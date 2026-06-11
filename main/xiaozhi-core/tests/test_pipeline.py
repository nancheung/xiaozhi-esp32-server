"""端到端：音频帧入 -> 协议消息与音频帧出，覆盖高级元数据全链路与打断。"""

import asyncio

from xiaozhi_core import AdapterSet, DialogueState, PromptComposer, SpeakerInfo, XiaozhiServer
from xiaozhi_core.domain.events import AbortRequested, AudioFrameReceived
from xiaozhi_core.testing import (
    SILENCE_FRAME,
    VOICE_FRAME,
    EmotionalFakeTts,
    FakeAsr,
    FakeVad,
    FakeVoiceprint,
    InMemoryMemory,
    InMemoryTransport,
    NeutralFakeTts,
    ScriptedLlm,
)


def _make_runtime(tts, asr=None, memory=None, voiceprint=None):
    transport = InMemoryTransport()
    llm = ScriptedLlm()
    server = XiaozhiServer(
        adapters=AdapterSet(
            vad=FakeVad(),
            # 工具箱默认中性，本套用例的剧情是"疲惫(sad)用户"——显式注入
            asr=asr or FakeAsr(raw_emotion="<|SAD|>", speech_rate=-0.3),
            llm=llm,
            tts=tts,
            transport=transport,
            memory=memory,
            voiceprint=voiceprint,
        ),
        composer=PromptComposer("你是温暖的陪伴助手。"),
    )
    return server.create_session(), transport, llm


async def _speak_one_utterance(runtime):
    for frame in [VOICE_FRAME, VOICE_FRAME, VOICE_FRAME, SILENCE_FRAME, SILENCE_FRAME]:
        await runtime.emit(AudioFrameReceived(frame=frame))


def test_full_turn_emotional_chain():
    async def run():
        tts = EmotionalFakeTts()
        memory = InMemoryMemory("用户上周说过工作压力大")
        runtime, transport, llm = _make_runtime(tts, memory=memory)
        await runtime.start()
        await _speak_one_utterance(runtime)

        # 出站协议时序与现状一致：stt -> tts:start -> sentence_start... -> tts:stop
        states = [
            (m["type"], m.get("state")) for m in transport.sent_events if m["type"] != "hello"
        ]
        assert states[0] == ("stt", None)
        assert states[1] == ("tts", "start")
        assert ("tts", "sentence_start") in states
        assert states[-1] == ("tts", "stop")
        assert transport.sent_audio  # 有音频帧出站

        # 案例2：asr.emotion 的消费者是提示词模板（非 LLM 端口）
        system_text = "\n".join(m["content"] for m in llm.last_messages if m["role"] == "system")
        assert "用户当前情绪：sad" in system_text
        assert "相关记忆：用户上周说过工作压力大" in system_text
        # 案例4：TTS 软需求反向激活了 LLM 输出契约
        assert "[输出规范]" in system_text

        # 案例3+4：LLM 输出的 <speak> 被解析为 Prosody 并映射到厂商参数
        assert tts.synth_calls
        assert all(params["emotion"] == "warm" for _, params in tts.synth_calls)
        # 标签不进入 TTS 文本与字幕
        assert all("<speak" not in text for text, _ in tts.synth_calls)

    asyncio.run(run())


def test_neutral_tts_degrades_gracefully():
    async def run():
        tts = NeutralFakeTts()
        runtime, transport, llm = _make_runtime(tts)
        await runtime.start()
        await _speak_one_utterance(runtime)

        system_text = "\n".join(m["content"] for m in llm.last_messages if m["role"] == "system")
        assert "用户当前情绪：sad" in system_text  # 共情线独立保留
        assert "[输出规范]" not in system_text  # 契约关闭，prompt 精简
        assert tts.synth_calls and all("<speak" not in t for t in tts.synth_calls)
        assert [m.get("state") for m in transport.sent_events if m["type"] == "tts"][-1] == "stop"

    asyncio.run(run())


def test_plain_asr_no_emotion_line():
    async def run():
        runtime, _, llm = _make_runtime(EmotionalFakeTts(), asr=FakeAsr(supports_emotion=False))
        await runtime.start()
        await _speak_one_utterance(runtime)
        system_text = "\n".join(m["content"] for m in llm.last_messages if m["role"] == "system")
        assert "用户当前情绪" not in system_text  # 占位符行整行丢弃
        assert "[输出规范]" in system_text  # TTS 需求与 ASR 能力无关

    asyncio.run(run())


def test_voiceprint_enrichment():
    async def run():
        speaker = SpeakerInfo(name="阿珍", description="家人，喜欢开玩笑")
        runtime, _, llm = _make_runtime(EmotionalFakeTts(), voiceprint=FakeVoiceprint(speaker))
        await runtime.start()
        await _speak_one_utterance(runtime)
        system_text = "\n".join(m["content"] for m in llm.last_messages if m["role"] == "system")
        assert "阿珍" in system_text  # 声纹经黑板进入动态块

    asyncio.run(run())


def test_dialogue_history_accumulates():
    async def run():
        runtime, _, llm = _make_runtime(EmotionalFakeTts())
        await runtime.start()
        await _speak_one_utterance(runtime)
        await _speak_one_utterance(runtime)
        history = runtime.session.dialogue.history_messages()
        roles = [m.role for m in history]
        assert roles == ["user", "assistant", "user", "assistant"]
        # 第二轮的 messages 含第一轮历史
        user_turns = [m for m in llm.last_messages if m["role"] == "user"]
        assert len(user_turns) == 2

    asyncio.run(run())


def test_abort_stops_output():
    async def run():
        runtime, transport, _ = _make_runtime(EmotionalFakeTts())
        await runtime.start()
        await _speak_one_utterance(runtime)
        before = len(transport.sent_audio)

        # 新一轮开始后立刻打断
        await runtime.emit(AudioFrameReceived(frame=VOICE_FRAME))
        await runtime.emit(AbortRequested())
        assert runtime.session.current_turn is None
        stops = [m for m in transport.sent_events if m["type"] == "tts" and m["state"] == "stop"]
        assert stops  # 打断即下发 tts:stop
        await runtime.emit(AudioFrameReceived(frame=SILENCE_FRAME))
        await runtime.emit(AudioFrameReceived(frame=SILENCE_FRAME))
        assert len(transport.sent_audio) >= before  # 不再产生新一轮音频前的残留

    asyncio.run(run())


def test_llm_failure_converges_turn_and_session_recovers():
    """LLM 抛错不能让会话卡死：本轮收束（tts:stop + 回 IDLE），下一轮正常对话。"""

    class FlakyLlm(ScriptedLlm):
        def __init__(self):
            super().__init__()
            self.fail_next = True

        async def stream(self, messages, tools=None):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("LLM 网络故障")
                yield  # pragma: no cover —— 保持 async generator 形态
            async for delta in super().stream(messages, tools):
                yield delta

    async def run():
        tts = EmotionalFakeTts()
        transport = InMemoryTransport()
        llm = FlakyLlm()
        server = XiaozhiServer(
            adapters=AdapterSet(
                vad=FakeVad(), asr=FakeAsr(), llm=llm, tts=tts, transport=transport
            ),
            composer=PromptComposer("你是助手。"),
        )
        runtime = server.create_session()
        await runtime.start()

        await _speak_one_utterance(runtime)  # 第一轮：LLM 抛错
        assert runtime.state_machine.state is DialogueState.IDLE  # 状态机已收束
        assert runtime.session.current_turn is None
        stops = [m for m in transport.sent_events if m.get("state") == "stop"]
        assert stops  # 设备侧收到 tts:stop，播放收束

        await _speak_one_utterance(runtime)  # 第二轮：正常对话
        assert tts.synth_calls  # 第二轮产出了语音
        assert runtime.state_machine.state is DialogueState.IDLE

    asyncio.run(run())


def test_session_stop_saves_memory():
    async def run():
        memory = InMemoryMemory()
        runtime, transport, _ = _make_runtime(EmotionalFakeTts(), memory=memory)
        await runtime.start()
        await _speak_one_utterance(runtime)
        await runtime.stop()
        assert memory.saved and memory.saved[0][1] == 2  # user + assistant
        assert transport.closed

    asyncio.run(run())

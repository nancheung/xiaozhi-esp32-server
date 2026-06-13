"""豆包端到端样例（examples/doubao_realtime）的离线测试。

不连真实豆包：协议层做二进制往返测试；编排层用 FakeDoubaoClient 回放
预置 ServerMessage 序列，驱动 DoubaoRealtimeStage 走完整轮次 / 打断 /
本地 LLM 接管，断言状态机与出站协议时序。
"""

import asyncio
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

from doubao_realtime import protocol
from doubao_realtime.echo_llm import EchoLlm
from doubao_realtime.stage import DoubaoRealtimeStage
from xiaozhi_core import AdapterSet, DialogueState, PromptComposer, XiaozhiServer
from xiaozhi_core.domain.events import AudioFrameReceived, TurnCompleted
from xiaozhi_core.domain.pipeline import Pipeline
from xiaozhi_core.domain.stages import AudioOutputStage
from xiaozhi_core.testing import (
    FakeAsr,
    FakeVad,
    InMemoryMemory,
    InMemoryTransport,
    NeutralFakeTts,
    ScriptedLlm,
)

# ---------------------------------------------------------------------------
# 协议层：二进制帧往返
# ---------------------------------------------------------------------------


def test_server_full_response_roundtrip():
    frame = protocol.encode_frame(
        protocol.SERVER_FULL_RESPONSE,
        event=protocol.EVENT_ASR_ENDED,
        session_id="sid-1",
        payload=json.dumps({"a": 1}).encode(),
    )
    msg = protocol.parse_server_message(frame)
    assert msg.kind == "full_response"
    assert msg.event == protocol.EVENT_ASR_ENDED
    assert msg.session_id == "sid-1"
    assert msg.payload == {"a": 1}


def test_server_ack_carries_raw_audio():
    frame = protocol.encode_frame(
        protocol.SERVER_ACK,
        event=352,
        session_id="sid-1",
        payload=b"\x01\x02\x03",
        serialization=protocol.NO_SERIALIZATION,
    )
    msg = protocol.parse_server_message(frame)
    assert msg.kind == "ack"
    assert msg.audio == b"\x01\x02\x03"


def test_server_error_response():
    payload = gzip.compress(json.dumps({"error": "bad"}).encode())
    frame = (
        bytes([0x11, (protocol.SERVER_ERROR_RESPONSE << 4), 0x11, 0x00])
        + (55000000).to_bytes(4, "big")
        + len(payload).to_bytes(4, "big")
        + payload
    )
    msg = protocol.parse_server_message(frame)
    assert msg.kind == "error"
    assert msg.code == 55000000
    assert msg.payload == {"error": "bad"}


def test_marshal_audio_frame_layout():
    frame = protocol.marshal_audio("sid", b"PCMPCM")
    assert frame[1] >> 4 == protocol.CLIENT_AUDIO_ONLY_REQUEST
    assert int.from_bytes(frame[4:8], "big") == protocol.EVENT_TASK_REQUEST
    sid_len = int.from_bytes(frame[8:12], "big")
    assert frame[12 : 12 + sid_len] == b"sid"
    body = frame[12 + sid_len :]
    assert gzip.decompress(body[4:]) == b"PCMPCM"


def test_marshal_event_payload_is_gzip_json():
    frame = protocol.marshal_event(
        protocol.EVENT_CHAT_TTS_TEXT, {"content": "你好"}, session_id="s"
    )
    assert frame[1] >> 4 == protocol.CLIENT_FULL_REQUEST
    assert int.from_bytes(frame[4:8], "big") == protocol.EVENT_CHAT_TTS_TEXT
    sid_len = int.from_bytes(frame[8:12], "big")
    body = frame[12 + sid_len :]
    assert json.loads(gzip.decompress(body[4:])) == {"content": "你好"}


def test_extract_asr_text_variants():
    assert protocol.extract_asr_text({"results": [{"text": "你好"}]}) == "你好"
    assert protocol.extract_asr_text({"text": "直取"}) == "直取"
    assert protocol.extract_asr_text({"results": []}) == ""
    assert protocol.extract_asr_text(None) == ""


# ---------------------------------------------------------------------------
# 编排层：FakeDoubaoClient 回放驱动 stage
# ---------------------------------------------------------------------------


def full(event, payload=None):
    return protocol.ServerMessage(kind="full_response", event=event, payload=payload)


def ack(audio):
    return protocol.ServerMessage(kind="ack", audio=audio)


class FakeDoubaoClient:
    """回放预置消息序列；记录出站调用供断言。"""

    def __init__(self, script):
        self._script = list(script)
        self.sent_audio = []
        self.chat_tts_texts = []
        self.rag_texts = []
        self.hellos = []
        self.closed = False
        self.drained = asyncio.Event()
        self._closing = asyncio.Event()

    async def connect(self):
        pass

    async def say_hello(self, content):
        self.hellos.append(content)

    async def send_audio(self, pcm):
        self.sent_audio.append(pcm)

    async def send_chat_tts_text(self, *, start, end, content):
        self.chat_tts_texts.append((start, end, content))

    async def send_chat_rag_text(self, *, external_rag):
        self.rag_texts.append(external_rag)

    async def messages(self):
        for message in self._script:
            yield message
        self.drained.set()
        await self._closing.wait()  # 脚本播完后保持连接，直到会话关闭

    async def close(self):
        self.closed = True
        self._closing.set()


def make_runtime(client, use_local_llm=False, say_hello=None, memory=None, comfort_text=None):
    transport = InMemoryTransport()
    llm = EchoLlm() if use_local_llm else ScriptedLlm()
    server = XiaozhiServer(
        adapters=AdapterSet(
            vad=FakeVad(),
            asr=FakeAsr(supports_emotion=False),
            llm=llm,
            tts=NeutralFakeTts(),
            transport=transport,
            memory=memory,
        ),
        composer=PromptComposer("你是语音助手。"),
        pipeline_factory=lambda: Pipeline(
            [
                DoubaoRealtimeStage(
                    client,
                    use_local_llm=use_local_llm,
                    comfort_text=comfort_text,
                    say_hello=say_hello,
                ),
                AudioOutputStage(),
            ]
        ),
    )
    return server.create_session(), transport, llm


async def run_script(client, runtime, inbound_frames=()):
    await runtime.start()  # SessionStarted -> stage 建连并启动接收循环
    for frame in inbound_frames:
        await runtime.emit(AudioFrameReceived(frame=frame))
    await asyncio.wait_for(client.drained.wait(), timeout=2)


def test_full_turn_cloud_mode():
    """450/451/459 -> ack 音频 -> 359：完整一轮，云端 LLM 文本进 assistant_text。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "今天天气怎么样"}]}),
                full(459),
                full(550, {"content": "今天"}),
                full(550, {"content": "晴。"}),
                ack(b"A1"),
                ack(b"A2"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(client)
        completed: list[TurnCompleted] = []
        runtime.bus.subscribe(TurnCompleted, lambda e: completed.append(e))

        await run_script(client, runtime, inbound_frames=[b"\x00" * 64])

        assert client.sent_audio == [b"\x00" * 64]  # 入站音频直通豆包
        kinds = [(m.get("type"), m.get("state")) for m in transport.sent_events]
        assert kinds == [
            ("stt", None),
            ("tts", "start"),
            ("tts", "sentence_start"),  # 550 增量切句下发回复文本
            ("tts", "stop"),
        ]
        assert transport.sent_events[0]["text"] == "今天天气怎么样"
        assert transport.sent_events[2]["text"] == "今天晴。"
        assert transport.sent_audio == [b"A1", b"A2"]
        assert runtime.state_machine.state is DialogueState.IDLE
        assert len(completed) == 1
        assert completed[0].user_text == "今天天气怎么样"
        assert completed[0].assistant_text == "今天晴。"

        await runtime.stop()
        assert client.closed

    asyncio.run(run())


def test_interrupt_drops_stale_audio():
    """SPEAKING 中收到 450 = 用户打断：旧轮残留 ack 被过滤，新轮正常下发。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "第一句"}]}),
                full(459),
                ack(b"OLD-1"),
                full(450),  # 打断
                ack(b"OLD-2"),  # 旧轮残留，应被丢弃
                full(451, {"results": [{"text": "第二句"}]}),
                full(459),
                ack(b"NEW-1"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(client)
        await run_script(client, runtime)

        assert transport.sent_audio == [b"OLD-1", b"NEW-1"]
        # 打断时 TurnAborted 下发了 tts:stop，新轮再 stt/tts:start/tts:stop
        kinds = [(m.get("type"), m.get("state")) for m in transport.sent_events]
        assert kinds == [
            ("stt", None),
            ("tts", "start"),
            ("tts", "stop"),  # TurnAborted
            ("stt", None),
            ("tts", "start"),
            ("tts", "stop"),
        ]
        assert runtime.state_machine.state is DialogueState.IDLE
        await runtime.stop()

    asyncio.run(run())


def test_empty_asr_cancels_turn_silently():
    async def run():
        client = FakeDoubaoClient([full(450), full(459)])
        runtime, transport, _ = make_runtime(client)
        await run_script(client, runtime)

        assert transport.sent_events == []
        assert runtime.state_machine.state is DialogueState.IDLE
        await runtime.stop()

    asyncio.run(run())


def test_local_llm_takeover_via_chat_tts_text():
    """本地 EchoLlm 接管：回复经 ChatTTSText 注入，云端自答音频被丢弃。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "你好"}]}),
                full(459),
                full(550, {"content": "云端自答"}),  # 接管模式下不记入 assistant_text
                ack(b"CLOUD"),  # 云端自答音频，应被丢弃
                full(350, {"tts_type": "chat_tts_text"}),  # 注入文本的音频开始
                ack(b"LOCAL"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(client, use_local_llm=True)
        completed: list[TurnCompleted] = []
        runtime.bus.subscribe(TurnCompleted, lambda e: completed.append(e))
        await run_script(client, runtime)

        assert client.chat_tts_texts == [(True, False, "用户刚说了：你好"), (False, True, "")]
        assert transport.sent_audio == [b"LOCAL"]
        assert completed[0].assistant_text == "用户刚说了：你好"
        assert runtime.state_machine.state is DialogueState.IDLE
        await runtime.stop()

    asyncio.run(run())


def test_say_hello_audio_passes_without_turn():
    """开场白：无轮次语境下豆包音频直接放行（turn_id=None 不被陈旧过滤）。"""

    async def run():
        client = FakeDoubaoClient([ack(b"HELLO-PCM"), full(359)])
        runtime, transport, _ = make_runtime(client, say_hello="你好呀")
        await run_script(client, runtime)

        assert client.hellos == ["你好呀"]
        assert transport.sent_audio == [b"HELLO-PCM"]
        assert runtime.state_machine.state is DialogueState.IDLE
        await runtime.stop()

    asyncio.run(run())


def test_memory_rag_injection():
    """知识注入分支：记忆经 ChatRAGText(502) 注入，安抚话术先发，云端自答音频被丢弃。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "我的猫叫什么"}]}),
                full(459),
                ack(b"CLOUD"),  # 注入前的云端自答音频，应被丢弃
                full(350, {"tts_type": "chat_tts_text"}),  # 安抚话术音频开始
                ack(b"COMFORT"),
                full(350, {"tts_type": "external_rag"}),  # 融合记忆后的回答音频
                ack(b"RAG"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(
            client, memory=InMemoryMemory("记忆内容"), comfort_text="稍等。"
        )
        await run_script(client, runtime)

        assert client.chat_tts_texts == [(True, False, "稍等。"), (False, True, "")]
        sentences = [m["text"] for m in transport.sent_events if m.get("state") == "sentence_start"]
        assert sentences == ["稍等。"]  # 安抚话术也以 sentence_start 下发
        assert client.rag_texts == [
            json.dumps([{"title": "用户记忆", "content": "记忆内容"}], ensure_ascii=False)
        ]
        assert transport.sent_audio == [b"COMFORT", b"RAG"]
        assert runtime.state_machine.state is DialogueState.IDLE
        await runtime.stop()

    asyncio.run(run())


def test_memory_rag_skipped_without_memory():
    """未装配 memory：注入分支自动失活，纯端到端、音频不丢。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "你好"}]}),
                full(459),
                ack(b"E2E"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(client, comfort_text="稍等。")
        await run_script(client, runtime)

        assert client.rag_texts == []
        assert client.chat_tts_texts == []  # 不注入就不发安抚话术
        assert transport.sent_audio == [b"E2E"]
        await runtime.stop()

    asyncio.run(run())


def test_dropping_flag_resets_across_turns_after_abort():
    """首轮 RAG 注入被打断（未收到 350 恢复信号），第二轮纯端到端音频不应被丢弃。"""

    class OnceMemory:
        """第一次 query 返回内容，之后返回空（模拟首轮有记忆、次轮无记忆）。"""

        def __init__(self, content: str) -> None:
            self._content = content
            self._used = False

        async def query(self, text: str) -> str:
            if not self._used:
                self._used = True
                return self._content
            return ""

        async def save(self, role: str, content: str) -> None:
            pass

    async def run() -> None:
        client = FakeDoubaoClient(
            [
                # 轮次 1：RAG 注入开始，被打断，350 未到
                full(450),
                full(451, {"results": [{"text": "我的猫叫什么"}]}),
                full(459),
                ack(b"CLOUD-T1"),  # 注入期间音频，应被丢弃
                full(450),  # 用户再次说话，打断（THINKING 状态）
                # 轮次 2：memory 返回空，纯端到端
                full(451, {"results": [{"text": "你好"}]}),
                full(459),
                ack(b"CLOUD-T2"),  # 第二轮音频，不应被丢弃
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(client, memory=OnceMemory("猫叫年糕"))
        await run_script(client, runtime)

        assert b"CLOUD-T1" not in transport.sent_audio, "轮1云端音频应被丢弃"
        assert b"CLOUD-T2" in transport.sent_audio, "轮2端到端音频不应被丢弃（脏标志已重置）"
        await runtime.stop()

    asyncio.run(run())


def test_rag_injection_filters_cloud_550_text():
    """知识注入期间，云端 550 文本应被丢弃；350(external_rag) 后的 550 文本应放行。"""

    async def run() -> None:
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "讲一个故事"}]}),
                full(459),
                full(550, {"content": "那你得先告诉我"}),  # 注入前云端文本，应丢弃
                full(550, {"content": "一些信息。"}),  # 同上
                ack(b"CLOUD"),  # 云端原始音频，应丢弃
                full(350, {"tts_type": "chat_tts_text"}),  # 安抚话术 TTS 开始
                ack(b"COMFORT"),
                full(350, {"tts_type": "external_rag"}),  # RAG 音频开始，恢复放行
                full(550, {"content": "故事开始了。"}),  # RAG 生成文本，应放行
                ack(b"RAG"),
                full(359),
            ]
        )
        runtime, transport, _ = make_runtime(
            client, memory=InMemoryMemory("记忆内容"), comfort_text="稍等。"
        )
        await run_script(client, runtime)

        sentences = [m["text"] for m in transport.sent_events if m.get("state") == "sentence_start"]
        assert sentences == ["稍等。", "故事开始了。"]
        assert transport.sent_audio == [b"COMFORT", b"RAG"]
        await runtime.stop()

    asyncio.run(run())


def test_local_llm_uses_composer_and_memory():
    """照念分支：prompt 经 PromptComposer 拼装，记忆走 {memory} 占位符进本地 prompt。"""

    async def run():
        client = FakeDoubaoClient(
            [
                full(450),
                full(451, {"results": [{"text": "我的猫叫什么"}]}),
                full(459),
                full(350, {"tts_type": "chat_tts_text"}),
                ack(b"LOCAL"),
                full(359),
            ]
        )
        runtime, transport, llm = make_runtime(
            client, use_local_llm=True, memory=InMemoryMemory("猫叫年糕")
        )
        await run_script(client, runtime)

        roles = [m["role"] for m in llm.last_messages]
        assert roles[0] == "system" and roles[-1] == "user"
        system_text = "\n".join(m["content"] for m in llm.last_messages if m["role"] == "system")
        assert "你是语音助手。" in system_text
        assert "相关记忆：猫叫年糕" in system_text
        assert llm.last_messages[-1]["content"] == "我的猫叫什么"
        assert client.chat_tts_texts == [
            (True, False, "用户刚说了：我的猫叫什么"),
            (False, True, ""),
        ]
        sentences = [m["text"] for m in transport.sent_events if m.get("state") == "sentence_start"]
        assert sentences == ["用户刚说了：我的猫叫什么"]  # 照念文本整段下发
        # 历史落账：user + assistant 都进对话历史（memory.save 不再存空）
        history = [(m.role, m.content) for m in runtime.session.dialogue.history_messages()]
        assert history == [
            ("user", "我的猫叫什么"),
            ("assistant", "用户刚说了：我的猫叫什么"),
        ]
        await runtime.stop()

    asyncio.run(run())

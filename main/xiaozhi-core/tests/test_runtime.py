"""XiaozhiServer 会话工厂：装配模板不可被会话污染。

有状态 adapter（VAD 窗口、Transport 连接）是会话级实例：
- 静态 ``adapters=`` 是装配模板，``create_session(transport=...)`` 不得改写模板本体；
- 静态 adapters 只能开一个会话——多连接场景必须用 ``adapters_factory``，
  否则连接 2 的 transport 会顶掉连接 1（音频串到别人的设备），fail-fast 拒绝。
"""

import asyncio
from collections.abc import Callable

import pytest

from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer
from xiaozhi_core.domain.events import AbortRequested, AudioFrameReceived
from xiaozhi_core.testing import (
    SILENCE_FRAME,
    VOICE_FRAME,
    EmotionalFakeTts,
    FakeAsr,
    FakeVad,
    InMemoryTransport,
    NeutralFakeTts,
    ScriptedLlm,
)


def _adapter_set() -> AdapterSet:
    return AdapterSet(vad=FakeVad(), asr=FakeAsr(), llm=ScriptedLlm(), tts=EmotionalFakeTts())


def _server(**kwargs) -> XiaozhiServer:
    return XiaozhiServer(composer=PromptComposer("你是助手。"), **kwargs)


def test_static_adapters_template_not_mutated_by_transport():
    template = _adapter_set()
    server = _server(adapters=template)
    transport = InMemoryTransport()

    runtime = server.create_session(transport=transport)

    assert runtime.adapters.transport is transport
    assert template.transport is None  # 模板本体未被改写


def test_static_adapters_second_session_fails_fast():
    server = _server(adapters=_adapter_set())
    server.create_session(transport=InMemoryTransport())

    with pytest.raises(RuntimeError, match="adapters_factory"):
        server.create_session(transport=InMemoryTransport())


def test_adapters_factory_supports_multiple_isolated_sessions():
    server = _server(adapters_factory=_adapter_set)
    t1, t2 = InMemoryTransport(), InMemoryTransport()

    r1 = server.create_session(transport=t1)
    r2 = server.create_session(transport=t2)

    assert r1.adapters.transport is t1
    assert r2.adapters.transport is t2
    assert r1.adapters.vad is not r2.adapters.vad  # 有状态 adapter 各自独立


# ---------------------------------------------------------------------------
# run() 模式下的实时打断：abort 走旁路，不排在轮次后面
# ---------------------------------------------------------------------------

_SLOW_TTS_CHUNKS = 50


class _SlowTts(NeutralFakeTts):
    """每帧 sleep 的慢速 TTS：模拟真实播放时长，给打断留出窗口。"""

    async def synthesize(self, text, *, prosody=None):
        self.synth_calls.append(text)
        for i in range(_SLOW_TTS_CHUNKS):
            await asyncio.sleep(0.01)
            yield f"opus:{text}#{i}".encode()


async def _until(predicate: Callable[[], bool], deadline: float = 2.0) -> None:
    async with asyncio.timeout(deadline):
        # 测试桩没有通知机制，只能轮询观测出站列表的变化
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


def test_abort_during_speaking_interrupts_immediately():
    """SPEAKING 期间设备发来 abort：立即 tts:stop 并截断音频，而非等整轮播完。"""

    async def run():
        transport = InMemoryTransport()
        server = XiaozhiServer(
            adapters=AdapterSet(
                vad=FakeVad(),
                asr=FakeAsr(),
                llm=ScriptedLlm(reply="好的。"),
                tts=_SlowTts(),
                transport=transport,
            ),
            composer=PromptComposer("你是助手。"),
        )
        runtime = server.create_session()
        run_task = asyncio.create_task(runtime.run())

        for frame in [VOICE_FRAME, VOICE_FRAME, VOICE_FRAME, SILENCE_FRAME, SILENCE_FRAME]:
            await transport.feed(AudioFrameReceived(frame=frame))
        await _until(lambda: bool(transport.sent_audio))  # 已开始出声（SPEAKING）

        await transport.feed(AbortRequested())
        await _until(lambda: runtime.session.current_turn is None)  # 打断即收束本轮

        # 音频被截断：远少于整轮帧数，且打断后不再继续出帧
        audio_at_abort = len(transport.sent_audio)
        assert audio_at_abort < _SLOW_TTS_CHUNKS // 2
        await asyncio.sleep(0.05)
        assert len(transport.sent_audio) <= audio_at_abort + 1  # 容忍一帧在途
        assert {"type": "tts", "state": "stop", "session_id": runtime.session.session_id} in (
            transport.sent_events
        )

        await transport.finish()
        await asyncio.wait_for(run_task, timeout=2)
        assert transport.closed

    asyncio.run(run())

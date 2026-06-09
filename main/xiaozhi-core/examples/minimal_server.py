"""最小可运行示例：两种装配对比，展示能力协商与高级元数据全链路。

运行::

    uv run python examples/minimal_server.py

场景 A：带情绪的 ASR + 支持韵律的 TTS —— 全链路打通；
场景 B：同一 ASR/LLM，仅换成中性 TTS —— LLM 输出契约自动关闭，prompt 精简。
"""

import asyncio

from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer
from xiaozhi_core.adapters.testing import (
    SILENCE_FRAME,
    VOICE_FRAME,
    EmotionalFakeTts,
    FakeAsr,
    FakeVad,
    InMemoryMemory,
    InMemoryTransport,
    NeutralFakeTts,
    ScriptedLlm,
)
from xiaozhi_core.domain.events import AudioFrameReceived


async def run_scenario(title: str, tts) -> None:
    print(f"\n{'=' * 24} {title} {'=' * 24}")
    transport = InMemoryTransport()
    llm = ScriptedLlm()
    server = XiaozhiServer(
        adapters=AdapterSet(
            vad=FakeVad(),
            asr=FakeAsr(),
            llm=llm,
            tts=tts,
            transport=transport,
            memory=InMemoryMemory("用户上周提过工作压力大"),
        ),
        composer=PromptComposer("你是温暖的陪伴助手。"),
    )
    runtime = server.create_session()

    print("—— 装配期能力协商 ——")
    print(runtime.negotiation.report())

    await runtime.start()
    for frame in [VOICE_FRAME, VOICE_FRAME, VOICE_FRAME, SILENCE_FRAME, SILENCE_FRAME]:
        await runtime.emit(AudioFrameReceived(frame=frame))

    print("\n—— LLM 实际收到的系统提示 ——")
    for message in llm.last_messages:
        if message["role"] == "system":
            print(f"  | {message['content']}".replace("\n", "\n  | "))

    print("\n—— 出站设备协议 ——")
    for message in transport.sent_events:
        print(f"  -> {message}")
    print(f"  -> 音频帧 ×{len(transport.sent_audio)}: {transport.sent_audio[:2]} ...")

    await runtime.stop()


async def main() -> None:
    await run_scenario("场景A：情绪ASR + 韵律TTS（全链路）", EmotionalFakeTts())
    await run_scenario("场景B：情绪ASR + 中性TTS（自动降级）", NeutralFakeTts())


if __name__ == "__main__":
    asyncio.run(main())

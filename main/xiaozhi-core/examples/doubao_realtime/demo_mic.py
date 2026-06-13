"""麦克风实时对话 demo：豆包端到端模型跑在 xiaozhi-core 编排上。

运行（先在 config.py 填好火山引擎凭据）::

    uv run --with websockets --with pyaudio python examples/doubao_realtime/demo_mic.py

config.use_local_llm = True 时，回复由本地 EchoLlm 生成（「用户刚说了：」+原话），
豆包仅做 ASR 与 TTS；False 则走豆包云端 LLM 的纯端到端模式。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):  # 支持直接 python demo_mic.py 运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from doubao_realtime import config
from doubao_realtime.client import DoubaoRealtimeClient
from doubao_realtime.echo_llm import EchoLlm
from doubao_realtime.jsonl_memory import JsonlMemory
from doubao_realtime.local_audio import MicTransport
from doubao_realtime.stage import DoubaoRealtimeStage
from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer
from xiaozhi_core.domain.pipeline import Pipeline
from xiaozhi_core.domain.stages import AudioOutputStage
from xiaozhi_core.testing import FakeAsr, FakeVad, NeutralFakeTts, ScriptedLlm


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    client = DoubaoRealtimeClient()
    server = XiaozhiServer(
        adapters=AdapterSet(
            # vad/asr/tts 槽用中性 Fake 占位：pipeline 不挂对应 stage，桩不会被执行；
            # llm 槽在本地照念模式下由 DoubaoRealtimeStage 真实调用。
            vad=FakeVad(),
            asr=FakeAsr(supports_emotion=False),
            llm=EchoLlm() if config.use_local_llm else ScriptedLlm(),
            tts=NeutralFakeTts(),
            transport=MicTransport(),
            # 装配 memory 即激活记忆链路：照念模式进本地 prompt，云端模式走 502 注入
            memory=JsonlMemory(config.jsonl_path),
        ),
        # 本地照念模式下 PromptComposer 真实参与拼 prompt（{memory} 占位符消费记忆）；
        # 云端模式人设在豆包 StartSession 的 dialog 配置里，composer 不参与。
        composer=PromptComposer("你是简洁友善的语音助手小智。"),
        pipeline_factory=lambda: Pipeline(
            [
                DoubaoRealtimeStage(
                    client,
                    use_local_llm=config.use_local_llm,
                    comfort_text=config.comfort_text,
                    say_hello=config.say_hello_content,
                ),
                AudioOutputStage(),
            ]
        ),
    )
    await server.create_session().run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出。")

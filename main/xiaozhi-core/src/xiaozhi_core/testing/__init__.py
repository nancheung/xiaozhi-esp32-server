"""``xiaozhi_core.testing``：受支持的公共测试工具箱。

面向**下游 adapter 作者**：当你为某个 Port 写真实实现（自家 ASR/TTS/LLM…）时，
可直接复用这里的零依赖 Fake 装配出一条完整会话，对编排行为做断言，而无需任何
外部服务。每个 Port 都有对应 Fake，覆盖能力声明、装配期协商、优雅降级等链路。

随正式发行包一起发布——与 ``litellm`` / ``fastapi`` 等技术适配器不同，本工具箱零
外部依赖，可在任意测试环境直接导入::

    from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer
    from xiaozhi_core.testing import FakeVad, FakeAsr, ScriptedLlm, EmotionalFakeTts

    server = XiaozhiServer(
        adapters=AdapterSet(vad=FakeVad(), asr=FakeAsr(), llm=ScriptedLlm(), tts=MyTts()),
        composer=PromptComposer("你是助手。"),
    )
"""

from __future__ import annotations

from .fakes import (
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

__all__ = [
    "SILENCE_FRAME",
    "VOICE_FRAME",
    "EmotionalFakeTts",
    "FakeAsr",
    "FakeVad",
    "FakeVoiceprint",
    "InMemoryMemory",
    "InMemoryTransport",
    "NeutralFakeTts",
    "ScriptedLlm",
]

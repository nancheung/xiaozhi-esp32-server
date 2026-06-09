"""端口契约（Driven / Driving Ports）。

领域核心只依赖本包的抽象；任何具体实现（silero / openai / litellm / FastAPI）
都在 adapters 层。端口同时是能力声明点（``SignalAware``）。
"""

from .asr import AsrPort
from .intent import IntentPort, IntentResult
from .llm import LlmDelta, LlmPort, ToolCallDelta
from .memory import MemoryPort
from .report import ReportPort
from .tools import CompositeToolPort, SessionToolProvider, StaticToolProvider, ToolPort
from .transport import TransportPort
from .tts import TtsPort
from .vad import VadPort, VadResult
from .vision import VisionPort
from .voiceprint import VoiceprintPort

__all__ = [
    "AsrPort",
    "CompositeToolPort",
    "IntentPort",
    "IntentResult",
    "LlmDelta",
    "LlmPort",
    "MemoryPort",
    "ReportPort",
    "SessionToolProvider",
    "StaticToolProvider",
    "ToolCallDelta",
    "ToolPort",
    "TransportPort",
    "TtsPort",
    "VadPort",
    "VadResult",
    "VisionPort",
    "VoiceprintPort",
]

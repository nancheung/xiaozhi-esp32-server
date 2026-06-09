"""xiaozhi-core：小智服务端领域核心（六边形架构 + 事件驱动）。

接入方三步启动定制化小智服务端::

    from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer

    server = XiaozhiServer(
        adapters=AdapterSet(vad=..., asr=..., llm=..., tts=...),
        composer=PromptComposer("你是温暖的陪伴助手。"),
    )
    runtime = server.create_session(transport=...)
    await runtime.run()
"""

from .domain import (
    Action,
    ActionResponse,
    Dialogue,
    DialogueState,
    DialogueStateMachine,
    EventBus,
    Message,
    MetadataBag,
    PerceivedEmotion,
    Pipeline,
    Prosody,
    RenderEmotion,
    S,
    SessionContext,
    Signal,
    SignalAware,
    SpeakerInfo,
    SpeakTagDirective,
    Stage,
    ToolDefinition,
    TurnContext,
    negotiate,
    register_signal,
)
from .domain.services import (
    AudioRateController,
    PromptComposer,
    SentenceSegmenter,
    WordCorrector,
)
from .runtime import AdapterSet, CoreSettings, SessionRuntime, XiaozhiServer

__all__ = [
    "Action",
    "ActionResponse",
    "AdapterSet",
    "AudioRateController",
    "CoreSettings",
    "Dialogue",
    "DialogueState",
    "DialogueStateMachine",
    "EventBus",
    "Message",
    "MetadataBag",
    "PerceivedEmotion",
    "Pipeline",
    "PromptComposer",
    "Prosody",
    "RenderEmotion",
    "S",
    "SentenceSegmenter",
    "SessionContext",
    "SessionRuntime",
    "Signal",
    "SignalAware",
    "SpeakTagDirective",
    "SpeakerInfo",
    "Stage",
    "ToolDefinition",
    "TurnContext",
    "WordCorrector",
    "XiaozhiServer",
    "negotiate",
    "register_signal",
]

__version__ = "0.1.0"

"""领域事件分类（架构文档 2.3 / 7.6）。

四类事件共用 ``Event`` 基类：
- 入站事件：Transport 把设备原始输入翻译为这些事件投递进来。
- 领域内部事件：stage 之间流转。
- 生命周期事件：hook 的主战场（上报 / 日志 / 埋点订阅于此）。

陈旧数据过滤：所有轮次相关事件携带 ``turn_id``，出站侧统一比对当前轮次。
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .signals import SpeakerInfo


class Event(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str = ""
    turn_id: str | None = None
    ts: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 入站事件（设备 / Transport -> 核心）
# ---------------------------------------------------------------------------


class HelloReceived(Event):
    payload: dict[str, Any] = Field(default_factory=dict)


class AudioFrameReceived(Event):
    frame: bytes


class ListenStateChanged(Event):
    state: str  # "start" | "stop" | "detect"
    text: str | None = None  # detect 模式下设备侧已识别的文本


class AbortRequested(Event):
    pass


class IotDescriptorsReceived(Event):
    descriptors: list[dict[str, Any]] = Field(default_factory=list)


class IotStatesReceived(Event):
    states: list[dict[str, Any]] = Field(default_factory=list)


class McpToolsListed(Event):
    tools: list[dict[str, Any]] = Field(default_factory=list)


class PingReceived(Event):
    pass


# ---------------------------------------------------------------------------
# 领域内部事件（stage 之间流转）
# ---------------------------------------------------------------------------


class VoiceStarted(Event):
    pass


class VoiceStopped(Event):
    pass


class AsrFinalized(Event):
    text: str


class SpeakerIdentified(Event):
    speaker: SpeakerInfo


class IntentDetected(Event):
    handled: bool = False
    intent: str | None = None
    reply: str | None = None


class LlmTokenStreamed(Event):
    token: str


class LlmToolCallRequested(Event):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecuted(Event):
    call_id: str
    name: str
    action: str
    result: str | None = None


class SentencePosition(StrEnum):
    FIRST = "FIRST"
    MIDDLE = "MIDDLE"
    LAST = "LAST"


class TtsSentenceSegmented(Event):
    position: SentencePosition
    text: str = ""


class TtsAudioChunkReady(Event):
    chunk: bytes


class AudioChunkSent(Event):
    size: int


# ---------------------------------------------------------------------------
# 生命周期事件（hook 主战场）
# ---------------------------------------------------------------------------


class SessionStarted(Event):
    pass


class SessionEnded(Event):
    pass


class TurnStarted(Event):
    pass


class TurnCompleted(Event):
    user_text: str = ""
    assistant_text: str = ""


class TurnAborted(Event):
    pass


class TtsStarted(Event):
    pass


class TtsStopped(Event):
    pass

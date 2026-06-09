"""上报端口：聊天记录 / 工具调用上报（由 ReportHook 订阅事件后调用）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ReportKind(StrEnum):
    ASR = "asr"
    TTS = "tts"
    TOOL = "tool"


class ReportPort(ABC):
    @abstractmethod
    async def report(
        self,
        kind: ReportKind,
        text: str,
        audio: bytes | None = None,
    ) -> None: ...

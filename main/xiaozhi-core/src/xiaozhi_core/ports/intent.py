"""意图端口：LLM 之前的前置路由（唤醒词 / 退出词 / 快捷指令）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..domain.dialogue import Message

if TYPE_CHECKING:
    from ..domain.context import TurnContext


class IntentResult(BaseModel):
    handled: bool = False
    intent: str | None = None
    reply: str | None = None  # handled 时可携带直接回复（走 TTS，跳过 LLM）


class IntentPort(ABC):
    @abstractmethod
    async def detect(
        self, history: list[Message], text: str, turn: TurnContext
    ) -> IntentResult: ...

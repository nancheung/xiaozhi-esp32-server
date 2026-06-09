"""记忆端口：每轮查询注入动态块，会话结束时保存。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.dialogue import Message


class MemoryPort(ABC):
    @abstractmethod
    async def query(self, text: str) -> str | None:
        """按当前用户输入检索相关记忆，返回注入提示词的文本。"""

    @abstractmethod
    async def save(self, messages: list[Message], session_id: str) -> None:
        """会话结束时保存对话历史。"""

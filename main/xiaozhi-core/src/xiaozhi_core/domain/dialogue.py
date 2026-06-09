"""对话历史聚合：真实历史与虚拟（few-shot）消息共存于一个时间线。

``is_temporary=True`` 标记虚拟消息（工具调用 few-shot 示例等），
由 ``PromptComposer`` 在拼装时与真实历史分段放置（架构文档 7.2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    is_temporary: bool = False

    def to_llm(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


@dataclass(slots=True)
class Dialogue:
    messages: list[Message] = field(default_factory=list)

    def put(self, message: Message) -> None:
        self.messages.append(message)

    def fewshot_messages(self) -> list[Message]:
        return [m for m in self.messages if m.is_temporary and m.role != "system"]

    def history_messages(self) -> list[Message]:
        return [m for m in self.messages if not m.is_temporary and m.role != "system"]

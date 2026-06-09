"""工具执行的领域契约（架构文档 7.5）。

``Action`` 决定 LLM 工具循环的走向：
- ``RESPONSE``：工具已给出最终回复，直接转 TTS。
- ``REQLLM``：工具结果回灌 LLM 继续推理。
- ``RECORD``：异步动作已触发（如播放音乐），用 response 简短播报。
- ``ERROR``：执行失败。
- ``NONE``：无需任何后续。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Action(StrEnum):
    RESPONSE = "response"
    REQLLM = "reqllm"
    RECORD = "record"
    ERROR = "error"
    NONE = "none"


class ActionResponse(BaseModel):
    action: Action
    response: str | None = None
    result: str | None = None


class ToolDefinition(BaseModel):
    """OpenAI function-call 格式的工具定义。"""

    name: str
    description: dict[str, Any] = Field(default_factory=dict)

    def to_schema(self) -> dict[str, Any]:
        return self.description

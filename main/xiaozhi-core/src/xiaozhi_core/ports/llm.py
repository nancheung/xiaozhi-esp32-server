"""LLM 端口：流式生成，逐 delta 产出文本与工具调用增量。

LLM 端口对情绪等元数据**无感知**：消费由 PromptComposer 模板完成，
生产由协商激活的 DirectiveProvider（输出契约 + 解析器）完成。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from ..domain.capabilities import SignalAware


class ToolCallDelta(BaseModel):
    call_id: str
    name: str | None = None
    arguments_fragment: str = ""


class LlmDelta(BaseModel):
    text: str | None = None
    tool_call: ToolCallDelta | None = None


class LlmPort(SignalAware, ABC):
    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmDelta]:
        """流式生成。``tools`` 为 OpenAI function-call 格式的工具 schema。"""

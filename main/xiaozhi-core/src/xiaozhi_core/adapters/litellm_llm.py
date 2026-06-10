"""litellm LLM 适配器：一个适配器统一 OpenAI / Ollama / Gemini 等多厂商。

安装：``pip install "xiaozhi-core[llm]"``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..ports.llm import LlmDelta, LlmPort, ToolCallDelta


def resolve_tool_call_delta(call: Any, index_to_id: dict[int, str]) -> ToolCallDelta:
    """流式 tool_call 分片 -> ``ToolCallDelta``（协议防腐层，纯函数可单测）。

    OpenAI 流式协议中 ``id``/``name`` 仅出现在每个工具调用的首个 delta，
    后续参数分片靠 ``index`` 关联；``index_to_id`` 跨分片记住映射，保证同一
    调用的全部分片解析到同一个 ``call_id``。全程无 id 的厂商退化为
    ``call_{index}``。
    """
    index = getattr(call, "index", None) or 0
    call_id = getattr(call, "id", None)
    if call_id:
        index_to_id[index] = call_id
    function = getattr(call, "function", None)
    return ToolCallDelta(
        call_id=index_to_id.get(index, f"call_{index}"),
        name=getattr(function, "name", None),
        arguments_fragment=getattr(function, "arguments", None) or "",
    )


class LiteLlmAdapter(LlmPort):
    def __init__(self, model: str, **completion_params: Any) -> None:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover
            raise ImportError('需要 litellm：pip install "xiaozhi-core[llm]"') from exc
        self._litellm = litellm
        self._model = model
        self._params = completion_params

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmDelta]:
        response = await self._litellm.acompletion(
            model=self._model,
            messages=messages,
            tools=tools or None,
            stream=True,
            **self._params,
        )
        index_to_id: dict[int, str] = {}
        async for chunk in response:
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            tool_calls = getattr(delta, "tool_calls", None) or []
            if text:
                yield LlmDelta(text=text)
            for call in tool_calls:
                yield LlmDelta(tool_call=resolve_tool_call_delta(call, index_to_id))

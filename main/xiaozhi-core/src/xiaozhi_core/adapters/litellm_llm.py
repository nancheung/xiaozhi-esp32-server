"""litellm LLM 适配器：一个适配器统一 OpenAI / Ollama / Gemini 等多厂商。

安装：``pip install "xiaozhi-core[llm]"``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..ports.llm import LlmDelta, LlmPort, ToolCallDelta


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
        async for chunk in response:
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            tool_calls = getattr(delta, "tool_calls", None) or []
            if text:
                yield LlmDelta(text=text)
            for call in tool_calls:
                function = getattr(call, "function", None)
                yield LlmDelta(
                    tool_call=ToolCallDelta(
                        call_id=getattr(call, "id", None) or f"call_{call.index}",
                        name=getattr(function, "name", None),
                        arguments_fragment=getattr(function, "arguments", None) or "",
                    )
                )

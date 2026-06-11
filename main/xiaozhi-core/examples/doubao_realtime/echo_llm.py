"""本地 Fake LLM 样例：演示「本地 LLM 接管云端回复」的接线方式。

豆包本身自带云端 LLM；本样例在 459（用户说完）后不等云端回复，而是用本地
``EchoLlm`` 生成文本（「用户刚说了：」+原话），经 ChatTTSText(event 500) 注入、
由豆包仅做 TTS 播报。把 ``EchoLlm`` 换成任意 ``LlmPort`` 实现（如 litellm
adapter）即可接入真实本地/自有模型。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from xiaozhi_core.ports.llm import LlmDelta, LlmPort

ECHO_PREFIX = "用户刚说了："


class EchoLlm(LlmPort):
    """回声 LLM：流式产出「用户刚说了：」+ 最后一条用户消息原话。

    记录最近一次收到的 messages（``last_messages``）供测试断言 prompt 拼装。
    """

    def __init__(self) -> None:
        self.last_messages: list[dict[str, Any]] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmDelta]:
        self.last_messages = messages
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        reply = ECHO_PREFIX + str(last_user)
        for i in range(0, len(reply), 8):  # 逐 8 字符流式，模拟 token 流
            await asyncio.sleep(0)
            yield LlmDelta(text=reply[i : i + 8])

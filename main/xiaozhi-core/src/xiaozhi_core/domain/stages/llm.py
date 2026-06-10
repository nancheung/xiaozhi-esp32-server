"""LlmStage：上下文拼装 -> 流式生成 -> 指令解析 -> 切句下发 -> 工具循环。

订阅 ``IntentDetected(handled=False)``。流程：
1. 用户消息入对话历史；查询记忆端口。
2. ``PromptComposer`` 四段拼装（含协商激活的 DirectiveProvider 契约片段）。
3. 流式消费 LLM：首部先经激活的指令解析器缓冲（``<speak ...>`` 标签在第一句
   合成前即解析完成、写入轮次黑板）；其余文本经切句器边产边发
   ``TtsSentenceSegmented``。
4. 工具调用增量聚合后经 ToolPort 执行，按 ``Action`` 决定直接回复 / 回灌
   LLM 继续推理（REQLLM 循环，限深）。
"""

from __future__ import annotations

import logging
from typing import Any

from ...ports.llm import ToolCallDelta
from ..actions import Action
from ..context import TurnContext
from ..dialogue import Message
from ..events import (
    Event,
    IntentDetected,
    LlmTokenStreamed,
    LlmToolCallRequested,
    SentencePosition,
    ToolExecuted,
    TtsSentenceSegmented,
)
from ..pipeline import Stage
from ..services.sentence_segmenter import SentenceSegmenter

logger = logging.getLogger(__name__)

_MAX_TOOL_DEPTH = 3


class LlmStage(Stage):
    subscribes = (IntentDetected,)

    async def handle(self, event: Event) -> None:
        assert isinstance(event, IntentDetected)
        if event.handled or self.is_stale(event):
            return
        turn = self.rt.session.current_turn
        if turn is None or turn.aborted:
            return
        # 故障收束：LLM / 记忆等任何环节抛错时补发 LAST 段，让 TtsStopped ->
        # on_finished 链路把状态机带回 IDLE——否则异常被事件总线吞掉后，
        # 会话将永久卡在 THINKING（后续语音事件全被状态机忽略）。
        try:
            await self._respond(turn)
        except Exception:
            logger.exception("LLM 轮次处理失败，收束本轮: turn_id=%s", turn.turn_id)
            if not turn.aborted:
                await self.rt.emit(TtsSentenceSegmented(position=SentencePosition.LAST))

    async def _respond(self, turn: TurnContext) -> None:
        session = self.rt.session
        session.dialogue.put(Message(role="user", content=turn.user_text))

        memory = None
        if self.rt.adapters.memory is not None:
            memory = await self.rt.adapters.memory.query(turn.user_text)

        messages = self.rt.composer.compose(
            session,
            turn,
            memory=memory,
            directive_fragment=self.rt.negotiation.directive_fragment,
        )

        tools_port = self.rt.adapters.tools
        tool_schemas = (
            [t.to_schema() for t in tools_port.list_tools()] if tools_port is not None else None
        )

        segmenter = SentenceSegmenter()
        emitted_any = False
        response_parts: list[str] = []

        async def emit_segment(text: str) -> None:
            nonlocal emitted_any
            position = SentencePosition.MIDDLE if emitted_any else SentencePosition.FIRST
            emitted_any = True
            await self.rt.emit(TtsSentenceSegmented(position=position, text=text))

        for _depth in range(_MAX_TOOL_DEPTH):
            tool_calls = await self._stream_once(
                turn, messages, tool_schemas, segmenter, response_parts, emit_segment
            )
            if turn.aborted:
                break
            if not tool_calls or tools_port is None:
                break
            messages, final_text = await self._run_tools(turn, messages, tool_calls)
            if final_text is not None:  # Action.RESPONSE / RECORD：工具给出最终回复
                response_parts.append(final_text)
                for segment in segmenter.feed(final_text):
                    await emit_segment(segment)
                break
            # Action.REQLLM：messages 已追加工具结果，回灌 LLM 继续

        remaining = segmenter.flush()
        if remaining and not turn.aborted:
            # 流式期间文本已逐 delta 计入 response_parts，此处仅补发未切句的尾段
            await emit_segment(remaining)
        if not turn.aborted:
            turn.assistant_text = "".join(response_parts)
            if turn.assistant_text:
                session.dialogue.put(Message(role="assistant", content=turn.assistant_text))
            await self.rt.emit(TtsSentenceSegmented(position=SentencePosition.LAST))

    async def _stream_once(
        self,
        turn: TurnContext,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]] | None,
        segmenter: SentenceSegmenter,
        response_parts: list[str],
        emit_segment: Any,
    ) -> dict[str, ToolCallDelta]:
        """单次 LLM 流式：返回聚合后的工具调用（无则空 dict）。"""
        directives = list(self.rt.negotiation.directives)
        head_buffer = ""
        head_done = not directives
        tool_calls: dict[str, ToolCallDelta] = {}

        async for delta in self.rt.adapters.llm.stream(messages, tools=tool_schemas):
            if turn.aborted:
                break
            if delta.tool_call is not None:
                self._merge_tool_call(tool_calls, delta.tool_call)
            if not delta.text:
                continue
            await self.rt.emit(LlmTokenStreamed(token=delta.text))

            text = delta.text
            if not head_done:
                head_buffer += text
                remaining, done = directives[0].try_extract(head_buffer, turn.meta)
                if not done:
                    continue
                head_done = True
                text = remaining
                if not text:
                    continue
            response_parts.append(text)
            for segment in segmenter.feed(text):
                await emit_segment(segment)

        if not head_done and head_buffer:  # 流结束仍未判定：原样放行
            remaining, _ = directives[0].try_extract(head_buffer + "\n", turn.meta)
            response_parts.append(remaining)
            for segment in segmenter.feed(remaining):
                await emit_segment(segment)
        return tool_calls

    @staticmethod
    def _merge_tool_call(acc: dict[str, ToolCallDelta], delta: ToolCallDelta) -> None:
        existing = acc.get(delta.call_id)
        if existing is None:
            acc[delta.call_id] = delta.model_copy()
            return
        if delta.name:
            existing.name = delta.name
        existing.arguments_fragment += delta.arguments_fragment

    async def _run_tools(
        self,
        turn: TurnContext,
        messages: list[dict[str, Any]],
        tool_calls: dict[str, ToolCallDelta],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """执行工具调用。返回 (追加结果后的 messages, 最终回复文本或 None)。"""
        import json

        tools_port = self.rt.adapters.tools
        assert tools_port is not None
        final_text: str | None = None
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name or "", "arguments": call.arguments_fragment},
                }
                for call in tool_calls.values()
            ],
        }
        messages = [*messages, assistant_msg]

        for call in tool_calls.values():
            try:
                arguments = json.loads(call.arguments_fragment) if call.arguments_fragment else {}
            except json.JSONDecodeError:
                arguments = {}
            name = call.name or ""
            await self.rt.emit(
                LlmToolCallRequested(call_id=call.call_id, name=name, arguments=arguments)
            )
            response = await tools_port.execute(name, arguments)
            await self.rt.emit(
                ToolExecuted(
                    call_id=call.call_id,
                    name=name,
                    action=response.action.value,
                    result=response.result or response.response,
                )
            )
            if response.action in (Action.RESPONSE, Action.RECORD) and response.response:
                final_text = response.response
            content = response.result or response.response or ""
            messages.append({"role": "tool", "tool_call_id": call.call_id, "content": content})
        return messages, final_text

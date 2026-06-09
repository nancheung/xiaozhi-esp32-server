"""IntentStage：LLM 前置路由。

订阅 ``AsrFinalized``（状态机已先行发布 TurnStarted）。无意图端口时
直接放行；意图被处理且带回复时，直通 TTS 段落事件，跳过 LLM。
"""

from __future__ import annotations

from ..events import AsrFinalized, Event, IntentDetected, SentencePosition, TtsSentenceSegmented
from ..pipeline import Stage


class IntentStage(Stage):
    subscribes = (AsrFinalized,)

    async def handle(self, event: Event) -> None:
        assert isinstance(event, AsrFinalized)
        if self.is_stale(event):
            return
        turn = self.rt.session.current_turn
        if turn is None or turn.aborted:
            return

        intent_port = self.rt.adapters.intent
        if intent_port is None:
            await self.rt.emit(IntentDetected(handled=False))
            return

        result = await intent_port.detect(
            self.rt.session.dialogue.history_messages(), event.text, turn
        )
        await self.rt.emit(IntentDetected(handled=result.handled, intent=result.intent))
        if result.handled and result.reply:
            turn.assistant_text = result.reply
            await self.rt.emit(
                TtsSentenceSegmented(position=SentencePosition.FIRST, text=result.reply)
            )
            await self.rt.emit(TtsSentenceSegmented(position=SentencePosition.LAST))

"""TtsStage：句段 -> 音频流。

订阅 ``TtsSentenceSegmented``。从轮次黑板读 ``S.prosody``（协商满足时由
DirectiveProvider 写入）传给 TtsPort——不支持韵律的实现忽略该参数即自然
降级。LAST 标记触发 ``TtsStopped``，状态机据此收束本轮。
"""

from __future__ import annotations

from ..events import (
    Event,
    SentencePosition,
    TtsAudioChunkReady,
    TtsSentenceSegmented,
    TtsStopped,
)
from ..pipeline import Stage
from ..signals import S


class TtsStage(Stage):
    subscribes = (TtsSentenceSegmented,)

    async def handle(self, event: Event) -> None:
        assert isinstance(event, TtsSentenceSegmented)
        if self.is_stale(event):
            return
        turn = self.rt.session.current_turn
        if turn is None or turn.aborted:
            return

        if event.position is SentencePosition.LAST:
            await self.rt.emit(TtsStopped())
            return
        if not event.text:
            return

        await self.rt.state_machine.on_speaking()
        prosody = turn.meta.get(S.prosody)
        async for chunk in self.rt.adapters.tts.synthesize(event.text, prosody=prosody):
            if turn.aborted:
                break
            await self.rt.emit(TtsAudioChunkReady(chunk=chunk))

"""AsrStage：语音段 -> 文本 + 元数据 enrichment。

订阅 ``VoiceStopped``（状态机已先行 begin_turn）。ASR 与声纹**并行**执行
（保留现状 gather 语义）；高级元数据（情绪/语速/语言/说话人）写入轮次黑板，
不压平进文本。结果为空则静默取消本轮。
"""

from __future__ import annotations

import asyncio
import logging

from ..events import AsrFinalized, Event, SpeakerIdentified, VoiceStopped
from ..pipeline import Stage
from ..signals import S, SpeakerInfo

logger = logging.getLogger(__name__)


class AsrStage(Stage):
    subscribes = (VoiceStopped,)

    async def handle(self, event: Event) -> None:
        assert isinstance(event, VoiceStopped)
        turn = self.rt.session.current_turn
        if turn is None or turn.aborted:
            return

        pending_text = self.rt.pending_text
        self.rt.pending_text = None
        frames = self.rt.audio_buffer
        self.rt.audio_buffer = []

        if pending_text is not None:
            text: str = pending_text
        else:
            voiceprint = self.rt.adapters.voiceprint
            if voiceprint is not None and frames:
                text_result, speaker = await asyncio.gather(
                    self.rt.adapters.asr.transcribe(frames, turn.meta),
                    voiceprint.identify(frames),
                    return_exceptions=True,
                )
                if isinstance(speaker, BaseException):
                    logger.warning("声纹识别失败: %s", speaker)
                elif isinstance(speaker, SpeakerInfo):
                    turn.meta.set(S.speaker, speaker)
                    await self.rt.emit(SpeakerIdentified(speaker=speaker))
                if isinstance(text_result, BaseException):
                    logger.error("ASR 识别失败: %s", text_result)
                    text = ""
                else:
                    text = text_result
            else:
                text = await self.rt.adapters.asr.transcribe(frames, turn.meta)

        if turn.aborted:  # 识别期间被并发打断（run() 的 abort 旁路）
            return
        if not text.strip():
            self.rt.state_machine.cancel_turn()
            return

        turn.user_text = text
        await self.rt.emit(AsrFinalized(text=text))

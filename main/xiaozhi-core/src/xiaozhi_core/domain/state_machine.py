"""显式对话状态机（架构文档 2.4）。

::

    IDLE        --ListenStart/VoiceStarted-->   LISTENING
    LISTENING   --VoiceStopped/ListenStop-->    RECOGNIZING   (begin_turn)
    RECOGNIZING --AsrFinalized-->               THINKING      (emit TurnStarted)
    THINKING    --首句 TTS-->                    SPEAKING      (emit TtsStarted)
    SPEAKING    --TtsStopped-->                 IDLE          (emit TurnCompleted)
    ANY         --AbortRequested-->             IDLE          (emit TurnAborted)

``turn_id`` 由状态机在进入 RECOGNIZING 时生成（``SessionContext.begin_turn``），
作为陈旧数据过滤的唯一依据。非法转移宽容处理（记录日志后忽略），与现状的
容错行为一致。
"""

from __future__ import annotations

import logging
from enum import Enum

from .context import SessionContext, TurnContext
from .event_bus import EventBus
from .events import TtsStarted, TurnAborted, TurnCompleted, TurnStarted

logger = logging.getLogger(__name__)


class DialogueState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    RECOGNIZING = "recognizing"
    THINKING = "thinking"
    SPEAKING = "speaking"


class DialogueStateMachine:
    def __init__(self, bus: EventBus, session: SessionContext) -> None:
        self._bus = bus
        self._session = session
        self.state = DialogueState.IDLE

    async def on_voice_started(self) -> None:
        if self.state in (DialogueState.IDLE, DialogueState.LISTENING):
            self.state = DialogueState.LISTENING

    async def on_voice_stopped(self) -> TurnContext | None:
        if self.state not in (DialogueState.IDLE, DialogueState.LISTENING):
            logger.debug("忽略 voice_stopped：当前状态 %s", self.state)
            return None
        self.state = DialogueState.RECOGNIZING
        return self._session.begin_turn()

    async def on_asr_finalized(self) -> None:
        if self.state is not DialogueState.RECOGNIZING:
            logger.debug("忽略 asr_finalized：当前状态 %s", self.state)
            return
        self.state = DialogueState.THINKING
        turn = self._session.current_turn
        await self._bus.publish(
            TurnStarted(session_id=self._session.session_id, turn_id=turn.turn_id if turn else None)
        )

    async def on_speaking(self) -> None:
        if self.state is not DialogueState.THINKING:
            return
        self.state = DialogueState.SPEAKING
        turn = self._session.current_turn
        await self._bus.publish(
            TtsStarted(session_id=self._session.session_id, turn_id=turn.turn_id if turn else None)
        )

    async def on_finished(self) -> None:
        turn = self._session.current_turn
        if turn is None:
            return
        self.state = DialogueState.IDLE
        await self._bus.publish(
            TurnCompleted(
                session_id=self._session.session_id,
                turn_id=turn.turn_id,
                user_text=turn.user_text,
                assistant_text=turn.assistant_text,
            )
        )
        self._session.end_turn()

    async def abort(self) -> None:
        turn = self._session.current_turn
        self.state = DialogueState.IDLE
        if turn is not None:
            turn.aborted = True
        # 无活跃轮次也发 TurnAborted：设备侧需要 tts:stop 收束播放（与现状一致）
        await self._bus.publish(
            TurnAborted(
                session_id=self._session.session_id,
                turn_id=turn.turn_id if turn else None,
            )
        )
        self._session.end_turn()

    def cancel_turn(self) -> None:
        """静默取消（如 ASR 结果为空）：回 IDLE，不发事件。"""
        self.state = DialogueState.IDLE
        self._session.end_turn()

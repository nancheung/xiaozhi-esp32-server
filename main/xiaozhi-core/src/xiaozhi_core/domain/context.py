"""会话 / 轮次上下文（架构文档 2.4）。

- ``SessionContext``：一条连接的生命周期。持有对话历史、会话级黑板、当前轮次。
- ``TurnContext``：一次「用户说话 -> 应答」。持有轮次黑板（元数据流转于此，
  绝不压平进文本）与 abort 标志。``turn_id`` 是陈旧数据过滤的唯一依据。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .dialogue import Dialogue
from .signals import MetadataBag


@dataclass(slots=True)
class TurnContext:
    turn_id: str
    user_text: str = ""
    assistant_text: str = ""
    aborted: bool = False
    meta: MetadataBag = field(default_factory=MetadataBag)


@dataclass(slots=True)
class SessionContext:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dialogue: Dialogue = field(default_factory=Dialogue)
    meta: MetadataBag = field(default_factory=MetadataBag)
    current_turn: TurnContext | None = None
    close_after_turn: bool = False

    def begin_turn(self) -> TurnContext:
        self.current_turn = TurnContext(turn_id=uuid.uuid4().hex)
        return self.current_turn

    def end_turn(self) -> None:
        self.current_turn = None

    def is_current(self, turn_id: str | None) -> bool:
        return (
            turn_id is not None
            and self.current_turn is not None
            and self.current_turn.turn_id == turn_id
        )

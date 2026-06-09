"""事件总线：publish / subscribe，多订阅者，按订阅顺序顺序分发。

- 支持按事件基类订阅（订阅 ``Event`` 即可观测全部事件——LoggingHook 的用法）。
- 同一事件的处理顺序 = 订阅顺序；handler 内 ``publish`` 嵌套事件时为深度优先，
  保证因果链路（VoiceStopped -> AsrFinalized -> ...）确定性可测。
- handler 异常被记录而不向上抛，单个订阅者故障不阻断链路。
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from .events import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe[E: Event](
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """订阅事件类型（含其子类）。返回取消订阅函数。"""
        self._subscribers[event_type].append(handler)

        def unsubscribe() -> None:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

        return unsubscribe

    async def publish(self, event: Event) -> None:
        for cls in type(event).__mro__:
            for handler in tuple(self._subscribers.get(cls, ())):  # type: ignore[arg-type]
                try:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception(
                        "事件处理失败: event=%s handler=%s",
                        type(event).__name__,
                        getattr(handler, "__qualname__", handler),
                    )
            if cls is Event:
                break

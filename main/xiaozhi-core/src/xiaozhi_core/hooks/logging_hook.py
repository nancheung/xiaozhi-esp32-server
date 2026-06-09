"""日志 hook：订阅事件基类即可观测全链路（统一观测点）。"""

from __future__ import annotations

import logging

from ..domain.event_bus import EventBus
from ..domain.events import AudioFrameReceived, Event, TtsAudioChunkReady

logger = logging.getLogger("xiaozhi_core.events")

_NOISY = (AudioFrameReceived, TtsAudioChunkReady)


def logging_hook(bus: EventBus) -> None:
    def on_event(event: Event) -> None:
        if isinstance(event, _NOISY):
            return
        logger.debug("[%s] %s", type(event).__name__, event.model_dump(exclude={"ts"}))

    bus.subscribe(Event, on_event)

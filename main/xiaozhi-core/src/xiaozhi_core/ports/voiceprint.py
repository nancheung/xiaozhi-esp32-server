"""声纹端口：元数据 enrichment 的具体实例（架构文档 7.4）。

在 AsrStage 内与 ASR 并行执行，结果写 ``TurnContext.meta[S.speaker]``，
由 PromptComposer 消费——与情绪/语速共用同一套机制。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..domain.capabilities import SignalAware
from ..domain.signals import S, Signal, SpeakerInfo


class VoiceprintPort(SignalAware, ABC):
    def provides(self) -> frozenset[Signal[Any]]:
        return frozenset({S.speaker})

    @abstractmethod
    async def identify(self, frames: list[bytes]) -> SpeakerInfo | None: ...

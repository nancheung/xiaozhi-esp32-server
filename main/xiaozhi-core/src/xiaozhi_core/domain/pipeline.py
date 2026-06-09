"""可插拔编排（架构文档 2.5）。

``Stage`` 声明订阅哪些事件、产出哪些事件、依赖哪个端口；``Pipeline`` 把
stage 接到会话的事件总线上。接入方可增删改 stage（纯文本聊天去掉
Vad/Asr/AudioOutput；在 Llm 前插敏感词过滤 stage 等）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar

from .events import Event

if TYPE_CHECKING:
    from ..runtime.server import SessionRuntime


class Stage(ABC):
    subscribes: ClassVar[tuple[type[Event], ...]] = ()

    def __init__(self) -> None:
        self.runtime: SessionRuntime | None = None

    def bind(self, runtime: SessionRuntime) -> None:
        self.runtime = runtime
        self.on_bind()

    def on_bind(self) -> None:  # noqa: B027 —— 可选初始化钩子
        """绑定运行时后的初始化钩子。"""

    @abstractmethod
    async def handle(self, event: Event) -> None: ...

    # -- 常用快捷访问 ---------------------------------------------------
    @property
    def rt(self) -> SessionRuntime:
        assert self.runtime is not None, "Stage 未绑定运行时"
        return self.runtime

    def is_stale(self, event: Event) -> bool:
        """陈旧轮次过滤：事件的 turn_id 不是当前轮次即丢弃。"""
        return event.turn_id is not None and not self.rt.session.is_current(event.turn_id)


class Pipeline:
    def __init__(self, stages: Sequence[Stage]) -> None:
        self.stages = list(stages)

    @classmethod
    def default(cls) -> Pipeline:
        from .stages import (
            AsrStage,
            AudioOutputStage,
            IntentStage,
            LlmStage,
            TtsStage,
            VadStage,
        )

        # 注意顺序即同一事件上的分发顺序：AudioOutputStage 须先于 Intent/Llm 观测
        # AsrFinalized，保证 stt / tts:start 在嵌套的 LLM->TTS 级联之前下发设备。
        return cls(
            [VadStage(), AsrStage(), AudioOutputStage(), IntentStage(), LlmStage(), TtsStage()]
        )

    def attach(self, runtime: SessionRuntime) -> None:
        for stage in self.stages:
            stage.bind(runtime)
            for event_type in stage.subscribes:
                runtime.bus.subscribe(event_type, stage.handle)

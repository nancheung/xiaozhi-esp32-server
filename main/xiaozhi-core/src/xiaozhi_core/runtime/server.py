"""运行时装配（架构文档 2.5 / 三）。

``SessionRuntime`` 是一条会话的装配结果：事件总线 + 上下文 + 状态机 +
能力协商 + pipeline。状态机的转移订阅先于 pipeline 挂载，保证同一事件上
「状态转移 -> stage 业务」的确定性顺序（如 VoiceStopped 先 begin_turn，
AsrStage 再消费）。

接入方三步启动::

    server = XiaozhiServer(adapters=AdapterSet(...), composer=PromptComposer("人设"))
    runtime = server.create_session()
    await runtime.run()          # 或逐事件 await runtime.emit(...)
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from ..domain.capabilities import (
    DirectiveProvider,
    NegotiationResult,
    SignalAware,
    SpeakTagDirective,
    negotiate,
)
from ..domain.context import SessionContext
from ..domain.event_bus import EventBus
from ..domain.events import (
    AbortRequested,
    AsrFinalized,
    Event,
    SessionEnded,
    SessionStarted,
    TtsStopped,
    VoiceStarted,
    VoiceStopped,
)
from ..domain.pipeline import Pipeline
from ..domain.services.audio_rate_controller import AudioRateController
from ..domain.services.prompt_composer import PromptComposer
from ..domain.state_machine import DialogueStateMachine
from ..ports.asr import AsrPort
from ..ports.intent import IntentPort
from ..ports.llm import LlmPort
from ..ports.memory import MemoryPort
from ..ports.report import ReportPort
from ..ports.tools import ToolPort
from ..ports.transport import TransportPort
from ..ports.tts import TtsPort
from ..ports.vad import VadPort
from ..ports.vision import VisionPort
from ..ports.voiceprint import VoiceprintPort

Hook = Callable[[EventBus], None]


@dataclass(slots=True)
class AdapterSet:
    """一条会话的端口实现集合。最小可运行 = vad + asr + llm + tts。"""

    vad: VadPort
    asr: AsrPort
    llm: LlmPort
    tts: TtsPort
    transport: TransportPort | None = None
    intent: IntentPort | None = None
    memory: MemoryPort | None = None
    tools: ToolPort | None = None
    voiceprint: VoiceprintPort | None = None
    vision: VisionPort | None = None
    report: ReportPort | None = None


class SessionRuntime:
    def __init__(
        self,
        adapters: AdapterSet,
        composer: PromptComposer,
        pipeline: Pipeline | None = None,
        derivers: Sequence[DirectiveProvider] | None = None,
        hooks: Sequence[Hook] = (),
        rate_controller: AudioRateController | None = None,
    ) -> None:
        self.adapters = adapters
        self.composer = composer
        self.bus = EventBus()
        self.session = SessionContext()
        self.state_machine = DialogueStateMachine(self.bus, self.session)
        self.rate_controller = rate_controller

        # 跨 stage 的轮次暂存（VadStage 产、AsrStage 消）
        self.audio_buffer: list[bytes] = []
        self.pending_text: str | None = None

        self.negotiation = self._negotiate(derivers)

        # 前置转移：同事件上先于 stage 执行（VoiceStopped 先 begin_turn，AsrStage 再消费）
        self.bus.subscribe(VoiceStarted, lambda _: self.state_machine.on_voice_started())
        self.bus.subscribe(VoiceStopped, lambda _: self.state_machine.on_voice_stopped())
        self.bus.subscribe(AsrFinalized, lambda _: self.state_machine.on_asr_finalized())
        self.bus.subscribe(AbortRequested, lambda _: self.state_machine.abort())

        (pipeline or Pipeline.default()).attach(self)

        # 后置转移：TtsStopped 须等 AudioOutputStage 下发 tts:stop 后再收束本轮，
        # 否则轮次提前结束会让出站消息被陈旧过滤。
        self.bus.subscribe(TtsStopped, lambda _: self.state_machine.on_finished())
        for hook in hooks:
            hook(self.bus)

    def _negotiate(self, derivers: Sequence[DirectiveProvider] | None) -> NegotiationResult:
        adapters = self.adapters
        producers: list[SignalAware] = [
            p
            for p in (adapters.asr, adapters.llm, adapters.tts, adapters.voiceprint)
            if isinstance(p, SignalAware)
        ]
        consumers: list[SignalAware] = [self.composer, adapters.tts]
        if derivers is None:
            derivers = [SpeakTagDirective(adapters.tts.supported_render_emotions())]
        return negotiate(producers, consumers, derivers)

    async def emit(self, event: Event) -> None:
        """发布事件；自动补齐 session_id 与当前 turn_id。"""
        if not event.session_id:
            event.session_id = self.session.session_id
        if event.turn_id is None and self.session.current_turn is not None:
            event.turn_id = self.session.current_turn.turn_id
        await self.bus.publish(event)

    async def start(self) -> None:
        await self.emit(SessionStarted())

    async def stop(self) -> None:
        if self.adapters.memory is not None:
            await self.adapters.memory.save(
                self.session.dialogue.history_messages(), self.session.session_id
            )
        await self.emit(SessionEnded())
        if self.adapters.transport is not None:
            await self.adapters.transport.close()

    async def run(self) -> None:
        """消费 Transport 入站事件直到连接结束。

        打断旁路：读流任务持续消费入站，``AbortRequested`` 不排队、立即处理
        （置 aborted 标志 + 下发 tts:stop），进行中的轮次在最近的检查点
        （LLM delta / TTS chunk / 出帧间隙）自行退出；其余事件经队列按序
        处理，保持 VAD 帧时序等顺序语义。
        """
        transport = self.adapters.transport
        if transport is None:
            raise RuntimeError("AdapterSet.transport 未配置，无法 run()；可改用 emit() 注入事件")
        await self.start()
        queue: asyncio.Queue[Event | None] = asyncio.Queue()

        async def read_inbound() -> None:
            try:
                async for event in transport.events():
                    if isinstance(event, AbortRequested):
                        await self.emit(event)  # 旁路：立即打断，不排在轮次后面
                    else:
                        queue.put_nowait(event)
            finally:
                queue.put_nowait(None)  # 连接结束哨兵

        reader = asyncio.create_task(read_inbound())
        try:
            while (event := await queue.get()) is not None:
                await self.emit(event)
            await reader  # 正常结束：让读流任务的异常（如传输层错误）显式上抛
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            await self.stop()


@dataclass(slots=True)
class XiaozhiServer:
    """会话工厂：持有装配模板，按连接创建 SessionRuntime。

    有状态 adapter（VAD 窗口、Transport 连接）是会话级实例：静态 ``adapters``
    只能开一个会话；多连接场景必须用 ``adapters_factory`` 按会话新建。
    """

    adapters_factory: Callable[[], AdapterSet] | None = None
    adapters: AdapterSet | None = None
    composer: PromptComposer = field(default_factory=lambda: PromptComposer("你是小智。"))
    pipeline_factory: Callable[[], Pipeline] = Pipeline.default
    hooks: Sequence[Hook] = ()
    rate_controller_factory: Callable[[], AudioRateController] | None = None
    _static_adapters_used: bool = field(default=False, init=False)

    def create_session(self, transport: TransportPort | None = None) -> SessionRuntime:
        if self.adapters_factory is not None:
            adapters = self.adapters_factory()
        elif self.adapters is not None:
            if self._static_adapters_used:
                raise RuntimeError(
                    "静态 adapters 已被会话占用：有状态 adapter（VAD/Transport）不可跨会话"
                    "共享，多会话场景请改用 adapters_factory 按会话新建"
                )
            self._static_adapters_used = True
            adapters = self.adapters
        else:
            raise ValueError("需提供 adapters 或 adapters_factory")
        if transport is not None:
            adapters = replace(adapters, transport=transport)  # 不改写装配模板本体
        rate_controller = (
            self.rate_controller_factory() if self.rate_controller_factory is not None else None
        )
        return SessionRuntime(
            adapters=adapters,
            composer=self.composer,
            pipeline=self.pipeline_factory(),
            hooks=self.hooks,
            rate_controller=rate_controller,
        )

"""DoubaoRealtimeStage：豆包端到端模型 <-> core 事件总线的融合 Stage。

替代默认管道里的 Vad/Asr/Llm/Tts 四个 stage（豆包云端已融合这四步），
只保留 AudioOutputStage 复用出站协议与陈旧轮次过滤::

    Pipeline([DoubaoRealtimeStage(client), AudioOutputStage()])

事件映射（豆包 -> core）：

    450 ASRInfo      -> VoiceStarted（SPEAKING/THINKING 中收到 = 用户打断，先 AbortRequested）
    451 ASRResponse  -> 暂存识别文本
    459 ASREnded     -> VoiceStopped（begin_turn）+ AsrFinalized；空文本静默取消
    SERVER_ACK 音频   -> TtsAudioChunkReady（首帧前补 on_speaking 转移，替代 TtsStage 职责）
    359 TTSEnded     -> TtsSentenceSegmented(LAST) + TtsStopped（收束本轮）
    550 ChatResponse -> 累积 turn.assistant_text（云端 LLM 模式）

入站方向：AudioFrameReceived 直通 ``client.send_audio()``（无本地 VAD/缓冲）。

回复路径按 **装配期协商** 自动选择（对齐 core 理念：给了什么 adapter 就激活什么链路）：

- ``use_local_llm=True``（照念分支，ChatTTSText 500）：本地 LLM 生成回复，豆包绕过云端
  LLM 仅做 TTS 照念。prompt 经 ``PromptComposer`` 拼装（与 LlmStage 同构），装配了
  ``MemoryPort`` 时记忆走 ``{memory}`` 占位符进本地 prompt。
- ``use_local_llm=False`` 且装配了 ``MemoryPort``（知识注入分支，ChatRAGText 502）：
  把 ``memory.query()`` 结果注入豆包，云端 LLM 据此**重新生成并润色**回答；可选先发
  ``comfort_text`` 安抚话术掩盖检索耗时。memory 未装配或查询为空 -> 自动降级纯端到端。

两条注入路径期间丢弃豆包注入前的自答音频，直到 350 携带
``tts_type in {"chat_tts_text", "external_rag"}``（与官方 demo 的丢弃逻辑一致）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Protocol

from xiaozhi_core.domain.dialogue import Message
from xiaozhi_core.domain.events import (
    AbortRequested,
    AsrFinalized,
    AudioFrameReceived,
    Event,
    SentencePosition,
    SessionEnded,
    SessionStarted,
    TtsAudioChunkReady,
    TtsSentenceSegmented,
    TtsStopped,
    VoiceStarted,
    VoiceStopped,
)
from xiaozhi_core.domain.pipeline import Stage
from xiaozhi_core.domain.services.sentence_segmenter import SentenceSegmenter
from xiaozhi_core.domain.state_machine import DialogueState

from . import protocol
from .protocol import ServerMessage

logger = logging.getLogger(__name__)

_RESUME_TTS_TYPES = {"chat_tts_text", "external_rag"}


class RealtimeClient(Protocol):
    """stage 依赖的客户端能力（测试注入 Fake 实现即可）。"""

    async def connect(self) -> None: ...
    async def say_hello(self, content: str) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def send_chat_tts_text(self, *, start: bool, end: bool, content: str) -> None: ...
    async def send_chat_rag_text(self, *, external_rag: str) -> None: ...
    def messages(self) -> Any: ...  # AsyncIterator[ServerMessage]
    async def close(self) -> None: ...


class DoubaoRealtimeStage(Stage):
    subscribes = (SessionStarted, AudioFrameReceived, SessionEnded)

    def __init__(
        self,
        client: RealtimeClient,
        *,
        use_local_llm: bool = False,
        comfort_text: str | None = None,
        say_hello: str | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._use_local_llm = use_local_llm
        self._comfort_text = comfort_text
        self._say_hello = say_hello
        self._receive_task: asyncio.Task[None] | None = None
        self._connected = False
        self._asr_text = ""
        # 当前应答归属的轮次：打断后过滤豆包仍在下发的旧轮音频；None = 无轮次
        # 语境（如开场白），音频直接放行。
        self._reply_turn_id: str | None = None
        # 注入（500/502）期间丢弃云端自答音频，直到 350(tts_type=chat_tts_text/external_rag)
        self._dropping_cloud_audio = False
        # 注入期间丢弃云端原始 LLM 550 文本；350(external_rag) 到来时清零
        # （350(external_rag) 晚于所有原始 LLM 550、早于所有 RAG LLM 550，是天然分隔点）
        self._dropping_cloud_text = False
        # 回复文本切句下发（AudioOutputStage 据此发 tts/sentence_start，与 LlmStage 同构）
        self._segmenter = SentenceSegmenter()
        self._sentence_emitted = False

    async def handle(self, event: Event) -> None:
        if isinstance(event, SessionStarted):
            await self._client.connect()
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            if self._say_hello:
                await self._client.say_hello(self._say_hello)
        elif isinstance(event, AudioFrameReceived):
            if self._connected:
                await self._client.send_audio(event.frame)
        elif isinstance(event, SessionEnded):
            self._connected = False
            if self._receive_task is not None:
                self._receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._receive_task
                self._receive_task = None
            await self._client.close()

    # -- 豆包 -> core ----------------------------------------------------
    async def _receive_loop(self) -> None:
        try:
            async for message in self._client.messages():
                await self._on_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("豆包接收循环异常退出，会话不再产出应答")

    async def _on_message(self, message: ServerMessage) -> None:
        logger.debug("收到豆包消息：%s", message.to_dict())
        if message.kind == "error":
            raise RuntimeError(f"豆包服务端错误 code={message.code}: {message.payload}")
        if message.kind == "ack":
            await self._on_audio(message.audio or b"")
            return
        if message.kind != "full_response":
            return

        event = message.event
        payload = message.payload or {}
        if event == protocol.EVENT_ASR_INFO:  # 450 用户开始说话
            if self.rt.state_machine.state in (DialogueState.SPEAKING, DialogueState.THINKING):
                await self.rt.emit(AbortRequested())  # 用户打断：立即收束当前应答
            self._asr_text = ""
            await self.rt.emit(VoiceStarted())
        elif event == protocol.EVENT_ASR_RESPONSE:  # 451 识别文本（增量覆盖）
            text = protocol.extract_asr_text(payload)
            if text:
                self._asr_text = text
        elif event == protocol.EVENT_ASR_ENDED:  # 459 用户说完
            await self._on_user_finished()
        elif event == protocol.EVENT_CHAT_RESPONSE:  # 550 云端 LLM 文本增量
            turn = self.rt.session.current_turn
            if turn is not None and not self._use_local_llm and not self._dropping_cloud_text:
                content = str(payload.get("content", ""))
                turn.assistant_text += content
                for segment in self._segmenter.feed(content):
                    await self._emit_sentence(segment)
        elif event == protocol.EVENT_TTS_SENTENCE_START:  # 350
            tts_type = payload.get("tts_type")
            if self._dropping_cloud_audio and tts_type in _RESUME_TTS_TYPES:
                self._dropping_cloud_audio = False  # 注入内容的音频开始，恢复下发
            if self._dropping_cloud_text and tts_type == "external_rag":
                self._dropping_cloud_text = False  # 原始 LLM 已结束，RAG 550 即将开始
        elif event == protocol.EVENT_TTS_ENDED:  # 359 本轮音频播完
            self._reply_turn_id = None
            remainder = self._segmenter.flush()
            if remainder:
                await self._emit_sentence(remainder)
            turn = self.rt.session.current_turn
            if turn is not None and not self._use_local_llm and turn.assistant_text:
                # 云端回复落账历史（本地接管路径在 takeover 内落账）
                self.rt.session.dialogue.put(Message(role="assistant", content=turn.assistant_text))
            await self.rt.emit(TtsSentenceSegmented(position=SentencePosition.LAST))
            await self.rt.emit(TtsStopped())
        elif event in (protocol.EVENT_SESSION_FINISHED, protocol.EVENT_SESSION_FAILED):
            logger.info("豆包会话结束 event=%s payload=%s", event, payload)

    async def _on_user_finished(self) -> None:
        await self.rt.emit(VoiceStopped())  # 状态机在此 begin_turn
        self._segmenter.reset()
        self._sentence_emitted = False
        self._dropping_cloud_audio = False  # 每轮开始时重置：旧轮注入状态不污染新轮
        self._dropping_cloud_text = False
        text = self._asr_text.strip()
        if not text:
            self.rt.state_machine.cancel_turn()
            return
        turn = self.rt.session.current_turn
        if turn is not None:
            turn.user_text = text
            self._reply_turn_id = turn.turn_id
        self.rt.session.dialogue.put(Message(role="user", content=text))
        await self.rt.emit(AsrFinalized(text=text))
        if self._use_local_llm:
            await self._local_llm_takeover(text)
        elif self.rt.adapters.memory is not None:
            await self._memory_rag_inject(text)

    async def _emit_sentence(self, text: str) -> None:
        """下发一段回复文本（AudioOutputStage 转为 tts/sentence_start 协议消息）。"""
        position = SentencePosition.MIDDLE if self._sentence_emitted else SentencePosition.FIRST
        self._sentence_emitted = True
        await self.rt.emit(TtsSentenceSegmented(position=position, text=text))

    async def _query_memory(self, user_text: str) -> str | None:
        memory = self.rt.adapters.memory
        return await memory.query(user_text) if memory is not None else None

    async def _local_llm_takeover(self, user_text: str) -> None:
        """照念分支（ChatTTSText 500）：本地 LLM 生成回复，豆包仅 TTS 照念。

        prompt 经 PromptComposer 拼装（与 LlmStage._respond 同构）：装配了
        MemoryPort 时记忆走 ``{memory}`` 占位符进本地 prompt。
        """
        self._dropping_cloud_audio = True
        session = self.rt.session
        turn = session.current_turn
        assert turn is not None, "459 后必有当前轮次"
        messages = self.rt.composer.compose(
            session, turn, memory=await self._query_memory(user_text)
        )
        parts: list[str] = []
        async for delta in self.rt.adapters.llm.stream(messages):
            if delta.text:
                parts.append(delta.text)
        reply = "".join(parts)
        turn.assistant_text = reply
        session.dialogue.put(Message(role="assistant", content=reply))
        await self._emit_sentence(reply)  # 照念文本即完整回复，整段下发
        await self._client.send_chat_tts_text(start=True, end=False, content=reply)
        await self._client.send_chat_tts_text(start=False, end=True, content="")

    async def _memory_rag_inject(self, user_text: str) -> None:
        """知识注入分支（ChatRAGText 502）：记忆注入豆包，云端 LLM 重新生成润色。"""
        self._dropping_cloud_audio = True  # 立即丢弃云端原始音频（等 350 事件恢复）
        self._dropping_cloud_text = True   # 立即丢弃云端原始 LLM 文本（502 发出后恢复）
        memory_text = await self._query_memory(user_text)
        if not memory_text:
            self._dropping_cloud_audio = False  # 无记忆：降级纯端到端，恢复放行
            self._dropping_cloud_text = False
            return
        if self._comfort_text:  # 安抚话术掩盖检索/重生成耗时（demo 同款两连发）
            await self._emit_sentence(self._comfort_text)
            await self._client.send_chat_tts_text(start=True, end=False, content=self._comfort_text)
            await self._client.send_chat_tts_text(start=False, end=True, content="")
        await self._client.send_chat_rag_text(
            external_rag=json.dumps(
                [{"title": "用户记忆", "content": memory_text}], ensure_ascii=False
            )
        )

    async def _on_audio(self, chunk: bytes) -> None:
        if not chunk or self._dropping_cloud_audio:
            return
        if self._reply_turn_id is not None and not self.rt.session.is_current(self._reply_turn_id):
            return  # 被打断的旧轮残留音频
        if self.rt.state_machine.state is DialogueState.THINKING:
            await self.rt.state_machine.on_speaking()  # 首帧音频 = 进入 SPEAKING
        await self.rt.emit(TtsAudioChunkReady(chunk=chunk))

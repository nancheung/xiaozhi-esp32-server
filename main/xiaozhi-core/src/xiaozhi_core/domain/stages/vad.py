"""VadStage：入站音频帧 -> 语音段边界。

订阅 ``AudioFrameReceived`` / ``ListenStateChanged``，缓冲语音帧，
经 VadPort 判停后发布 ``VoiceStarted`` / ``VoiceStopped``。
``listen.detect``（设备侧已出文本）直接走文本通道，跳过 ASR。
"""

from __future__ import annotations

from ..events import (
    AudioFrameReceived,
    Event,
    ListenStateChanged,
    VoiceStarted,
    VoiceStopped,
)
from ..pipeline import Stage

_PRE_ROLL_FRAMES = 10  # 静音期保留的前导帧数（与现状一致）


class VadStage(Stage):
    subscribes = (AudioFrameReceived, ListenStateChanged)

    def on_bind(self) -> None:
        self._frames: list[bytes] = []
        self._in_voice = False

    async def handle(self, event: Event) -> None:
        if isinstance(event, ListenStateChanged):
            await self._handle_listen(event)
            return
        assert isinstance(event, AudioFrameReceived)
        result = self.rt.adapters.vad.detect(event.frame)

        self._frames.append(event.frame)
        if not self._in_voice and not result.is_voice:
            self._frames = self._frames[-_PRE_ROLL_FRAMES:]

        if result.is_voice and not self._in_voice:
            self._in_voice = True
            await self.rt.emit(VoiceStarted())
        if result.voice_stopped and self._in_voice:
            await self._finish_segment()

    async def _handle_listen(self, event: ListenStateChanged) -> None:
        if event.state == "start":
            self._reset()
            self.rt.adapters.vad.reset()
        elif event.state == "stop":
            if self._frames:
                await self._finish_segment()
        elif event.state == "detect" and event.text:
            # 设备侧已识别出文本：直通文本通道，AsrStage 优先取 pending_text
            self._reset()
            self.rt.pending_text = event.text
            await self.rt.emit(VoiceStopped())

    async def _finish_segment(self) -> None:
        self.rt.audio_buffer = self._frames
        self._reset()
        await self.rt.emit(VoiceStopped())

    def _reset(self) -> None:
        self._frames = []
        self._in_voice = False

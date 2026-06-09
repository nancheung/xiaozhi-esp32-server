"""AudioOutputStage：领域事件 -> 设备出站协议。

唯一与设备协议打交道的 stage，经 TransportPort 下发。时序与现状协议一致::

    hello -> stt -> tts:start -> [tts:sentence_start -> opus×N]... -> tts:stop

音频帧经 ``AudioRateController`` 节流（60ms 帧时序 + 预缓冲直发）。
打断（TurnAborted）立即下发 tts:stop；陈旧轮次的音频被 turn_id 过滤。
"""

from __future__ import annotations

from ..events import (
    AsrFinalized,
    AudioChunkSent,
    Event,
    HelloReceived,
    SentencePosition,
    TtsAudioChunkReady,
    TtsSentenceSegmented,
    TtsStopped,
    TurnAborted,
)
from ..pipeline import Stage


class AudioOutputStage(Stage):
    subscribes = (
        HelloReceived,
        AsrFinalized,
        TtsSentenceSegmented,
        TtsAudioChunkReady,
        TtsStopped,
        TurnAborted,
    )

    async def handle(self, event: Event) -> None:
        transport = self.rt.adapters.transport
        if transport is None:
            return
        session_id = self.rt.session.session_id

        if isinstance(event, HelloReceived):
            await transport.send_event({"type": "hello", "session_id": session_id})
            return
        if isinstance(event, TurnAborted):
            self._reset_rate_controller()
            await transport.send_event({"type": "tts", "state": "stop", "session_id": session_id})
            return
        if self.is_stale(event):
            return

        if isinstance(event, AsrFinalized):
            await transport.send_event(
                {"type": "stt", "text": event.text, "session_id": session_id}
            )
            await transport.send_event({"type": "tts", "state": "start", "session_id": session_id})
        elif isinstance(event, TtsSentenceSegmented):
            if event.position is not SentencePosition.LAST and event.text:
                await transport.send_event(
                    {
                        "type": "tts",
                        "state": "sentence_start",
                        "text": event.text,
                        "session_id": session_id,
                    }
                )
        elif isinstance(event, TtsAudioChunkReady):
            controller = self.rt.rate_controller
            if controller is not None:
                await controller.pace()
            await transport.send_audio(event.chunk)
            await self.rt.emit(AudioChunkSent(size=len(event.chunk)))
        elif isinstance(event, TtsStopped):
            self._reset_rate_controller()
            await transport.send_event({"type": "tts", "state": "stop", "session_id": session_id})

    def _reset_rate_controller(self) -> None:
        if self.rt.rate_controller is not None:
            self.rt.rate_controller.reset()

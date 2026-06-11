"""本机音频传输：麦克风采集为入站事件、扬声器播放出站音频（依赖 pyaudio）。

实现 ``TransportPort``：core 把它当成「设备」——``events()`` 产出
``AudioFrameReceived``，``send_audio()`` 播放豆包返回的 24k PCM，
``send_event()`` 把协议消息打印到控制台（观察 stt / tts 时序）。
新一轮 ``tts:start`` 时清空播放队列里上一轮的残留（打断体验）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import AsyncIterator
from typing import Any

from xiaozhi_core.domain.events import AudioFrameReceived, Event
from xiaozhi_core.ports.transport import TransportPort

from . import config

logger = logging.getLogger(__name__)


class MicTransport(TransportPort):
    def __init__(self) -> None:
        try:
            import pyaudio
        except ImportError as exc:  # 快速失败并给出可操作的指引
            raise RuntimeError("MicTransport 需要 pyaudio：uv add pyaudio --group dev") from exc

        self._pa = pyaudio.PyAudio()
        in_cfg, out_cfg = config.input_audio_config, config.output_audio_config
        self._in_chunk = in_cfg["chunk"]
        self._input = self._pa.open(
            format=self._pa.get_format_from_width(in_cfg["sample_width"]),
            channels=in_cfg["channels"],
            rate=in_cfg["sample_rate"],
            input=True,
            frames_per_buffer=in_cfg["chunk"],
        )
        self._output = self._pa.open(
            format=self._pa.get_format_from_width(out_cfg["sample_width"]),
            channels=out_cfg["channels"],
            rate=out_cfg["sample_rate"],
            output=True,
            frames_per_buffer=out_cfg["chunk"],
        )
        self._closed = False
        self._playback: queue.Queue[bytes] = queue.Queue()
        self._player = threading.Thread(target=self._player_loop, daemon=True)
        self._player.start()

    def _player_loop(self) -> None:
        while not self._closed:
            try:
                self._output.write(self._playback.get(timeout=0.5))
            except queue.Empty:
                continue
            except Exception:
                logger.exception("音频播放失败")

    async def events(self) -> AsyncIterator[Event]:
        print("已打开麦克风，请讲话（Ctrl+C 退出）...")
        while not self._closed:
            frame = await asyncio.to_thread(
                self._input.read, self._in_chunk, exception_on_overflow=False
            )
            yield AudioFrameReceived(frame=frame)

    async def send_event(self, message: dict[str, Any]) -> None:
        if message.get("type") == "tts" and message.get("state") == "start":
            self._drain_playback()  # 新一轮应答开始，丢掉上一轮残留
        print(f"[协议] {json.dumps(message, ensure_ascii=False)}")

    async def send_audio(self, frame: bytes) -> None:
        self._playback.put(frame)

    def _drain_playback(self) -> None:
        while True:
            try:
                self._playback.get_nowait()
            except queue.Empty:
                return

    async def close(self) -> None:
        self._closed = True
        for stream in (self._input, self._output):
            stream.stop_stream()
            stream.close()
        self._pa.terminate()

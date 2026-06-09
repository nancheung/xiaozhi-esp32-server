"""出站音频限流（源自 xiaozhi-server ``AudioRateController`` + 预缓冲策略）。

按帧时长（默认 60ms）维持虚拟播放位置：前 ``pre_buffer_frames`` 帧直发
压低首响，之后每帧 sleep 到其应播时刻再放行，防止设备端缓冲溢出。
纯 asyncio 实现，由 ``AudioOutputStage`` 在发送前调用 ``pace()``。
"""

from __future__ import annotations

import asyncio
import time


class AudioRateController:
    def __init__(self, frame_duration_ms: int = 60, pre_buffer_frames: int = 5) -> None:
        self.frame_duration_ms = frame_duration_ms
        self.pre_buffer_frames = pre_buffer_frames
        self._sent = 0
        self._start: float | None = None
        self._position_ms = 0.0

    async def pace(self) -> None:
        """在发送一帧前调用：必要时等待到该帧的应播时刻。"""
        if self._sent < self.pre_buffer_frames:
            self._sent += 1
            return
        if self._start is None:
            self._start = time.monotonic()
        elapsed_ms = (time.monotonic() - self._start) * 1000
        if elapsed_ms < self._position_ms:
            await asyncio.sleep((self._position_ms - elapsed_ms) / 1000)
        self._position_ms += self.frame_duration_ms
        self._sent += 1

    def reset(self) -> None:
        self._sent = 0
        self._start = None
        self._position_ms = 0.0

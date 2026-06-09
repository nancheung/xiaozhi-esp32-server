"""VAD 端口：检测语音活动。adapter 为会话级实例，自行管理解码与窗口状态。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..domain.capabilities import SignalAware


class VadResult(BaseModel):
    is_voice: bool = False
    voice_stopped: bool = False


class VadPort(SignalAware, ABC):
    @abstractmethod
    def detect(self, frame: bytes) -> VadResult:
        """检测一帧音频。``voice_stopped=True`` 表示一段语音结束（静音窗满）。"""

    def reset(self) -> None:
        """轮次开始时重置内部状态。"""

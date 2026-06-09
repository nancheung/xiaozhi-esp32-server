"""传输端口（Driving Port）：设备接入。

adapter（WebSocket / MQTT / 测试桩）负责协议细节，把原始输入翻译为入站
``Event`` 投递给核心；核心通过 ``send_event`` / ``send_audio`` 下发。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from ..domain.events import Event


class TransportPort(ABC):
    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        """产出入站事件，连接断开时结束迭代。"""

    @abstractmethod
    async def send_event(self, message: dict[str, Any]) -> None:
        """下发控制消息（stt / tts 状态 / hello ack 等 JSON）。"""

    @abstractmethod
    async def send_audio(self, frame: bytes) -> None:
        """下发一帧音频。"""

    async def close(self) -> None:  # noqa: B027 —— 可选清理钩子
        pass

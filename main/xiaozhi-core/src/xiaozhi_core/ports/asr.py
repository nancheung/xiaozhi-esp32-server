"""ASR 端口：语音转文本。

高级能力（情绪 / 语速 / 语言）不进返回值、不压平进文本——写入轮次黑板
``bag``（``S.asr_emotion`` 等），并通过 ``provides()`` 声明，参与装配期协商。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.capabilities import SignalAware
from ..domain.signals import MetadataBag


class AsrPort(SignalAware, ABC):
    @abstractmethod
    async def transcribe(self, frames: list[bytes], bag: MetadataBag) -> str:
        """整段识别：输入缓冲的音频帧，返回文本；元数据写入 ``bag``。"""

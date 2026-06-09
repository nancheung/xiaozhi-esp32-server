"""TTS 端口：文本转音频流。

高级特性走软需求声明：``wants() -> {S.prosody}`` 表示本 TTS 能消费韵律。
协商器据此反向激活 LLM 的输出契约，并把 ``supported_render_emotions()``
回灌进契约，保证 LLM 只从该 TTS 真能渲染的集合里选。
不支持韵律的实现保持默认声明即可，链路自动降级为纯文本。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..domain.capabilities import SignalAware
from ..domain.signals import Prosody, RenderEmotion


class TtsPort(SignalAware, ABC):
    def supported_render_emotions(self) -> tuple[RenderEmotion, ...]:
        return (RenderEmotion.NEUTRAL,)

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        prosody: Prosody | None = None,
    ) -> AsyncIterator[bytes]:
        """合成一句话，流式产出音频帧（编码格式由 adapter 与设备协商决定）。"""

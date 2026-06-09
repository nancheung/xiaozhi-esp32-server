"""强类型元数据信号。

设计（架构文档 7.3）：
- ``Signal[T]``：命名空间化的强类型字段令牌（``asr.emotion`` / ``prosody`` / ``vendor.feature``）。
- ``MetadataBag``：按 Signal 令牌索引的强类型异构容器（type-indexed map），
  写入时按 Signal 的类型做 Pydantic 运行时校验——扩展字段同样有强约束。
- 核心规范词汇：感知情绪 / 渲染情绪 / 韵律 / 说话人。枚举为开放枚举（含 ``OTHER``），
  厂商原始标签由 adapter 的防腐层（ACL）归一化进来，核心永不见原始格式。

注意：感知情绪 ``PerceivedEmotion``（用户说话时的情绪）与渲染情绪 ``RenderEmotion``
（要求 TTS 表达的情绪底色）是两个独立类型；二者之间的翻译（共情逻辑）由 LLM 完成，
不进类型系统。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


@dataclass(frozen=True, slots=True)
class Signal[T]:
    """命名空间化的强类型字段令牌。身份即 ``key``，可作为黑板与集合的键。"""

    key: str
    value_type: type[T]
    doc: str = ""

    def __repr__(self) -> str:
        return f"<Signal {self.key}>"


class MetadataBag:
    """按 ``Signal`` 令牌索引的强类型异构容器。

    挂在事件上、也是 ``TurnContext`` 黑板。写入时按令牌声明的类型做运行时校验。
    """

    _adapters: ClassVar[dict[Signal[Any], TypeAdapter[Any]]] = {}

    def __init__(self) -> None:
        self._values: dict[Signal[Any], Any] = {}

    def set[T](self, signal: Signal[T], value: T) -> None:
        adapter = self._adapters.get(signal)
        if adapter is None:
            adapter = TypeAdapter(signal.value_type)
            self._adapters[signal] = adapter
        self._values[signal] = adapter.validate_python(value)

    def get[T](self, signal: Signal[T]) -> T | None:
        return self._values.get(signal)

    def has(self, signal: Signal[Any]) -> bool:
        return signal in self._values

    def discard(self, signal: Signal[Any]) -> None:
        self._values.pop(signal, None)

    def keys(self) -> frozenset[Signal[Any]]:
        return frozenset(self._values)

    def snapshot(self) -> dict[str, Any]:
        """供 hook / 日志观测的只读快照（key -> value）。"""
        return {sig.key: value for sig, value in self._values.items()}


# ---------------------------------------------------------------------------
# 核心规范词汇（封闭强类型 + 开放枚举）
# ---------------------------------------------------------------------------


class PerceivedEmotion(StrEnum):
    """ASR / 声学侧感知到的用户情绪。开放枚举：未知标签归 ``OTHER``。"""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    FEARFUL = "fearful"
    DISGUSTED = "disgusted"
    OTHER = "other"


class RenderEmotion(StrEnum):
    """要求 TTS 渲染的情绪底色。开放枚举：未知标签归 ``OTHER``。"""

    NEUTRAL = "neutral"
    GENTLE = "gentle"
    EXCITED = "excited"
    COMFORT = "comfort"
    SERIOUS = "serious"
    OTHER = "other"


class Prosody(BaseModel):
    """TTS 渲染韵律：情绪底色 / 语气 / 语速 / 音高 / 音量（归一化，adapter 各自映射）。"""

    model_config = ConfigDict(frozen=True)

    emotion: RenderEmotion | None = None
    style: str | None = None
    rate: float | None = Field(default=None, ge=-1.0, le=1.0)
    pitch: float | None = Field(default=None, ge=-1.0, le=1.0)
    volume: float | None = Field(default=None, ge=-1.0, le=1.0)


class SpeakerInfo(BaseModel):
    """声纹识别出的说话人。"""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None


class CoreSignals:
    """核心 Signal 注册表。扩展能力请用 ``vendor.feature`` 命名空间另行注册。"""

    asr_emotion = Signal("asr.emotion", PerceivedEmotion, "ASR 感知的用户情绪")
    asr_speech_rate = Signal("asr.speech_rate", float, "用户语速（归一化 -1..1）")
    language = Signal("language", str, "识别出的语言标签")
    speaker = Signal("speaker", SpeakerInfo, "声纹识别出的说话人")
    prosody = Signal("prosody", Prosody, "要求 TTS 渲染的韵律")


S = CoreSignals

SIGNAL_REGISTRY: dict[str, Signal[Any]] = {
    sig.key: sig for sig in vars(CoreSignals).values() if isinstance(sig, Signal)
}


def register_signal(signal: Signal[Any]) -> Signal[Any]:
    """注册扩展 Signal（``vendor.feature``），供模板占位符扫描与观测使用。"""
    existing = SIGNAL_REGISTRY.get(signal.key)
    if existing is not None and existing != signal:
        raise ValueError(f"Signal key 冲突: {signal.key}")
    SIGNAL_REGISTRY[signal.key] = signal
    return signal

"""能力声明与装配期协商（架构文档 7.3）。

两种绑定方向：
- **前向 / 软拉取**：上游碰巧产出的 Signal，下游可选取用（``wants`` / 模板占位符）。
  有就用，没有就降级，消费者常常不是端口本身（如 ``asr.emotion`` 的消费者是
  PromptComposer 的占位符，LLM 端口对情绪无感知）。
- **反向 / 需求激活**：下游能力需要一个本不存在的 Signal（TTS 情绪渲染需要
  ``prosody``），由 ``DirectiveProvider``（提示词契约片段 + 流式输出解析器）
  把 LLM 变成该 Signal 的通用派生生产者。**只有当下游真的需要时才激活契约**，
  否则系统提示保持精简、不浪费 token。

装配期跑一次 ``negotiate``：``produced ∩ wanted`` 软拉取直接可用；
``wanted − produced`` 交给 deriver 激活；输出生效能力矩阵供观测。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .signals import MetadataBag, Prosody, RenderEmotion, S, Signal


class SignalAware:
    """能力声明 mixin：端口/组件覆写以声明自己产出或需要哪些 Signal。"""

    def provides(self) -> frozenset[Signal[Any]]:
        return frozenset()

    def wants(self) -> frozenset[Signal[Any]]:
        return frozenset()


class DirectiveProvider(ABC):
    """派生生产者：通过「提示词契约 + 输出解析」让 LLM 产出某些 Signal。"""

    @property
    @abstractmethod
    def produces(self) -> frozenset[Signal[Any]]: ...

    @abstractmethod
    def prompt_fragment(self) -> str:
        """注入系统提示的输出契约片段。仅在协商激活后使用。"""

    @abstractmethod
    def try_extract(self, buffer: str, bag: MetadataBag) -> tuple[str, bool]:
        """尝试从 LLM 流式输出的首部提取指令。

        Returns:
            ``(剩余文本, 是否完成判定)``。未完成（前缀仍可能构成指令）时调用方
            应继续缓冲；完成后剩余文本进入正常的切句 -> TTS 链路。
        """


class SpeakTagDirective(DirectiveProvider):
    """标签式 prosody 契约：要求 LLM 在回复最开头输出一行::

        <speak emotion=gentle style=安慰>

    标签在流式输出首部即可解析完成，TTS 在第一句话合成前就拿到韵律——
    与全流式低首响不冲突。TTS 支持的情绪集合会回灌进契约，保证 LLM 只从
    该 TTS 真能渲染的集合里选。
    """

    _TAG = re.compile(r"^\s*<speak\b([^>]*)>\s*")
    _ATTR = re.compile(r"(\w+)=([^\s>]+)")
    _MAX_BUFFER = 120

    def __init__(self, supported_emotions: Sequence[RenderEmotion] = (RenderEmotion.NEUTRAL,)):
        self._supported = tuple(supported_emotions)

    @property
    def produces(self) -> frozenset[Signal[Any]]:
        return frozenset({S.prosody})

    def prompt_fragment(self) -> str:
        options = ", ".join(e.value for e in self._supported)
        return (
            "[输出规范] 回复最开头先输出一行 <speak emotion=情绪 style=语气>，"
            f"emotion 仅限: {options}。依据用户情绪共情选择，其后再写正文。"
        )

    def try_extract(self, buffer: str, bag: MetadataBag) -> tuple[str, bool]:
        match = self._TAG.match(buffer)
        if match:
            attrs = dict(self._ATTR.findall(match.group(1)))
            try:
                emotion = RenderEmotion(attrs.get("emotion", ""))
            except ValueError:
                emotion = RenderEmotion.OTHER
            bag.set(S.prosody, Prosody(emotion=emotion, style=attrs.get("style")))
            return buffer[match.end() :], True
        stripped = buffer.lstrip()
        could_still_match = (
            len(stripped) < self._MAX_BUFFER
            and ("<speak".startswith(stripped[:6]) or stripped.startswith("<speak"))
            and ">" not in stripped
        )
        if could_still_match and (not stripped or stripped.startswith("<")):
            return buffer, False
        return buffer, True  # 不是指令，原样放行


@dataclass(frozen=True, slots=True)
class NegotiationResult:
    produced: frozenset[Signal[Any]]
    wanted: frozenset[Signal[Any]]
    satisfied: frozenset[Signal[Any]]
    unmet: frozenset[Signal[Any]]
    directives: tuple[DirectiveProvider, ...]
    directive_fragment: str

    def report(self) -> str:
        """生效能力矩阵（装配期可观测）。"""

        def fmt(sigs: frozenset[Signal[Any]]) -> list[str]:
            return sorted(s.key for s in sigs)

        derived: frozenset[Signal[Any]] = (
            frozenset().union(*(d.produces for d in self.directives))
            if self.directives
            else frozenset()
        )
        lines = [
            f"产出={fmt(self.produced)}",
            f"需要={fmt(self.wanted)}",
            f"直接满足={fmt(self.satisfied)}",
            f"派生激活={fmt(derived)}",
            f"LLM输出契约={'已激活' if self.directives else '关闭(精简prompt)'}",
        ]
        return "\n".join(lines)


def negotiate(
    producers: Iterable[SignalAware],
    consumers: Iterable[SignalAware],
    derivers: Iterable[DirectiveProvider] = (),
) -> NegotiationResult:
    """装配期能力协商：算谁产、谁要，并决定是否激活派生生产者。"""
    produced = frozenset().union(*(p.provides() for p in producers)) if producers else frozenset()
    wanted = frozenset().union(*(c.wants() for c in consumers)) if consumers else frozenset()
    satisfied = produced & wanted
    unmet = wanted - produced

    active: list[DirectiveProvider] = []
    for deriver in derivers:
        if deriver.produces & unmet:
            active.append(deriver)

    fragment = "\n".join(d.prompt_fragment() for d in active)
    return NegotiationResult(
        produced=produced,
        wanted=wanted,
        satisfied=satisfied,
        unmet=unmet,
        directives=tuple(active),
        directive_fragment=fragment,
    )

"""提示词分层拼装（架构文档 7.2，沉淀自 ``Dialogue.get_llm_dialogue_with_memory``）。

四段结构（前两段稳定，利于 LLM prefix cache）::

    [system 静态前缀] -> [few-shot 虚拟历史] -> [system 动态块] -> [真实历史]

动态块由模板渲染，模板里的 ``{asr.emotion}`` 这类占位符即 Signal 软拉取的
消费点——**消费者是模板，不是 LLM 端口**。占位符解析为空的整行自动丢弃，
实现"有则注入、无则降级"。协商激活的 LLM 输出契约（DirectiveProvider 片段）
追加在动态块末尾。
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ..capabilities import SignalAware
from ..signals import SIGNAL_REGISTRY, Signal

if TYPE_CHECKING:
    from ..context import SessionContext, TurnContext

_TOKEN = re.compile(r"\{([a-z0-9_.]+)\}")

DEFAULT_DYNAMIC_TEMPLATE = (
    "当前时间：{now}\n"
    "用户当前情绪：{asr.emotion}（请据此共情回应）\n"
    "当前说话人：{speaker}\n"
    "相关记忆：{memory}"
)


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, BaseModel):
        return value.model_dump_json(exclude_none=True)
    return str(value)


class PromptComposer(SignalAware):
    def __init__(
        self,
        base_prompt: str,
        dynamic_template: str = DEFAULT_DYNAMIC_TEMPLATE,
        signals: dict[str, Signal[Any]] | None = None,
    ) -> None:
        self._base_prompt = base_prompt
        self._template = dynamic_template
        self._signals = signals if signals is not None else SIGNAL_REGISTRY

    def wants(self) -> frozenset[Signal[Any]]:
        """扫描模板占位符，声明软拉取的 Signal——参与装配期协商。"""
        keys = {m.group(1) for m in _TOKEN.finditer(self._template)}
        return frozenset(self._signals[k] for k in keys if k in self._signals)

    def compose(
        self,
        session: SessionContext,
        turn: TurnContext,
        *,
        memory: str | None = None,
        directive_fragment: str = "",
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._base_prompt}]
        messages.extend(m.to_llm() for m in session.dialogue.fewshot_messages())

        dynamic = self._render_dynamic(turn, memory)
        if directive_fragment:
            dynamic = f"{dynamic}\n{directive_fragment}" if dynamic else directive_fragment
        if dynamic:
            messages.append({"role": "system", "content": dynamic})

        messages.extend(m.to_llm() for m in session.dialogue.history_messages())
        return messages

    def _render_dynamic(self, turn: TurnContext, memory: str | None) -> str:
        builtins = {
            "now": datetime.now().strftime("%H:%M"),
            "memory": memory or "",
        }

        lines: list[str] = []
        for line in self._template.splitlines():
            had_token = False
            all_empty = True

            def replace(match: re.Match[str]) -> str:
                nonlocal had_token, all_empty
                had_token = True
                key = match.group(1)
                if key in builtins:
                    value = builtins[key]
                else:
                    signal = self._signals.get(key)
                    value = _render_value(turn.meta.get(signal)) if signal else ""
                if value:
                    all_empty = False
                return value

            rendered = _TOKEN.sub(replace, line)
            if had_token and all_empty:
                continue  # 占位符全空 -> 整行丢弃（优雅降级）
            lines.append(rendered)
        return "\n".join(lines).strip()

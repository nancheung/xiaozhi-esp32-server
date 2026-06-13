"""JSONL 文件记忆：初始化时加载历史，会话结束时追加写入。"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from xiaozhi_core.domain.dialogue import Message
from xiaozhi_core.ports.memory import MemoryPort


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """单条对话记录，对应 JSONL 文件中的一行。"""

    role: str        # "user" | "assistant"
    content: str     # 原文
    time: str        # ISO-8601 UTC
    session_id: str  # 会话 ID

    def to_jsonl_line(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> ConversationRecord:
        d = json.loads(line)
        return cls(role=d["role"], content=d["content"], time=d["time"], session_id=d["session_id"])

    def prompt_line(self) -> str:
        """格式化为注入 prompt 的文本行（只含 role / time / content）。"""
        return f"[{self.time[:16]}] {self.role}: {self.content}"


class JsonlMemory(MemoryPort):
    """JSONL 持久记忆。

    初始化时一次性将 JSONL 文件加载到 _records；query() 只读内存，无文件 I/O。
    save() 在会话结束时追加写文件，但不更新 _records——当前会话数据因此天然
    不出现在本次 query() 中，无需额外的 session_id 过滤。
    """

    def __init__(self, path: Path, *, max_records: int = 20) -> None:
        self._path = path
        self._max_records = max_records
        self._records: list[ConversationRecord] = self._load()

    def _load(self) -> list[ConversationRecord]:
        if not self._path.exists():
            return []
        records: list[ConversationRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(ConversationRecord.from_json_line(line))
                    except (json.JSONDecodeError, KeyError):
                        continue
        return records

    async def query(self, text: str) -> str | None:
        if not self._records:
            return None
        recent = self._records[-self._max_records :]
        return "\n".join(r.prompt_line() for r in recent)

    async def save(self, messages: list[Message], session_id: str) -> None:
        now = datetime.now(tz=UTC).isoformat(timespec="seconds")
        records = [
            ConversationRecord(role=m.role, content=m.content, time=now, session_id=session_id)
            for m in messages
            if m.content
        ]
        if records:
            with self._path.open("a", encoding="utf-8") as f:
                for r in records:
                    f.write(r.to_jsonl_line() + "\n")
        # 不更新 self._records：保持初始化快照，确保当前会话不污染本次查询

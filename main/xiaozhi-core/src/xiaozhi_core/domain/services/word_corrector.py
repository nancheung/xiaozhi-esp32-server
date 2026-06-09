"""流式替换词滑窗匹配（源自 xiaozhi-server ``TTSProviderBase._match_stream_text``）。

处理替换词跨流式分片的场景：逐字符匹配，前缀可能命中替换词时挂起等待，
确定不匹配后放行。
"""

from __future__ import annotations


class WordCorrector:
    def __init__(self, corrections: dict[str, str]) -> None:
        self._corrections = dict(corrections)
        # 按首字分组、长词优先，避免短词截胡
        self._by_first_char: dict[str, list[str]] = {}
        for key in sorted(self._corrections, key=len, reverse=True):
            if key:
                self._by_first_char.setdefault(key[0], []).append(key)
        self._pending = ""

    def feed(self, text: str) -> str:
        """喂入文本片段，返回已确定可放行的文本（替换后）。"""
        if not self._corrections or not text:
            return text
        out: list[str] = []
        for char in text:
            candidate = self._pending + char
            matched = False
            first = self._pending[0] if self._pending else char
            for key in self._by_first_char.get(first, ()):
                if candidate == key:
                    out.append(self._corrections[key])
                    self._pending = ""
                    matched = True
                    break
                if key.startswith(candidate):
                    self._pending = candidate
                    matched = True
                    break
            if matched:
                continue
            if self._pending:
                out.append(self._pending)
                self._pending = ""
            if char in self._by_first_char:
                self._pending = char
            else:
                out.append(char)
        return "".join(out)

    def flush(self) -> str:
        pending, self._pending = self._pending, ""
        return pending

    def reset(self) -> None:
        self._pending = ""

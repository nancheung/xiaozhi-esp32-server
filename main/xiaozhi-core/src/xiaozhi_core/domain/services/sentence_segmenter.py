"""流式切句（源自 xiaozhi-server ``TTSProviderBase._get_segment_text``）。

LLM 逐 token 输出累积于缓冲，按标点切出可即时送 TTS 的句段。
首句使用更宽松的标点集（含逗号），让第一句话更快出声、压低首响。
"""

from __future__ import annotations

DEFAULT_PUNCTUATIONS: tuple[str, ...] = ("。", "？", "?", "！", "!", "；", ";", "：")
FIRST_SENTENCE_PUNCTUATIONS: tuple[str, ...] = (
    "，",
    "~",
    "、",
    ",",
    *DEFAULT_PUNCTUATIONS,
)


class SentenceSegmenter:
    def __init__(
        self,
        punctuations: tuple[str, ...] = DEFAULT_PUNCTUATIONS,
        first_sentence_punctuations: tuple[str, ...] = FIRST_SENTENCE_PUNCTUATIONS,
    ) -> None:
        self._punctuations = punctuations
        self._first_punctuations = first_sentence_punctuations
        self._buffer = ""
        self._is_first_sentence = True

    def feed(self, text: str) -> list[str]:
        """喂入新文本，返回切出的完整句段（可能为空）。"""
        self._buffer += text
        segments: list[str] = []
        while True:
            puncts = self._first_punctuations if self._is_first_sentence else self._punctuations
            cut = max((self._buffer.rfind(p) for p in puncts), default=-1)
            if cut == -1:
                break
            segment = self._buffer[: cut + 1].strip()
            self._buffer = self._buffer[cut + 1 :]
            if segment:
                segments.append(segment)
                self._is_first_sentence = False
        return segments

    def flush(self) -> str | None:
        """流结束时取出剩余文本。"""
        remaining = self._buffer.strip()
        self._buffer = ""
        self._is_first_sentence = True
        return remaining or None

    def reset(self) -> None:
        self._buffer = ""
        self._is_first_sentence = True

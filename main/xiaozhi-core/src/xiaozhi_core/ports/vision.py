"""视觉端口（架构文档 7.1）。

两种触发模式共用本端口：
- 带外：``VisionHttpAdapter``（独立 HTTP 入口）直接调用；
- 带内：包装成 ``vision.describe`` 工具挂到 ToolPort，由 LLM 主动调用。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class VisionPort(ABC):
    @abstractmethod
    async def describe(self, question: str, image: bytes) -> str: ...

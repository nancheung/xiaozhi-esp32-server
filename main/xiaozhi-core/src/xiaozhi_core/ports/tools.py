"""工具端口（架构文档 7.5）：统一 ``list + execute``，双作用域聚合。

- ``StaticToolProvider``：进程级内置固定工具（装饰器注册，如退出对话）。
- ``SessionToolProvider``：会话级动态工具（设备 IoT descriptors / device-MCP
  tools/list 运行时注册，仅活在本会话）。
- ``CompositeToolPort``：聚合多 provider 并按名路由（继承现状
  UnifiedToolManager 的职责）。

执行器签名统一为 ``async/sync fn(**arguments) -> ActionResponse``；
需要会话状态的工具用闭包捕获（如退出工具捕获 SessionContext）。
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..domain.actions import Action, ActionResponse, ToolDefinition

ToolFunc = Callable[..., Any]


class ToolPort(ABC):
    @abstractmethod
    def list_tools(self) -> list[ToolDefinition]: ...

    @abstractmethod
    def has_tool(self, name: str) -> bool: ...

    @abstractmethod
    async def execute(self, name: str, arguments: dict[str, Any]) -> ActionResponse: ...


class _RegistryToolProvider(ToolPort):
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolFunc]] = {}

    def register(self, definition: ToolDefinition, func: ToolFunc) -> None:
        self._tools[definition.name] = (definition, func)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def clear(self) -> None:
        self._tools.clear()

    def list_tools(self) -> list[ToolDefinition]:
        return [definition for definition, _ in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, arguments: dict[str, Any]) -> ActionResponse:
        entry = self._tools.get(name)
        if entry is None:
            return ActionResponse(action=Action.ERROR, result=f"未知工具: {name}")
        _, func = entry
        result = func(**arguments)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, ActionResponse):
            return result
        return ActionResponse(action=Action.REQLLM, result=str(result))


class StaticToolProvider(_RegistryToolProvider):
    """进程级内置固定工具。提供装饰器注册风格。"""

    def tool(self, definition: ToolDefinition) -> Callable[[ToolFunc], ToolFunc]:
        def decorator(func: ToolFunc) -> ToolFunc:
            self.register(definition, func)
            return func

        return decorator


class SessionToolProvider(_RegistryToolProvider):
    """会话级动态工具：随 IotDescriptors / McpToolsListed 注册，会话结束即弃。"""


class CompositeToolPort(ToolPort):
    def __init__(self, providers: list[ToolPort] | None = None) -> None:
        self.providers: list[ToolPort] = providers or []

    def add_provider(self, provider: ToolPort) -> None:
        self.providers.append(provider)

    def list_tools(self) -> list[ToolDefinition]:
        tools: dict[str, ToolDefinition] = {}
        for provider in self.providers:
            for definition in provider.list_tools():
                tools[definition.name] = definition
        return list(tools.values())

    def has_tool(self, name: str) -> bool:
        return any(p.has_tool(name) for p in self.providers)

    async def execute(self, name: str, arguments: dict[str, Any]) -> ActionResponse:
        for provider in self.providers:
            if provider.has_tool(name):
                return await provider.execute(name, arguments)
        return ActionResponse(action=Action.ERROR, result=f"未知工具: {name}")

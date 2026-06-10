"""工具端口：执行错误隔离。

LLM 生成的参数不可信（幻觉参数 / 类型错误），工具自身也可能抛错——
执行失败必须转为 ``ActionResponse(ERROR)`` 带上下文返回，绝不向上抛异常
（否则会被事件总线吞掉，导致本轮无法收束、会话死锁）。
"""

import asyncio

from xiaozhi_core import Action, ActionResponse, ToolDefinition
from xiaozhi_core.ports.tools import StaticToolProvider


def _provider_with_echo() -> StaticToolProvider:
    provider = StaticToolProvider()

    @provider.tool(ToolDefinition(name="echo", description={"name": "echo"}))
    def echo(text: str) -> ActionResponse:
        return ActionResponse(action=Action.RESPONSE, response=text)

    return provider


def test_hallucinated_argument_returns_error_response():
    provider = _provider_with_echo()
    response = asyncio.run(provider.execute("echo", {"text": "你好", "bogus": 1}))
    assert response.action is Action.ERROR
    assert response.result and "echo" in response.result  # 错误信息带工具名上下文


def test_tool_raising_returns_error_response():
    provider = StaticToolProvider()

    @provider.tool(ToolDefinition(name="boom", description={"name": "boom"}))
    def boom() -> ActionResponse:
        raise RuntimeError("内部故障")

    response = asyncio.run(provider.execute("boom", {}))
    assert response.action is Action.ERROR
    assert response.result and "内部故障" in response.result


def test_valid_arguments_still_execute():
    provider = _provider_with_echo()
    response = asyncio.run(provider.execute("echo", {"text": "你好"}))
    assert response.action is Action.RESPONSE
    assert response.response == "你好"

"""FastAPI WebSocket 传输适配器：设备协议 <-> 入站事件。

安装：``pip install "xiaozhi-core[server]"``。出站消息序列与现有
xiaozhi-server 设备协议一致（hello/stt/tts 状态 + 二进制音频帧）。

注意：本模块不启用 ``from __future__ import annotations``——FastAPI 需要在
运行时即时求值 endpoint 的参数注解（``fastapi.WebSocket`` 在 create_app 内
局部导入）。
"""

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from ..domain.events import (
    AbortRequested,
    AudioFrameReceived,
    Event,
    HelloReceived,
    IotDescriptorsReceived,
    IotStatesReceived,
    ListenStateChanged,
    McpToolsListed,
    PingReceived,
)
from ..ports.transport import TransportPort

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import WebSocket


def parse_device_message(raw: str | bytes) -> Event | None:
    """设备原始消息 -> 入站事件（协议防腐层，纯函数可单测）。"""
    if isinstance(raw, bytes):
        return AudioFrameReceived(frame=raw)
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    msg_type = message.get("type")
    match msg_type:
        case "hello":
            return HelloReceived(payload=message)
        case "listen":
            return ListenStateChanged(state=message.get("state", ""), text=message.get("text"))
        case "abort":
            return AbortRequested()
        case "iot":
            if "descriptors" in message:
                return IotDescriptorsReceived(descriptors=message["descriptors"])
            return IotStatesReceived(states=message.get("states", []))
        case "mcp":
            payload = message.get("payload", {})
            tools = payload.get("result", {}).get("tools")
            if tools is not None:
                return McpToolsListed(tools=tools)
            return None
        case "ping":
            return PingReceived()
        case _:
            return None


class FastApiWebSocketTransport(TransportPort):
    def __init__(self, websocket: "WebSocket") -> None:
        self._ws = websocket

    async def events(self) -> AsyncIterator[Event]:
        from starlette.websockets import WebSocketDisconnect

        while True:
            try:
                raw = await self._ws.receive()
            except WebSocketDisconnect:
                return
            if raw.get("type") == "websocket.disconnect":
                return
            data: str | bytes | None = raw.get("bytes") or raw.get("text")
            if data is None:
                continue
            event = parse_device_message(data)
            if event is not None:
                yield event

    async def send_event(self, message: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(message, ensure_ascii=False))

    async def send_audio(self, frame: bytes) -> None:
        await self._ws.send_bytes(frame)

    async def close(self) -> None:
        try:
            await self._ws.close()
        except RuntimeError:
            pass


def create_app(server: Any) -> Any:
    """构建承载 WebSocket 入口的 FastAPI 应用。

    Args:
        server: ``XiaozhiServer`` 会话工厂。
    """
    import fastapi

    app = fastapi.FastAPI(title="xiaozhi-core")

    @app.websocket("/xiaozhi/v1/")
    async def websocket_endpoint(websocket: fastapi.WebSocket) -> None:
        await websocket.accept()
        transport = FastApiWebSocketTransport(websocket)
        runtime = server.create_session(transport=transport)
        await runtime.run()

    return app

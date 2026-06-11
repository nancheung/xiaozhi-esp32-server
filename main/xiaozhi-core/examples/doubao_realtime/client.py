"""豆包 Realtime Dialog 异步 WebSocket 客户端（依赖 websockets）。

只做协议收发，不含任何编排逻辑；编排在 ``stage.DoubaoRealtimeStage``。
测试用 ``tests`` 里的 FakeDoubaoClient 替换（鸭子类型，方法签名一致即可）。
"""

from __future__ import annotations

import copy
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from . import config, protocol
from .protocol import ServerMessage

logger = logging.getLogger(__name__)


class DoubaoRealtimeClient:
    def __init__(
        self,
        ws_config: dict[str, Any] | None = None,
        session_req: dict[str, Any] | None = None,
    ) -> None:
        self._ws_config = ws_config or config.ws_connect_config
        self._session_req = copy.deepcopy(session_req or config.start_session_req)
        self.session_id = str(uuid.uuid4())
        self._ws: Any = None

    async def connect(self) -> None:
        """建连 -> StartConnection(1) -> StartSession(100)。"""
        import websockets

        headers = self._ws_config["headers"]
        if not headers.get("X-Api-App-ID") or not headers.get("X-Api-Access-Key"):
            raise RuntimeError(
                "缺少豆包鉴权信息：请在 examples/doubao_realtime/config.py 的 "
                "ws_connect_config['headers'] 填入 X-Api-App-ID 与 X-Api-Access-Key"
            )
        try:
            self._ws = await websockets.connect(
                self._ws_config["base_url"], additional_headers=headers, ping_interval=None
            )
        except TypeError:  # websockets < 13 的旧参数名
            self._ws = await websockets.connect(
                self._ws_config["base_url"], extra_headers=headers, ping_interval=None
            )

        await self._ws.send(protocol.marshal_event(protocol.EVENT_START_CONNECTION, {}))
        reply = protocol.parse_server_message(await self._ws.recv())
        logger.info("StartConnection 响应: %s", reply)

        await self._ws.send(
            protocol.marshal_event(
                protocol.EVENT_START_SESSION, self._session_req, session_id=self.session_id
            )
        )
        reply = protocol.parse_server_message(await self._ws.recv())
        logger.info("StartSession 响应: %s", reply)

    async def say_hello(self, content: str) -> None:
        await self._ws.send(
            protocol.marshal_event(
                protocol.EVENT_SAY_HELLO, {"content": content}, session_id=self.session_id
            )
        )

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send(protocol.marshal_audio(self.session_id, pcm))

    async def send_chat_tts_text(self, *, start: bool, end: bool, content: str) -> None:
        """event 500 ChatTTSText：注入机器人回复文本，由豆包仅做 TTS 播报。"""
        await self._ws.send(
            protocol.marshal_event(
                protocol.EVENT_CHAT_TTS_TEXT,
                {"start": start, "end": end, "content": content},
                session_id=self.session_id,
            )
        )

    async def send_chat_rag_text(self, *, external_rag: str) -> None:
        """event 502 ChatRAGText：注入外部知识，豆包云端 LLM 据此重新生成润色回答。"""
        await self._ws.send(
            protocol.marshal_event(
                protocol.EVENT_CHAT_RAG_TEXT,
                {"external_rag": external_rag},
                session_id=self.session_id,
            )
        )

    async def messages(self) -> AsyncIterator[ServerMessage]:
        """持续产出服务端消息，连接关闭时结束。"""
        import websockets

        while True:
            try:
                data = await self._ws.recv()
            except websockets.ConnectionClosed:
                return
            if isinstance(data, str):
                logger.debug("忽略文本帧: %s", data)
                continue
            yield protocol.parse_server_message(data)

    async def close(self) -> None:
        """FinishSession(102) -> FinishConnection(2) -> 关闭 WS。容忍连接已断。"""
        if self._ws is None:
            return
        try:
            await self._ws.send(
                protocol.marshal_event(
                    protocol.EVENT_FINISH_SESSION, {}, session_id=self.session_id
                )
            )
            await self._ws.send(protocol.marshal_event(protocol.EVENT_FINISH_CONNECTION, {}))
        except Exception as exc:
            logger.debug("关闭握手未完成（连接可能已断）: %s", exc)
        await self._ws.close()
        self._ws = None

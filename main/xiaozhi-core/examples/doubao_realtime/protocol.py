"""豆包 Realtime Dialog 二进制协议（纯函数，零外部依赖）。

帧格式（移植自官方 demo 的 protocol.py）::

    4 字节 header：版本/头大小 | 消息类型/标志 | 序列化/压缩 | 保留
    [4 字节 event id]          —— 标志含 MSG_WITH_EVENT 时存在
    [4 字节长度 + session_id]  —— 会话级事件存在
    4 字节长度 + payload       —— gzip 压缩的 JSON 或原始音频
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL_VERSION = 0b0001

# 消息类型
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# 消息标志
NO_FLAG = 0b0000
NEG_SEQUENCE = 0b0010
MSG_WITH_EVENT = 0b0100

# 序列化 / 压缩
NO_SERIALIZATION = 0b0000
JSON_SERIALIZATION = 0b0001
NO_COMPRESSION = 0b0000
GZIP_COMPRESSION = 0b0001

# 客户端事件
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_TASK_REQUEST = 200
EVENT_SAY_HELLO = 300
EVENT_CHAT_TTS_TEXT = 500
EVENT_CHAT_TEXT_QUERY = 501
EVENT_CHAT_RAG_TEXT = 502

# 服务端事件
EVENT_SESSION_STARTED = 150   # 服务端确认 session 建立，payload 含 dialog_id
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_USAGE_RESPONSE = 154    # token 用量统计（每轮交互后下发）
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351  # 分句 TTS 结束，payload 含精确文本和音频时长
EVENT_TTS_ENDED = 359
EVENT_ASR_INFO = 450  # 用户开始说话（SPEAKING 中收到即打断信号）
EVENT_ASR_RESPONSE = 451  # ASR 识别文本（增量覆盖）
EVENT_ASR_ENDED = 459  # 用户说话结束
EVENT_CHAT_RESPONSE = 550  # 云端 LLM 文本增量
EVENT_CHAT_ENDED = 559     # 云端 LLM 文本生成结束
EVENT_DIALOG_COMMON_ERROR = 599  # 实时通话期间错误描述


def encode_frame(
    message_type: int,
    *,
    event: int | None = None,
    session_id: str | None = None,
    payload: bytes = b"",
    serialization: int = JSON_SERIALIZATION,
    compression: int = GZIP_COMPRESSION,
) -> bytes:
    """编一帧。客户端发送与测试构造服务端帧共用。"""
    flags = MSG_WITH_EVENT if event is not None else NO_FLAG
    frame = bytearray()
    frame.append((PROTOCOL_VERSION << 4) | 0b0001)  # header_size 固定 1（无扩展头）
    frame.append((message_type << 4) | flags)
    frame.append((serialization << 4) | compression)
    frame.append(0x00)
    if event is not None:
        frame.extend(event.to_bytes(4, "big"))
    if session_id is not None:
        sid = session_id.encode()
        frame.extend(len(sid).to_bytes(4, "big"))
        frame.extend(sid)
    if compression == GZIP_COMPRESSION:
        payload = gzip.compress(payload)
    frame.extend(len(payload).to_bytes(4, "big"))
    frame.extend(payload)
    return bytes(frame)


def marshal_event(event: int, payload: dict[str, Any], session_id: str | None = None) -> bytes:
    """客户端 JSON 事件帧（StartConnection/StartSession/ChatTTSText 等）。"""
    return encode_frame(
        CLIENT_FULL_REQUEST,
        event=event,
        session_id=session_id,
        payload=json.dumps(payload, ensure_ascii=False).encode(),
    )


def marshal_audio(session_id: str, pcm: bytes) -> bytes:
    """客户端音频帧（event 200 TaskRequest）。"""
    return encode_frame(
        CLIENT_AUDIO_ONLY_REQUEST,
        event=EVENT_TASK_REQUEST,
        session_id=session_id,
        payload=pcm,
        serialization=NO_SERIALIZATION,
    )


@dataclass(slots=True)
class ServerMessage:
    """解析后的服务端消息。kind: full_response | ack | error | unknown。"""

    kind: str
    event: int | None = None
    session_id: str | None = None
    payload: dict[str, Any] | None = None
    audio: bytes | None = None
    code: int | None = None

    def to_dict(self, *, exclude_audio: bool = True):
        d = asdict(self)

        audio = d.get("audio")
        if audio is not None and exclude_audio:
            d["audio"] = f"<bytes {len(d["audio"])}>"
        return d


def parse_server_message(data: bytes) -> ServerMessage:
    """解一帧服务端消息。未知消息类型返回 kind="unknown"（调用方丢弃）。"""
    header_size = data[0] & 0x0F
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    body = data[header_size * 4 :]

    if message_type in (SERVER_FULL_RESPONSE, SERVER_ACK):
        event: int | None = None
        if flags & NEG_SEQUENCE:
            body = body[4:]  # 序号，样例不消费
        if flags & MSG_WITH_EVENT:
            event = int.from_bytes(body[:4], "big")
            body = body[4:]
        sid_len = int.from_bytes(body[:4], "big")
        session_id = body[4 : 4 + sid_len].decode("utf-8", errors="replace")
        body = body[4 + sid_len :]
        raw = body[4:]  # 跳过 4 字节 payload 长度
        if compression == GZIP_COMPRESSION:
            raw = gzip.decompress(raw)
        if message_type == SERVER_ACK or serialization == NO_SERIALIZATION:
            return ServerMessage(kind="ack", event=event, session_id=session_id, audio=raw)
        payload = json.loads(raw) if raw else None
        return ServerMessage(
            kind="full_response", event=event, session_id=session_id, payload=payload
        )

    if message_type == SERVER_ERROR_RESPONSE:
        code = int.from_bytes(body[:4], "big")
        raw = body[8:]
        if compression == GZIP_COMPRESSION:
            raw = gzip.decompress(raw)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            payload = {"raw": raw.decode("utf-8", errors="replace")}
        return ServerMessage(kind="error", code=code, payload=payload)

    return ServerMessage(kind="unknown")


def extract_asr_text(payload: dict[str, Any] | None) -> tuple[str, bool]:
    """从 451 ASRResponse 提取识别文本和是否为最终结果。

    Returns:
        (text, is_final): is_final=True 表示 is_interim=False 的最终确认结果。
    """
    if not payload:
        return "", False
    results = payload.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        r = results[0]
        return str(r.get("text", "")), not r.get("is_interim", True)
    return str(payload.get("text", "")), False

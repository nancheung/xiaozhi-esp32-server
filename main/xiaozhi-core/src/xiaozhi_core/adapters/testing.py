"""测试/示例用 Fake 适配器：无外部依赖即可跑通完整链路。

同时是「实现者如何声明 / 生产 / 消费」的参考样例：
- ``FakeAsr``：``provides()`` 受 ``supports_emotion`` 门控——高级能力非核心能力；
  防腐层把厂商原始标签归一化为核心规范类型后写入轮次黑板。
- ``EmotionalFakeTts``：``wants() -> {S.prosody}`` 软需求，反向激活 LLM 输出契约；
  ``synthesize`` 把核心 ``Prosody`` 映射为自家参数。
- ``NeutralFakeTts``：零声明 -> 链路自动降级为纯文本。
- ``ScriptedLlm``：自身对元数据零感知；是否输出 ``<speak>`` 标签完全由系统提示里
  有没有被激活的 [输出规范] 契约决定。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..domain.events import Event
from ..domain.signals import (
    MetadataBag,
    PerceivedEmotion,
    Prosody,
    RenderEmotion,
    S,
    Signal,
    SpeakerInfo,
)
from ..ports.asr import AsrPort
from ..ports.llm import LlmDelta, LlmPort
from ..ports.memory import MemoryPort
from ..ports.transport import TransportPort
from ..ports.tts import TtsPort
from ..ports.vad import VadPort, VadResult
from ..ports.voiceprint import VoiceprintPort

VOICE_FRAME = b"V"
SILENCE_FRAME = b"_"

_RAW_EMOTION_ACL = {
    "<|SAD|>": PerceivedEmotion.SAD,
    "<|HAPPY|>": PerceivedEmotion.HAPPY,
    "<|ANGRY|>": PerceivedEmotion.ANGRY,
}


class FakeVad(VadPort):
    """``b"V"`` 为语音帧；连续 ``silence_window`` 个静音帧判停。"""

    def __init__(self, silence_window: int = 2) -> None:
        self._silence_window = silence_window
        self._had_voice = False
        self._silence = 0

    def detect(self, frame: bytes) -> VadResult:
        is_voice = frame == VOICE_FRAME
        if is_voice:
            self._had_voice = True
            self._silence = 0
            return VadResult(is_voice=True)
        if not self._had_voice:
            return VadResult()
        self._silence += 1
        if self._silence >= self._silence_window:
            self.reset()
            return VadResult(voice_stopped=True)
        return VadResult()

    def reset(self) -> None:
        self._had_voice = False
        self._silence = 0


class FakeAsr(AsrPort):
    def __init__(
        self,
        text: str = "我今天好累，什么都不想做",
        raw_emotion: str | None = "<|SAD|>",
        speech_rate: float = -0.3,
        supports_emotion: bool = True,
    ) -> None:
        self._text = text
        self._raw_emotion = raw_emotion
        self._speech_rate = speech_rate
        self.supports_emotion = supports_emotion

    def provides(self) -> frozenset[Signal[Any]]:
        base: set[Signal[Any]] = {S.language}
        if self.supports_emotion:
            base |= {S.asr_emotion, S.asr_speech_rate}
        return frozenset(base)

    async def transcribe(self, frames: list[bytes], bag: MetadataBag) -> str:
        bag.set(S.language, "zh")
        if self.supports_emotion and self._raw_emotion:
            emotion = _RAW_EMOTION_ACL.get(self._raw_emotion, PerceivedEmotion.OTHER)
            bag.set(S.asr_emotion, emotion)
            bag.set(S.asr_speech_rate, self._speech_rate)
        return self._text


class FakeVoiceprint(VoiceprintPort):
    def __init__(self, speaker: SpeakerInfo | None = None) -> None:
        self._speaker = speaker or SpeakerInfo(name="阿珍", description="家人，喜欢开玩笑")

    async def identify(self, frames: list[bytes]) -> SpeakerInfo | None:
        return self._speaker


class ScriptedLlm(LlmPort):
    """按系统提示内容决定输出形态；记录最近一次 messages 供测试断言。"""

    def __init__(self, reply: str = "听起来真的辛苦了。先休息一下，待会儿陪我聊聊好不好？") -> None:
        self._reply = reply
        self.last_messages: list[dict[str, Any]] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmDelta]:
        self.last_messages = messages
        system_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        reply = self._reply
        if "[输出规范]" in system_text:
            reply = f"<speak emotion=gentle style=安慰>{reply}"
        for i in range(0, len(reply), 4):  # 逐 4 字符流式，模拟 token 流
            await asyncio.sleep(0)
            yield LlmDelta(text=reply[i : i + 4])


class EmotionalFakeTts(TtsPort):
    """支持韵律渲染的 TTS：声明软需求 + 反向映射核心 Prosody 到自家参数。"""

    def __init__(self) -> None:
        self.synth_calls: list[tuple[str, dict[str, Any]]] = []

    def wants(self) -> frozenset[Signal[Any]]:
        return frozenset({S.prosody})

    def supported_render_emotions(self) -> tuple[RenderEmotion, ...]:
        return (
            RenderEmotion.NEUTRAL,
            RenderEmotion.GENTLE,
            RenderEmotion.EXCITED,
            RenderEmotion.COMFORT,
        )

    async def synthesize(
        self, text: str, *, prosody: Prosody | None = None
    ) -> AsyncIterator[bytes]:
        vendor_params = self._to_vendor_params(prosody)
        self.synth_calls.append((text, vendor_params))
        for i in range(2):  # 每句两帧
            await asyncio.sleep(0)
            yield f"opus[{vendor_params['emotion']}]:{text}#{i}".encode()

    @staticmethod
    def _to_vendor_params(prosody: Prosody | None) -> dict[str, Any]:
        if prosody is None:
            return {"emotion": "neutral", "style": "", "speed": 0}
        vendor_emotion = {
            RenderEmotion.GENTLE: "warm",
            RenderEmotion.COMFORT: "warm",
            RenderEmotion.EXCITED: "lively",
        }.get(prosody.emotion or RenderEmotion.NEUTRAL, "neutral")
        return {
            "emotion": vendor_emotion,
            "style": prosody.style or "",
            "speed": int((prosody.rate or 0) * 50),
        }


class NeutralFakeTts(TtsPort):
    """不支持任何高级特性的 TTS：零声明，链路自动降级。"""

    def __init__(self) -> None:
        self.synth_calls: list[str] = []

    async def synthesize(
        self, text: str, *, prosody: Prosody | None = None
    ) -> AsyncIterator[bytes]:
        self.synth_calls.append(text)
        await asyncio.sleep(0)
        yield f"opus:{text}".encode()


class InMemoryTransport(TransportPort):
    """测试桩传输：记录出站，入站经 ``feed`` 注入。"""

    def __init__(self) -> None:
        self.sent_events: list[dict[str, Any]] = []
        self.sent_audio: list[bytes] = []
        self.closed = False
        self._inbound: asyncio.Queue[Event | None] = asyncio.Queue()

    async def feed(self, event: Event) -> None:
        await self._inbound.put(event)

    async def finish(self) -> None:
        await self._inbound.put(None)

    async def events(self) -> AsyncIterator[Event]:
        while True:
            event = await self._inbound.get()
            if event is None:
                return
            yield event

    async def send_event(self, message: dict[str, Any]) -> None:
        self.sent_events.append(message)

    async def send_audio(self, frame: bytes) -> None:
        self.sent_audio.append(frame)

    async def close(self) -> None:
        self.closed = True


class InMemoryMemory(MemoryPort):
    def __init__(self, memory_text: str | None = None) -> None:
        self._memory_text = memory_text
        self.saved: list[tuple[str, int]] = []

    async def query(self, text: str) -> str | None:
        return self._memory_text

    async def save(self, messages: list[Any], session_id: str) -> None:
        self.saved.append((session_id, len(messages)))

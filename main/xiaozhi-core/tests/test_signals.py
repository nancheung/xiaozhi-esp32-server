"""Signal / MetadataBag：强类型令牌与运行时校验。"""

import pytest
from pydantic import BaseModel, ValidationError

from xiaozhi_core import MetadataBag, PerceivedEmotion, Prosody, RenderEmotion, S, Signal


def test_bag_set_get_typed():
    bag = MetadataBag()
    bag.set(S.asr_emotion, PerceivedEmotion.SAD)
    bag.set(S.asr_speech_rate, -0.3)
    assert bag.get(S.asr_emotion) is PerceivedEmotion.SAD
    assert bag.get(S.asr_speech_rate) == -0.3
    assert bag.get(S.prosody) is None


def test_bag_validates_on_set():
    bag = MetadataBag()
    with pytest.raises(ValidationError):
        bag.set(S.asr_speech_rate, "不是数字")  # type: ignore[arg-type]
    # 可被校验转换的值正常通过（"sad" -> PerceivedEmotion.SAD）
    bag.set(S.asr_emotion, "sad")  # type: ignore[arg-type]
    assert bag.get(S.asr_emotion) is PerceivedEmotion.SAD


def test_vendor_extension_signal():
    class WordTimestamps(BaseModel):
        words: list[str]
        offsets_ms: list[int]

    vendor_sig = Signal("doubao.word_timestamps", WordTimestamps, "豆包逐字时间戳")
    bag = MetadataBag()
    bag.set(vendor_sig, WordTimestamps(words=["你", "好"], offsets_ms=[0, 200]))
    value = bag.get(vendor_sig)
    assert value is not None and value.words == ["你", "好"]
    assert "doubao.word_timestamps" in bag.snapshot()


def test_prosody_normalized_range():
    with pytest.raises(ValidationError):
        Prosody(rate=2.0)
    p = Prosody(emotion=RenderEmotion.GENTLE, style="安慰", rate=-0.5)
    assert p.emotion is RenderEmotion.GENTLE

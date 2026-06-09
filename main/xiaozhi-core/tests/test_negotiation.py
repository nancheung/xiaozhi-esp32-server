"""装配期能力协商：情绪四态降级矩阵（架构文档 7.3.3）。"""

from xiaozhi_core import MetadataBag, PromptComposer, Prosody, RenderEmotion, S, negotiate
from xiaozhi_core.adapters.testing import EmotionalFakeTts, FakeAsr, NeutralFakeTts
from xiaozhi_core.domain.capabilities import SpeakTagDirective


def _negotiate(asr, tts):
    composer = PromptComposer("你是助手。")
    return negotiate(
        producers=[asr, tts],
        consumers=[composer, tts],
        derivers=[SpeakTagDirective(tts.supported_render_emotions())],
    )


def test_emotional_asr_emotional_tts_full_chain():
    result = _negotiate(FakeAsr(supports_emotion=True), EmotionalFakeTts())
    assert S.asr_emotion in result.satisfied  # 软拉取直接满足
    assert result.directives  # prosody 无人天然产 -> 派生激活
    assert "[输出规范]" in result.directive_fragment
    assert "gentle" in result.directive_fragment  # TTS 支持集合回灌进契约


def test_emotional_asr_neutral_tts_no_directive():
    result = _negotiate(FakeAsr(supports_emotion=True), NeutralFakeTts())
    assert S.asr_emotion in result.satisfied  # 共情线仍在
    assert not result.directives  # TTS 不要 prosody -> 契约关闭，prompt 精简
    assert result.directive_fragment == ""


def test_plain_asr_emotional_tts_directive_still_active():
    result = _negotiate(FakeAsr(supports_emotion=False), EmotionalFakeTts())
    assert S.asr_emotion not in result.produced
    assert result.directives  # TTS 的需求与 ASR 能力无关，仍反向激活


def test_plain_asr_neutral_tts_zero_overhead():
    result = _negotiate(FakeAsr(supports_emotion=False), NeutralFakeTts())
    assert not result.directives
    assert S.asr_emotion not in result.satisfied


def test_speak_tag_directive_streaming_extract():
    directive = SpeakTagDirective([RenderEmotion.GENTLE])
    bag = MetadataBag()
    # 标签跨分片到达：先不完整 -> 继续缓冲
    remaining, done = directive.try_extract("<spe", bag)
    assert not done
    remaining, done = directive.try_extract("<speak emotion=gentle style=安慰>你好", bag)
    assert done and remaining == "你好"
    prosody = bag.get(S.prosody)
    assert isinstance(prosody, Prosody) and prosody.emotion is RenderEmotion.GENTLE
    assert prosody.style == "安慰"


def test_speak_tag_directive_passthrough_non_tag():
    directive = SpeakTagDirective([RenderEmotion.GENTLE])
    bag = MetadataBag()
    remaining, done = directive.try_extract("你好呀", bag)
    assert done and remaining == "你好呀"
    assert bag.get(S.prosody) is None

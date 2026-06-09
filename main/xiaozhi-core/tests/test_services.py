"""领域服务：切句 / 替换词滑窗。"""

from xiaozhi_core import SentenceSegmenter, WordCorrector


def test_segmenter_first_sentence_uses_loose_punctuation():
    seg = SentenceSegmenter()
    assert seg.feed("你好，") == ["你好，"]  # 首句逗号即切，快速出声
    assert seg.feed("今天天气，不错。") == ["今天天气，不错。"]  # 此后仅句末标点
    assert seg.feed("还有尾巴") == []
    assert seg.flush() == "还有尾巴"


def test_segmenter_streaming_accumulation():
    seg = SentenceSegmenter()
    out: list[str] = []
    for token in ["听起来", "真的辛苦了", "。先休息", "一下！好不好"]:
        out.extend(seg.feed(token))
    out_flush = seg.flush()
    assert out == ["听起来真的辛苦了", "。先休息一下！"] or out == [
        "听起来真的辛苦了。",
        "先休息一下！",
    ]
    assert out_flush == "好不好"


def test_word_corrector_cross_chunk_match():
    wc = WordCorrector({"小志": "小智"})
    # 替换词跨分片到达
    assert wc.feed("你好小") == "你好"
    assert wc.feed("志同学") == "小智同学"
    assert wc.flush() == ""


def test_word_corrector_pending_flush():
    wc = WordCorrector({"小志": "小智"})
    assert wc.feed("叫我小") == "叫我"
    assert wc.flush() == "小"  # 未成词的前缀原样放行

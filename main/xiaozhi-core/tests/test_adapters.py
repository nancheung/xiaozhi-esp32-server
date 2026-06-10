"""litellm 适配器协议防腐层：OpenAI 流式 tool_call 分片聚合。

OpenAI 流式协议中，工具调用的 ``id``/``name`` 只出现在首个 delta，
后续参数分片 ``id=None``，仅靠 ``index`` 关联——适配器必须把同一调用的
全部分片解析到同一个 ``call_id``，否则下游按 call_id 聚合会裂成多条。
"""

from types import SimpleNamespace

from xiaozhi_core.adapters.litellm_llm import resolve_tool_call_delta
from xiaozhi_core.domain.stages.llm import LlmStage


def _chunk_call(index, call_id=None, name=None, arguments=""):
    """模拟 litellm 流式 chunk 中的单个 tool_call 分片。"""
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_sharded_tool_call_resolves_to_single_call_id():
    index_to_id: dict[int, str] = {}
    shards = [
        _chunk_call(0, call_id="call_abc", name="get_weather"),
        _chunk_call(0, arguments='{"city": '),
        _chunk_call(0, arguments='"上海"}'),
    ]
    deltas = [resolve_tool_call_delta(s, index_to_id) for s in shards]

    assert all(d.call_id == "call_abc" for d in deltas)

    merged: dict[str, object] = {}
    for delta in deltas:
        LlmStage._merge_tool_call(merged, delta)
    assert list(merged) == ["call_abc"]
    call = merged["call_abc"]
    assert call.name == "get_weather"
    assert call.arguments_fragment == '{"city": "上海"}'


def test_parallel_tool_calls_interleaved_by_index():
    index_to_id: dict[int, str] = {}
    shards = [
        _chunk_call(0, call_id="call_a", name="get_weather"),
        _chunk_call(1, call_id="call_b", name="play_music"),
        _chunk_call(0, arguments='{"city": "北京"}'),
        _chunk_call(1, arguments='{"song": "晴天"}'),
    ]
    deltas = [resolve_tool_call_delta(s, index_to_id) for s in shards]

    merged: dict[str, object] = {}
    for delta in deltas:
        LlmStage._merge_tool_call(merged, delta)
    assert set(merged) == {"call_a", "call_b"}
    assert merged["call_a"].arguments_fragment == '{"city": "北京"}'
    assert merged["call_b"].arguments_fragment == '{"song": "晴天"}'


def test_missing_id_falls_back_to_index_key():
    """个别厂商全程不带 id：退化为按 index 合成稳定 call_id。"""
    index_to_id: dict[int, str] = {}
    shards = [
        _chunk_call(0, name="get_weather"),
        _chunk_call(0, arguments="{}"),
    ]
    deltas = [resolve_tool_call_delta(s, index_to_id) for s in shards]
    assert deltas[0].call_id == deltas[1].call_id == "call_0"

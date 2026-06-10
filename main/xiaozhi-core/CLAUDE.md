# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

`xiaozhi-core` 是小智服务端的**领域核心包**：六边形架构 + 事件驱动的语音对话编排引擎。它独立于
仓库其余部分（`xiaozhi-server` / `manager-*`），是一个可单独 `uv sync` 的 Python 包。完整设计见
[`docs/architecture/hexagonal-design.md`](../../docs/architecture/hexagonal-design.md)（仓库根 `docs/`）。
源码中的注释大量引用「架构文档 X.X」即指该文件的章节号。

## 常用命令

```bash
uv sync                                    # 安装依赖（自动获取 Python 3.12）
uv run pytest                              # 全量测试
uv run pytest tests/test_pipeline.py       # 单文件
uv run pytest tests/test_pipeline.py::test_full_turn_emotional_chain   # 单个用例
uv run ruff check .                        # lint
uv run ruff format .                       # 格式化
uv run python examples/minimal_server.py   # 跑能力协商对比演示（无需真实 adapter）
```

完成任务前务必跑 `ruff check` 与 `pytest`。Ruff 配置：line-length 100，启用 `E F I UP B ASYNC RUF`，
但忽略 `RUF001/002/003`（中文全角标点）。

## 架构分层（六边形）

四个目录对应六边形的内外圈，**依赖方向严格单向：adapters → ports → domain**。

- **`domain/`** —— 领域核心，**只允许依赖 Pydantic + 标准库**。任何 framework 依赖（FastAPI、litellm 等）
  混入这里都是架构违规。
- **`ports/`** —— 端口契约（抽象接口）：`vad/asr/llm/tts/tools/memory/intent/vision/voiceprint/transport/report`。
  最小可运行集 = `vad + asr + llm + tts`，其余为 `None` 时对应链路自动降级。
- **`adapters/`** —— 端口的具体实现，框架性依赖全封装在此（`litellm_llm.py` 走 extra `llm`，
  `fastapi_transport.py` 走 extra `server`）。
- **`testing/`** —— `xiaozhi_core.testing`：零依赖 Fake 工具箱，覆盖每个 Port，是受支持的公共测试
  入口（tests 与 `examples/` 共用，下游也可复用）。默认值中性，剧情数据由构造参数注入。
- **`runtime/`** —— 装配层：`XiaozhiServer`（会话工厂，持装配模板）+ `SessionRuntime`（单会话装配结果）。

接入方三步启动：选/写 adapter → 配 `PromptComposer` 人设 → `create_session().run()`。

## 核心机制（改动前必须理解）

**事件驱动 pipeline**（`domain/pipeline.py` + `domain/stages/`）：每个 `Stage` 声明 `subscribes`
（订阅哪些事件类型），`Pipeline.attach` 把 stage 接到会话的 `EventBus`。**stage 在列表中的顺序 = 同一
事件上的分发顺序**，这是有意为之的契约——例如 `AudioOutputStage` 必须排在 `Intent/Llm` 之前，否则
`stt`/`tts:start` 下发时序会乱。增删 stage 即可定制（纯文本聊天去掉 Vad/Asr/AudioOutput；在 Llm 前
插敏感词 stage）。

**显式状态机**（`domain/state_machine.py`）：`IDLE→LISTENING→RECOGNIZING→THINKING→SPEAKING`。
`turn_id` 在进入 RECOGNIZING 时由 `SessionContext.begin_turn` 生成。状态转移订阅在 `SessionRuntime`
里**手动排在 pipeline 前后**：`VoiceStarted/VoiceStopped/AsrFinalized` 的转移先于 stage（保证 begin_turn
先发生），`TtsStopped→on_finished` 后于 stage（等 `AudioOutputStage` 下发 `tts:stop` 再收束本轮）。
改这些订阅顺序会破坏时序，慎重。

**陈旧轮次过滤**：所有轮次相关事件携带 `turn_id`。`Stage.is_stale(event)` 比对当前轮次，旧轮次事件
直接丢弃。`SessionRuntime.emit` 自动补齐 `session_id` 与当前 `turn_id`。

**强类型 Signal + 黑板**（`domain/signals.py`）：高级能力（情绪、韵律、说话人等）**不压平进文本**，而是
以 `Signal[T]` 强类型令牌流转于 `MetadataBag`（按令牌索引、写入时做 Pydantic 校验的黑板）。厂商原始标签
由 adapter 的防腐层（ACL）归一化进开放枚举（含 `OTHER`），核心永不见原始格式。注意 `PerceivedEmotion`
（用户情绪）与 `RenderEmotion`（要 TTS 表达的情绪）是两个独立类型，二者翻译（共情）由 LLM 完成、不进类型系统。

**装配期能力协商**（`domain/capabilities.py`，重点机制）：`negotiate()` 在装配时跑一次，决定 Signal 接线：
- *前向/软拉取*：上游 `provides()` 的 Signal，下游 `wants()` 或模板占位符可选取用，没有就降级。消费者
  常常不是端口本身（如 `asr.emotion` 的消费者是 `PromptComposer` 的 `{asr.emotion}` 占位符，LLM 对情绪无感知）。
- *反向/需求激活*：下游需要一个本不存在的 Signal（TTS 要 `prosody`）时，`DirectiveProvider`（如
  `SpeakTagDirective`）把 LLM 变成该 Signal 的派生生产者——注入提示词契约片段 + 解析流式输出首部。
  **只有下游真需要时才激活契约**，否则系统提示保持精简、零额外 token。任一端不支持 → 链路降级 + prompt 同步精简。

新增一个「高级能力」（情绪是范本）应复用这套机制：定义 Signal → adapter `provides`/`wants` 声明 → 必要时
写 `DirectiveProvider`，而不是把元数据塞进 prompt 字符串。

**Hook**（`hooks/`）：通过订阅 `EventBus` 上的生命周期事件（`TurnCompleted`、`SessionEnded` 等）做上报/
日志/埋点的旁路，不侵入 pipeline。`SessionRuntime(hooks=[...])` 注入。

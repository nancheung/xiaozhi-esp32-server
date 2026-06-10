# xiaozhi-core

小智服务端**领域核心**：六边形架构 + 事件驱动的语音对话编排引擎。
设计文档见 [`docs/architecture/hexagonal-design.md`](../../docs/architecture/hexagonal-design.md)。

> 技术栈：uv · Python 3.12 · Pydantic v2 · FastAPI/uvicorn（optional）· litellm（optional）· Ruff。
> **六边形纯度**：领域核心仅依赖 Pydantic + 标准库；框架性依赖全部封在 `adapters/`。

## 三步启动一个定制化小智服务端

```python
from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer

server = XiaozhiServer(
    adapters=AdapterSet(vad=..., asr=..., llm=..., tts=...),   # 1. 选/写 adapter
    composer=PromptComposer("你是温暖的陪伴助手。"),               # 2. 配人设 + hook
)
runtime = server.create_session(transport=...)                  # 3. run
await runtime.run()
```

## 目录

```
src/xiaozhi_core/
  domain/            # 领域核心（仅依赖 Pydantic + stdlib）
    signals.py       #   Signal[T] 强类型令牌 + MetadataBag 黑板 + 核心规范词汇
    events.py        #   入站/内部/生命周期事件
    event_bus.py     #   发布订阅总线（hook 的统一观测点）
    state_machine.py #   IDLE→LISTENING→RECOGNIZING→THINKING→SPEAKING 显式状态机
    capabilities.py  #   能力声明 + 装配期协商 + DirectiveProvider（LLM 派生生产）
    pipeline.py      #   Stage 基类 + 可插拔编排
    stages/          #   Vad / Asr / Intent / Llm / Tts / AudioOutput
    services/        #   切句 / 替换词滑窗 / 音频限流 / 提示词分层拼装
  ports/             # 端口契约（vad/asr/llm/tts/tools/memory/intent/vision/voiceprint/...）
  runtime/           # SessionRuntime / XiaozhiServer 装配
  adapters/          # litellm（extra: llm）/ FastAPI WebSocket（extra: server）
  testing/           # 零依赖 Fake 工具箱（覆盖每个 Port，供下游测试复用）
  hooks/             # logging_hook 等事件订阅旁路
```

## 测试工具箱（`xiaozhi_core.testing`）

随发行包一起发布的零依赖 Fake，覆盖每个 Port。下游为某个 Port 写真实 adapter 时，
可直接用它装配一条完整会话、对编排行为做断言，无需任何外部服务：

```python
from xiaozhi_core import AdapterSet, PromptComposer, XiaozhiServer
from xiaozhi_core.testing import FakeVad, FakeAsr, ScriptedLlm, EmotionalFakeTts

server = XiaozhiServer(
    adapters=AdapterSet(vad=FakeVad(), asr=FakeAsr(), llm=ScriptedLlm(), tts=MyRealTts()),
    composer=PromptComposer("你是助手。"),
)
```

Fake 默认值保持中性，具体场景（情绪、台词、说话人）由构造参数注入——参见
[`examples/minimal_server.py`](examples/minimal_server.py) 如何用它演示情绪全链路。

## 高级特性的通用机制（情绪示例）

元数据**不压平进文本**，以强类型 `Signal` 流转于轮次黑板；装配期协商决定接线：

- ASR 有情绪能力 → `provides({asr.emotion})`，识别后写黑板；
- 提示词模板占位符 `{asr.emotion}` 是软拉取消费点（消费者是模板，不是 LLM）；
- TTS 声明 `wants({prosody})` → 反向激活 LLM 输出契约 `<speak emotion=.. style=..>`，
  TTS 支持的情绪集合回灌进契约；
- 任一端不支持 → 对应链路自动降级，prompt 同步精简，零额外 token。

运行对比演示：

```bash
uv run python examples/minimal_server.py
```

## 开发

```bash
uv sync               # 安装（自动获取 Python 3.12）
uv run pytest         # 测试
uv run ruff check .   # lint
uv run ruff format .  # 格式化
```

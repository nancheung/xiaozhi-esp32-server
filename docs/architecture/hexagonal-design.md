# xiaozhi-server 六边形架构 + 事件驱动 设计

> 本文档对现有 `main/xiaozhi-server` 的运行机制做系统化提炼，并给出一套「领域核心 + 端口/适配器 + 事件总线 + 可插拔编排」的目标架构，用于指导把核心能力沉淀为可复用的包。
>
> 形态目标：先在**同仓库新增一个可被 import 的包**（建议 `main/xiaozhi-core`），孵化成熟后独立发布为 pip 包；现有 `main/xiaozhi-server` 后续作为该包的使用方。

---

## 背景与动机

`xiaozhi-server` 本质上已经是一个 **固定 pipeline 编排器（VAD→ASR→Intent→LLM→TTS→AudioOutput）+ 一组可插拔 provider**。各 provider 的抽象（`core/providers/*/base.py`）相当干净，但存在以下复用障碍：

- **编排逻辑、会话/轮次状态机、所有 hook（上报/情绪/日志/工具）全部硬编码**在 `core/connection.py`（约 1600 行）与 `core/handle/*` 中；
- provider 抽象与 `ConnectionHandler`（`conn`）强耦合：provider 直接读写 `conn.xxx`、直接 `conn.tts.tts_text_queue.put(...)`、直接调用 `sendAudioMessage(conn, ...)`；
- 状态机是隐式的（散落的布尔标志 + `sentence_id` 过滤），没有显式 State；
- hook 不是统一订阅机制，而是写死在流程里的函数调用。

目标：**提炼领域核心（编排 + 状态机 + 事件总线 + 公共算法）与端口契约**，让任意项目通过「选/写 adapter + 注册 hook + 配置 pipeline」最小代价启动一个定制化小智服务端。

---

## 一、现状关键事实

### 1. 端到端链路（4 级队列 + 回调链，全程边产边消）

```
设备 Opus(60ms帧)
 → ws.recv → conn.asr_audio_queue                         [connection.py _route_message]
 → asr_text_priority_thread → handleAudioMessage          [providers/asr/base.py; handle/receiveAudioHandle.py]
 → vad.is_vad(conn,audio)                                 [providers/vad/silero.py]
 → asr.receive_audio → handle_voice_stop（ASR+声纹 gather）
 → startToChat → handle_user_intent → conn.chat（线程池） [handle/intentHandler.py; connection.py]
 → llm.response[_with_functions]（流式 token）
 → tts.tts_text_queue.put(TTSMessageDTO FIRST/MIDDLE/LAST)
 → tts_text_priority_thread → _get_segment_text 切句 → to_tts_stream → text_to_speak → handle_opus
 → tts_audio_queue → _audio_play_priority_thread → sendAudioMessage
 → sendAudio + AudioRateController(60ms节流, 预缓冲5帧) → ws.send   [handle/sendAudioHandle.py; utils/audioRateController.py]
```

并发模型：**asyncio 事件循环 + 3 个 per-connection 守护线程（asr / tts-text / tts-audio）+ report 线程 + ThreadPoolExecutor(5)**；跨线程统一 `asyncio.run_coroutine_threadsafe(coro, conn.loop)`；线程间用 `queue.Queue` 解耦。

### 2. 会话 vs 轮次

- **Session** = 一条 WS 连接：`session_id`、`Dialogue()` 全量历史、provider 实例、队列、线程；断开时落库（标题 / 记忆）。
- **Turn** = 一次「用户说话 → 应答」：`sentence_id`（每次 `chat()` 生成）。**所有下游消息携带 sentence_id**，TTS / 发送端会丢弃 `sentence_id != conn.sentence_id` 的陈旧数据——这是打断不串音的核心机制。

### 3. 已有端口（provider base 抽象）

| 端口 | 抽象方法 | 工厂 |
|---|---|---|
| VAD | `is_vad(conn,data)->bool` | `utils/vad.create_instance` |
| ASR | `speech_to_text()`；+`receive_audio/handle_voice_stop/open_audio_channels` | `utils/asr` |
| LLM | `response()` / `response_with_functions()`（流式生成器） | `utils/llm` |
| TTS | `text_to_speak()`；+`to_tts_stream/open_audio_channels` | `utils/tts` |
| Memory | `save_memory()/query_memory()` | `utils/memory` |
| Intent | `detect_intent()` | `utils/intent` |
| Tools | `execute()/get_tools()/has_tool()`（多 executor 注册） | `unified_tool_manager` |
| VLLM | `response(question,image)` | `utils/vllm` |

加载约定：`config.selected_module.<MODULE>` → 动态 import `core/providers/<type>/<impl>` → 类名统一 `XxxProvider`。

### 4. 入站 / 出站事件与时序

- **入站**（JSON `type`，注册表 `textMessageHandlerRegistry`）：`hello`（必首发）/ `listen`(start|stop|detect) / `abort` / `iot` / `mcp` / `server` / `ping` + 二进制 Opus。
- **出站**：`hello` → `stt` → `tts:start` → `tts:sentence_start`（每句，带字幕）→ 二进制 Opus（60ms 节流）→ `tts:stop`。
- **打断**：`abort` → `clear_queues()` → `tts:stop`，靠 sentence_id 丢弃残留。

### 5. 隐式状态机

`IDLE → LISTENING → ASR → THINKING(LLM) → SPEAKING → IDLE`，标志位 `client_have_voice / client_voice_stop / client_abort / client_is_speaking / client_listen_mode(auto|manual)`；任意态 `abort` 回 `IDLE`。

### 6. Hook / 可观测点（目前硬编码）

`enqueue_asr_report`(1) / `enqueue_tts_report`(2) / `enqueue_tool_report`(3) → `report_queue` → report 线程 POST 管理 API；`auto_import_modules("plugins_func.functions")`；意图前置 `checkWakeupWords / check_direct_exit`；`get_emotion`；`logger.bind(tag=TAG)`。

### 7. 公共算法

- `AudioRateController`：虚拟播放位 + 事件驱动 60ms 节流 + 预缓冲 5 帧；
- `_get_segment_text`：标点滑窗切句，首句使用更宽松标点集以更快出声；
- `_match_stream_text`：跨流式分片的替换词滑窗匹配；
- `OpusEncoderUtils` / `decode_opus`；MQTT 网关 16 字节头。

---

## 二、目标架构：六边形 + 事件驱动

### 2.1 分层总览

```
┌──────────────────────── Driving Adapters（驱动侧/入站适配器） ────────────────────────┐
│  WebSocketTransport · MqttTransport · TestHarnessTransport（把帧/控制消息→入站事件）   │
└───────────────────────────────────────┬────────────────────────────────────────────┘
                                         │ Inbound Ports
┌────────────────────────────────────── 领域核心（不依赖任何具体实现） ──────────────────┐
│  EventBus（事件总线）                                                                  │
│  SessionContext / TurnContext（会话/轮次上下文，取代 conn 的状态聚合）                  │
│  DialogueStateMachine（显式状态机）                                                     │
│  PipelineOrchestrator（可插拔 stage 编排：VAD→ASR→Intent→LLM→TTS→AudioOutput）         │
│  Domain Services：SentenceSegmenter · AudioRateController · WordCorrector · OpusCodec   │
└───────────────────────────────────────┬────────────────────────────────────────────┘
                                         │ Driven Ports（端口契约）
┌──────────────────────────────────── Driven Adapters（被驱动侧/出站适配器） ────────────┐
│  VadAdapter(silero…) AsrAdapter(openai…) LlmAdapter TtsAdapter MemoryAdapter           │
│  IntentAdapter ToolAdapter ReportAdapter（现有 providers 包装即得）                     │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**设计铁律**：领域核心只依赖端口接口，不 import 任何具体 provider，不 import `websockets`。依赖方向永远从外向内。

### 2.2 端口契约（Ports）

**Driving Ports（入站）—— `TransportPort`**

- `async receive() -> AsyncIterator[RawInbound]`：产出原始入站（二进制音频帧 / 控制 JSON）。
- `async send_audio(frame: bytes)` / `async send_event(msg: dict)`：下发音频与控制消息。
- 适配器负责协议细节（WS / MQTT / 16 字节头），并把原始输入翻译成**入站事件**投递到 EventBus。

**Driven Ports（出站）—— 在现有 base 基础上「去 conn 化」**，把"读写 conn、直接操作队列、直接 send"的副作用抽走，端口只表达**纯能力**：

| Port | 接口（建议签名） | 与现状映射 |
|---|---|---|
| `VadPort` | `detect(state: VadState, pcm) -> VadResult(is_voice, voice_stopped)` | `silero.is_vad`，VAD 状态从 conn 移入 VadState |
| `AsrPort` | `transcribe(audio_stream) -> AsyncIterator[AsrChunk]` + `capabilities()`（STREAM/NON_STREAM/LOCAL） | `speech_to_text` / `receive_audio` |
| `LlmPort` | `stream(messages, tools=None) -> AsyncIterator[LlmDelta(text?, tool_call?)]` | `response` / `response_with_functions` |
| `TtsPort` | `synthesize(text) -> AsyncIterator[AudioChunk]` + `capabilities()`（DUAL/SINGLE/NON_STREAM） | `text_to_speak` / `to_tts_stream` |
| `MemoryPort` | `save(msgs, session_id)` / `query(q) -> str` | 原样 |
| `IntentPort` | `detect(history, text) -> IntentResult` | `detect_intent` |
| `ToolPort` | `list() -> [ToolDef]` / `execute(name, args) -> ActionResponse` | `UnifiedToolManager` |
| `ReportPort` | `report(kind, text, audio?, ts)` | `enqueue_*_report` 的去耦版 |

> 关键变化：**队列与线程不再是 provider 的职责**，而是编排器 / 运行时的职责。provider 退化为「纯流式能力提供者」，更易测、可独立复用。现有 `base.py` 里的 `open_audio_channels / *_priority_thread / handle_opus / tts_audio_queue` 等逻辑上移到领域核心的 `PipelineOrchestrator` + `AudioOutputStage`。

### 2.3 事件分类（Event Taxonomy）

统一 `Event` 基类（`type`、`session_id`、`turn_id?`、`ts`、`payload`），EventBus 支持 `publish(event)` 与 `subscribe(event_type, handler)`（多订阅者）。

**入站事件（设备 / Transport → 核心）**
`HelloReceived` · `AudioFrameReceived` · `ListenStateChanged(start|stop|detect)` · `AbortRequested` · `IotDescriptors` · `IotStates` · `McpMessage` · `Ping`

**领域内部事件（stage 之间流转）**
`VoiceStarted` · `VoiceStopped` · `AsrPartial` · `AsrFinalized` · `IntentDetected` · `LlmTokenStreamed` · `LlmToolCallRequested` · `ToolExecuted` · `TtsSentenceSegmented` · `TtsAudioChunkReady`

**出站事件（核心 → Transport → 设备）**
`SttResultEmitted` · `TtsStarted` · `TtsSentenceStarted` · `AudioChunkSent` · `TtsStopped` · `HelloAck`

**生命周期事件（hook 的主战场）**
`SessionStarted` · `SessionEnded` · `TurnStarted` · `TurnAborted` · `TurnCompleted` · `EmotionDetected`

**典型一轮事件时序**（与现状语义等价）：

```
ListenStateChanged(stop)/VoiceStopped
 → AsrFinalized → SttResultEmitted → TurnStarted → TtsStarted
 → IntentDetected →（LlmTokenStreamed × N | LlmToolCallRequested → ToolExecuted）
 → TtsSentenceSegmented → TtsSentenceStarted → TtsAudioChunkReady → AudioChunkSent × N
 → TtsStopped → TurnCompleted
打断：AbortRequested → TurnAborted →（清队列 + 丢弃旧 turn_id）→ TtsStopped
```

### 2.4 显式状态机（DialogueStateMachine）

把隐式标志位升级为显式状态 + 受控转移，转移即发事件：

```
States: IDLE, LISTENING, RECOGNIZING, THINKING, SPEAKING
IDLE        --ListenStart/HaveVoice-->            LISTENING
LISTENING   --VoiceStopped/ListenStop-->          RECOGNIZING
RECOGNIZING --AsrFinalized-->                     THINKING   (emit SttResult, TurnStarted)
THINKING    --first TtsSentence-->                SPEAKING
SPEAKING    --TtsStopped(queue drained)-->        IDLE       (emit TurnCompleted)
ANY         --AbortRequested-->                   IDLE       (emit TurnAborted)
```

`turn_id`（即现 `sentence_id`）由状态机在 `TurnStarted` 时生成，作为「陈旧数据过滤」的唯一依据，统一在 `AudioOutputStage` 与发送端比对。`SessionContext` 持有 `Dialogue`、provider 句柄、状态机、各队列；`TurnContext` 持有 `turn_id`、累积文本、abort 标志。

### 2.5 可插拔编排（PipelineOrchestrator）

- `Pipeline = [Stage]`，默认 `[VadStage, AsrStage, IntentStage, LlmStage, TtsStage, AudioOutputStage]`。
- 每个 `Stage` 声明：订阅哪些事件、产出哪些事件、依赖哪个 Port。Stage 内部封装现状那段「队列 + 线程 + 切句 + 节流」逻辑，但只通过端口与事件交互。
- 接入方可：删 stage（纯文本聊天去掉 Vad/Asr/AudioOutput）、插 stage（在 Llm 前插敏感词过滤 stage）、换 stage 实现。
- 公共算法作为**领域服务**注入 stage：`SentenceSegmenter`（=`_get_segment_text`）、`AudioRateController`（原样迁移）、`WordCorrector`（=`_match_stream_text` + 替换词）、`OpusCodec`。

### 2.6 统一 Hook 机制

取代散落的 `enqueue_*_report` / `get_emotion` / 日志：接入方通过 `bus.subscribe(EventType, handler)` 注册旁路逻辑。

- 内置 hook（默认装配，可关）：`ReportHook`（订阅 `AsrFinalized` / `TtsStopped` / `ToolExecuted` → ReportPort）、`LoggingHook`、`EmotionHook`、`MetricsHook`。
- 这样「日志观测点 / 事件接收下发点」成为**一等公民、可订阅、可替换**。

### 2.7 全流式如何保持

保留四级流式契约，但用端口的 `AsyncIterator` 表达，编排器在 stage 间用 `asyncio.Queue` 串联（替代裸线程 + `queue.Queue` + `run_coroutine_threadsafe` 的混合模型，统一到 asyncio；阻塞型 provider 用 `loop.run_in_executor` 包裹）。流式语义不变：ASR 边收边识别 → LLM 逐 token → TTS 标点切句首句提前出声（FIRST/MIDDLE/LAST 边界）→ AudioRateController 60ms 节流 + 预缓冲降首帧延迟。

---

## 三、包结构（同仓库孵化，面向未来独立发布）

```
main/xiaozhi-core/                 # 新包；不动现有 xiaozhi-server
  xiaozhi_core/
    domain/
      events.py                    # Event 基类 + 全部事件定义
      event_bus.py                 # EventBus（publish/subscribe）
      state_machine.py             # DialogueStateMachine
      context.py                   # SessionContext / TurnContext
      pipeline.py                  # Stage 基类 + PipelineOrchestrator
      stages/                      # VadStage/AsrStage/IntentStage/LlmStage/TtsStage/AudioOutputStage
      services/                    # SentenceSegmenter / AudioRateController / WordCorrector / OpusCodec
    ports/
      transport.py vad.py asr.py llm.py tts.py memory.py intent.py tools.py report.py
    runtime/
      server.py                    # XiaozhiServer：装配 transport+adapters+pipeline+hooks
      config.py                    # 配置 → 装配映射（沿用 selected_module 思路）
    hooks/                         # ReportHook/LoggingHook/EmotionHook/MetricsHook
  adapters/                        # 把现有 providers 包装为端口实现（薄封装）
  examples/minimal_server.py       # 最小可运行 demo（VAD+ASR+LLM+TTS）
  pyproject.toml                   # 为未来独立发布预留
```

### 接入方最小使用形态（设计目标，示意伪代码）

```python
server = XiaozhiServer(
    transport=WebSocketTransport(host, port),
    adapters=dict(vad=SileroVad(...), asr=OpenAiAsr(...), llm=OpenAiLlm(...), tts=EdgeTts(...)),
    pipeline=Pipeline.default(),            # 或自定义增删 stage
    hooks=[ReportHook(api), LoggingHook()], # 订阅事件做旁路
)
await server.run()
```

三步即可启动定制化小智服务端：**选 / 写 adapter → 配 pipeline + 注册 hook → run**。

---

## 四、现状 → 新架构 映射表

| 现状 | 新架构归属 |
|---|---|
| `connection.py` 的队列 / 线程 / 状态 / 编排 | 拆入 `PipelineOrchestrator` + 各 `Stage` + `SessionContext` / 状态机 |
| `core/providers/*/base.py` 抽象 | 提炼为 `ports/*`；实现下沉为 `adapters/*`（去 conn 化） |
| `tts/base.py` 的 `open_audio_channels/*_priority_thread/handle_opus` | 上移到 `TtsStage` + `AudioOutputStage` |
| `_get_segment_text` / `_match_stream_text` | `services/SentenceSegmenter` / `WordCorrector` |
| `AudioRateController` | `services/AudioRateController`（基本原样） |
| `handle/textMessageHandlerRegistry` + 各 handler | `WebSocketTransport` 解析 + 发布入站事件 |
| `sendAudioHandle` / `send_tts_message` / `send_stt_message` | `AudioOutputStage` + `Transport.send_event`（出站事件） |
| `enqueue_*_report` / report 线程 | `ReportPort` + `ReportHook`（订阅事件） |
| `intentHandler` 前置检查 | `IntentStage` + 可订阅的前置 hook |
| `sentence_id` 过滤陈旧数据 | `turn_id` 由状态机管理，统一在出站 stage 比对 |

---

## 五、孵化 / 演进路径（增量、低回归）

1. **阶段零**：本设计文档（当前）。
2. **阶段一**：在 `xiaozhi-core` 落地 `ports/` + `events/` + `EventBus` + 公共 `services/`（纯算法，零行为改动，可单测）。
3. **阶段二**：实现 `PipelineOrchestrator` 与各 `Stage`，用 `adapters/` 薄封装现有 provider；`examples/minimal_server.py` 跑通最小链路。
4. **阶段三**：让现有 `xiaozhi-server` 改为依赖该包（保持外部 WS 协议与配置兼容），逐步替换 `connection.py`。
5. **阶段四**：抽出 `pyproject.toml` 独立发布，`xiaozhi-server` 变为纯使用方。

---

## 六、设计自洽性核对清单

逐条对照现状确认语义不丢：

1. **链路完整性**：四级流式（asr→llm→tts-text→tts-audio）在新事件流中均有对应事件与 stage，无断点。
2. **打断正确性**：`AbortRequested → TurnAborted` + `turn_id` 过滤，能复现现状「清队列 + 丢弃旧轮次音频」的不串音行为。
3. **时序一致**：出站 `stt → tts:start → sentence_start → opus → tts:stop` 顺序与现状 `sendAudioHandle` 完全一致（设备协议不变，零破坏）。
4. **端口可替换性**：每个 Port 至少能映射 ≥2 个现有实现（如 TTS 的 NON_STREAM 与 DUAL_STREAM），证明抽象不过拟合单一实现。
5. **最小实现可行**：VAD + ASR + LLM + TTS 四端口 + 默认 pipeline 能描述一个可启动的最小服务端。

> 进入实现阶段后，端到端验证可用 `test/test_page.html`（谷歌浏览器连 `ws://<ip>:8000/xiaozhi/v1/`）跑一轮完整语音对话，比对新旧版本的出站消息序列与音频帧节奏（60ms）。

---

## 七、高级能力与横切关注点

前六节给出主链路与端口骨架。但把抽象做"通用"，最易漏的是这些**横切关注点**：视觉、上下文构建、跨阶段的高级元数据（情绪/语速/语言/说话人）、工具的静态与动态注册。本节给出它们在新架构中的统一落点。

### 7.1 视觉能力（VisionPort）

现状是**带外（out-of-band）**：HTTP 端点 `/mcp/vision/explain`（`core/api/vision_handler.py`）独立处理，设备直接 POST 图片+问题同步取结果；会话建立时通过 MCP `initialize.capabilities.vision` 把带 token 的 URL 下发设备。它**不走 WebSocket 对话流**。

新设计：
- `VisionPort`（driven port）= `describe(question, image) -> text`，现有 `VLLMProviderBase.response` 薄封装即得。
- `VisionHttpAdapter`（**第二个 driving 适配器**，与 `TransportPort` 并列）：独立 HTTP 入口，调用 `VisionPort`，与主语音 pipeline 并行解耦。
- 能力广播：`SessionStarted` 时由 device-MCP 握手 stage 发"vision 能力 + 鉴权 URL"出站事件。
- 可选 in-band：再把 `VisionPort` 包成 `vision.describe` 工具挂到 `ToolPort`（见 7.5），让 LLM 主动看图。两种触发模式共用同一 driven port。

### 7.2 上下文构建：PromptComposer 领域服务

现状散落在 `prompt_manager.py`（模板 + 时间/天气/位置/农历静态富化）、`dialogue.py::get_llm_dialogue_with_memory`（四段拼装 + `is_temporary`）、`connection.py::_inject_tool_call_fewshot/_initialize_memory`。其中**静态前缀刻意前置以命中 prefix cache**，时间/记忆/说话人每轮重注入。

新设计——纯领域编排，归入核心：
- 领域聚合 `Dialogue`（在 `SessionContext` 内，保留 `is_temporary` 区分真实历史 vs few-shot）。
- 领域服务 `PromptComposer`：分层拼装 **静态 cache 前缀 | few-shot | 动态块[时间/记忆/说话人] | 历史**（沉淀现 `get_llm_dialogue_with_memory` 为可测纯函数）。
- 出站端口：`MemoryPort`(query/save)、`ContextProviderPort`(天气/位置/dynamic_context)、`ProfilePort`(设备私有配置 / 初始 summary memory)。
- 生命周期映射：静态 prompt 在 `SessionStarted` 构建一次；时间/记忆/说话人在 `TurnStarted` 注入；记忆查询是 `LlmStage` 入口前一步（`MemoryPort.query(text)` → 注入动态块）。

### 7.3 高级特性的通用解法（核心）

**现状的根本问题**：元数据被**压平进文本字符串**（ASR 把 emotion/language/speaker 塞进 JSON 串 `enhanced_text`，到 `startToChat` 又拆出来只取 `content` 喂 LLM）——情绪/语速在进 LLM 前就丢了；LLM 情绪只能靠输出 emoji 反推；TTS 语速/音量是静态配置（`tts.py::convert_percentage_to_range`，`TTSMessageDTO` 无 prosody 字段）。三段断开。

#### 7.3.1 强类型表示：核心规范层 + 扩展能力层

- **核心规范层（封闭强类型）**：内置一小撮稳定模型 `Language / PerceivedEmotion / RenderEmotion / Prosody(emotion,style,rate,pitch,volume) / Speaker / Confidence`；核心 stage 直接编排。枚举用**开放枚举**（含 `OTHER` + 原始标签）防信息丢失。
- **扩展能力层（开放强类型）**：实现者独有能力（如 `doubao.word_timestamps`）用**带类型的 Signal 令牌**表示，`key` 命名空间化 `vendor.feature` 可带版本。
- **元数据容器**：不是 `dict[str, Any]`，而是**按 Signal 令牌索引的强类型异构容器** `MetadataBag.get(sig: Signal[T]) -> T | None`（type-indexed map）。它挂在事件上，也是 `TurnContext` 黑板。
- **归一化 ACL**：实现者原始输出（`"<|SAD|>"` / valence-arousal / 概率分布）由其 adapter 映射进核心规范类型，核心永不见原始格式；反向 TTS adapter 把 `RenderEmotion` 映射回自家参数。

> 注意：感知情绪 `asr.emotion : PerceivedEmotion` 与渲染情绪 `prosody.emotion : RenderEmotion` **是两个独立 Signal**，二者的翻译（共情逻辑）由 LLM 完成，不进类型系统。

#### 7.3.2 两种绑定方向（区别于简单的"交集"）

关键洞察：下游"消费"不是单一语义，存在两种绑定方向：

- **前向 / 软拉取（opt-in pull）**：某 Signal 上游碰巧产出，下游**可选**取用。消费者常常**不是端口本身**——例如 `asr.emotion` 的消费者是 `PromptComposer` 的模板占位符 `{asr.emotion}`，`LlmPort` 对情绪无感知。有就填、无则空。
- **反向 / 需求激活（demand-activated push）**：下游能力（TTS 情绪渲染）需要一个**本不存在**的 Signal，于是反向产生需求；编排器回溯找生产者——LLM 是 `prosody.*` 的**通用派生生产者**（`DirectiveProvider` = 提示词契约片段 + 输出解析器）。**只有当下游真的需要时，才把"输出 `<speak emotion style>`"的契约注入系统提示**，否则不激活、不浪费 token。

#### 7.3.3 装配期协商 + 运行期轨迹（情绪四态示例）

装配期（选定 adapter 后跑一次）：算 `produced = ⋃ provides()`、`wanted = consumes() ∪ wants()`；`produced ∩ wanted` 软拉取直接可用；`wanted − produced` 交给已知 `DirectiveProvider` 激活，并把 **TTS 支持的情绪集合回灌进 LLM 契约**（`可用情绪={gentle,excited,...}`，保证 LLM 只选 TTS 能渲染的）。输出"生效能力矩阵"供可观测。

运行期一轮：
```
1. VoiceStopped → AsrStage：FunASR 写 TurnContext{asr.emotion=SAD, asr.speech_rate=-0.3}   【案例1 高级能力，门控产出】
2. TurnStarted  → PromptComposer：模板 {asr.emotion} 填"难过"（无则留空，prompt 仍合法）       【案例2 消费方=模板，非LLM】
3. LlmStage：LLM 流式出文本；DirectiveProvider 解析 <speak emotion=gentle style=安慰>
            → 写 TurnContext.prosody；去标签文本进 TTS                                       【案例3 通用产出 + 案例4 反向要求】
4. TtsStage：读 TurnContext.prosody → TtsPort.synthesize(text, prosody)；中性 TTS 直接忽略      【案例4 高级渲染】
```

**降级矩阵**（四态独立可组合）：

| ASR 出情绪 | TTS 吃情绪 | 结果 |
|---|---|---|
| ✓ | ✓ | 用户情绪进 prompt 共情；LLM 被要求输出 prosody；TTS 渲染。全链路 |
| ✗ | ✓ | prompt 无用户情绪，但 TTS 要 → LLM 仍输出 prosody（纯文本推断）。TTS 有情绪 |
| ✓ | ✗ | LLM **不被要求**输出 prosody（prompt 精简）；asr.emotion 仍注入共情。两条线独立 |
| ✗ | ✗ | 纯文本链路，零额外开销 |

> 同一 ASR/LLM，仅换 TTS，系统提示里的"输出规范"段就自动增删——这就是"反向需求激活"与"软拉取"两种绑定共存的效果。`DirectiveProvider` 的输出契约对支持 JSON schema 的 LLM 可走 structured output 通道，与标签式在协商时择优（标签式通用但需剥流、structured 可靠但与逐 token 出声有张力）。

### 7.4 声纹识别（VoiceprintPort）

现状在 `ASRProviderBase.handle_voice_stop` 内 `asyncio.gather` 与 ASR 并行跑 `VoiceprintProvider.identify_speaker`，merge 进 `enhanced_text` 并注入 `<speakers_info>`。

新设计：声纹是 7.3 "元数据 enrichment"的一个**具体实例**——`VoiceprintPort.identify(pcm, session) -> Speaker`，在 `AsrStage` 内与 ASR 并行（保留 gather）或拆为 `SpeakerIdStage` 订阅 `VoiceStopped`；输出写 `TurnContext.speaker`（强类型，不再拼字符串），由 `PromptComposer` 消费注入动态块。与情绪/语速共用同一套机制，不再是特例。

### 7.5 工具（ToolPort：静态固定 + 会话级动态）

现状 `UnifiedToolManager` 按 `ToolType`(SERVER_PLUGIN / SERVER_MCP / DEVICE_IOT / DEVICE_MCP / MCP_ENDPOINT) 注册并路由；内置固定 = `@register_function` + `auto_import_modules`；会话级动态 = 设备 `iot` descriptors / `mcp` tools/list 运行时注册；`ActionResponse.Action`(RESPONSE/REQLLM/RECORD/ERROR) 驱动 LLM 循环。

新设计：
- `ToolPort` = `list() -> [ToolDef]` + `execute(name, args) -> ActionResponse`。
- **`CompositeToolPort`**（保留聚合+路由）聚合按**作用域**划分的 provider：
  - `StaticToolProvider`（进程级）：装饰器注册表 → 内置固定工具。`handle_exit_intent` 映射为领域动作（置 `close_after_chat` → 触发 `TurnCompleted`/`SessionEnded`）。
  - `SessionToolProvider`（会话级、动态）：订阅入站事件——`IotDescriptors` → 注册本会话 IoT 工具（如"调音量"）；`McpToolsListed` → 注册 device-MCP 工具。仅活在 `SessionContext` 生命周期内。
- `LlmStage` 每轮从 `ToolPort.list()` 取当前可用工具（自然含动态新增的设备工具）；工具调用产 `LlmToolCallRequested` → `ToolPort.execute` → `ToolExecuted`（`enqueue_tool_report` 变订阅 hook）。`ActionResponse.Action` 作为**领域契约**入核心，决定循环是否递归/注入/结束。

### 7.6 端口 / 事件 / 黑板 汇总（本节新增项）

| 类别 | 新增项 |
|---|---|
| Driven Ports | `VisionPort` · `VoiceprintPort` · `ToolPort`(CompositeToolPort) · `MemoryPort` · `ContextProviderPort` · `ProfilePort` |
| Driving Ports | `VisionHttpAdapter`（与 `TransportPort` 并列的第二入站适配器） |
| 入站事件 | `IotDescriptors` · `IotStates` · `McpToolsListed` · `VisionRequested` |
| 内部事件 | `SpeakerIdentified` · `LlmToolCallRequested` · `ToolExecuted` |
| TurnContext 黑板字段（Signal） | `asr.emotion` · `asr.speech_rate` · `language` · `speaker` · `prosody` · `vendor.*`(扩展) |
| 领域契约 | `ActionResponse.Action`(RESPONSE/REQLLM/RECORD/ERROR) · `Signal[T]` · `Capability/DirectiveProvider` |

---

## 八、技术框架与工程化选型（实现层）

抽象设计与技术栈解耦，但落地需钉死一套现代 Python 技术栈：**uv · Python 3.12 · Pydantic v2 · FastAPI/uvicorn · litellm · Ruff**。核心原则——**六边形纯度**：领域核心只依赖 `Pydantic v2 + 标准库`，框架性依赖（FastAPI/uvicorn、litellm）一律封在适配器层。

### 8.1 抽象 → 技术 映射

| 抽象概念 | 技术落地 | 位置（六边形分层） |
|---|---|---|
| 包管理 / monorepo / 锁定 | **uv**（workspace 管理 `xiaozhi-core` 与 `xiaozhi-server`，`uv.lock` 锁定，`uv run` 跑脚本） | 工程根 |
| 语言基线 | **Python 3.12**：PEP 695 泛型语法 `class Signal[T]` / `type` 别名、`asyncio.TaskGroup`（替代裸 gather 管理 stage 任务）、`@override` | 全局 |
| 事件 / DTO / Signal / 配置 强类型 | **Pydantic v2**：`Event`/`*MessageDTO`/`Prosody`/`Speaker` 为 `BaseModel`；入站消息用 **discriminated union**（`type` 字段判别）一次性解析校验；`MetadataBag` 值用 `TypeAdapter` 按 Signal schema 运行时校验；配置用 `pydantic-settings`（沿用 `selected_module` 思路） | **领域核心**（仅此一项框架依赖） |
| 入站适配器（设备接入 / 视觉 / OTA） | **FastAPI + uvicorn**：`WebSocketTransport` 用 FastAPI `WebSocket`；`VisionHttpAdapter`、OTA 用 FastAPI 路由；`uvicorn` ASGI 承载；`lifespan` 管理启动/关闭与 GC 管理器 | Driving Adapters |
| LLM 驱动适配器 | **litellm**：`LlmPort` 单一适配器统一 OpenAI/Ollama/Gemini/Coze/Dify… 的流式、function calling、structured output（`response_format`）；记忆 embedding 也走 litellm。**替代现有 `core/providers/llm/*` 一堆按厂商手写的实现** | LLM Driven Adapter |
| 代码质量 | **Ruff**：lint + format 合一（替代 black/flake8/isort）；`ruff check`/`ruff format` 进 CI 与 pre-commit | 工程根 |

### 8.2 工程骨架（pyproject + uv workspace）

```toml
# 根 pyproject.toml —— uv workspace
[tool.uv.workspace]
members = ["main/xiaozhi-core", "main/xiaozhi-server"]

[tool.ruff]
target-version = "py312"
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "RUF"]

# main/xiaozhi-core/pyproject.toml —— 领域核心：保持框架无关
[project]
name = "xiaozhi-core"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.7", "pydantic-settings>=2.3"]   # 仅此；不依赖 FastAPI/litellm

[project.optional-dependencies]
adapters = ["litellm>=1.40"]          # LLM 适配器按需装
server   = ["fastapi>=0.111", "uvicorn[standard]>=0.30"]   # 入站适配器/运行时
```

要点：
- **核心 `dependencies` 不含 FastAPI/litellm/uvicorn**，确保领域逻辑可在无网络、无 Web 框架下单测；适配器与运行时通过 optional-extras 引入，体现六边形依赖方向。
- `uv run --package xiaozhi-server xiaozhi-server` 启动；`uv run pytest`、`uv run ruff check` 统一入口。

### 8.3 关键技术落点示例

```python
# 领域核心：Python 3.12 PEP 695 泛型 + Pydantic v2（无框架依赖）
class Signal[T](BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str                      # "asr.emotion" / "prosody" / "vendor.feature"
    doc: str = ""

class AsrFinalized(BaseModel):    # 事件即强类型，metadata 走 Signal 索引容器
    type: Literal["asr.finalized"] = "asr.finalized"
    turn_id: str
    text: str

# LLM 适配器：litellm 统一多厂商 + 流式 + structured output（封在适配器层）
class LiteLlmAdapter:             # implements LlmPort
    async def stream(self, messages: list[dict], response_format=None):
        async for chunk in await litellm.acompletion(
            model=self.model, messages=messages, stream=True,
            response_format=response_format,           # 7.3 DirectiveProvider 的 structured 通道
        ):
            yield chunk.choices[0].delta

# 入站适配器：FastAPI WebSocket（封在 driving adapter 层）
@app.websocket("/xiaozhi/v1/")
async def ws(ws: WebSocket):
    await WebSocketTransport(ws).run()   # 解析帧/JSON → 发布入站事件到 EventBus
```

### 8.4 与现状的取舍

- **litellm 替代手写 LLM providers**：现有 9+ 个厂商实现收敛为一个适配器，新增模型零代码；`response_with_functions` 的 (text, tool_call) 流式语义由 litellm 统一提供。少数特殊厂商（Coze/Dify 这类非 OpenAI 协议的"工作流"型）仍可保留独立适配器实现 `LlmPort`，与 litellm 适配器并存。
- **FastAPI 替代裸 `websockets` + `aiohttp`**：WS、视觉 HTTP、OTA 三个入口统一到一个 ASGI 应用与一套鉴权依赖（`Depends`），`lifespan` 收口启动顺序。
- **asyncio 统一**：3.12 `TaskGroup` 管理 per-session 的 stage 任务，替代现状"裸线程 + `queue.Queue` + `run_coroutine_threadsafe`"混合模型（阻塞型本地推理用 `run_in_executor` 包裹）。
- **Pydantic v2 进核心是有意为之**：它只是数据建模与校验，不绑定 IO/框架，不破坏六边形纯度，却为事件/Signal/配置带来统一的强类型与运行时校验。

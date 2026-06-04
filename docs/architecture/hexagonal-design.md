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

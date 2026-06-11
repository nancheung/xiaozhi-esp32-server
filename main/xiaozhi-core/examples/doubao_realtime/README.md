# 豆包端到端实时对话样例

把火山引擎 **豆包 Realtime Dialog**（端到端语音模型：音频进 → 文本+音频出，ASR/LLM/TTS 云端融合）接到
xiaozhi-core 的事件驱动编排上。核心是一个自定义融合 Stage：

```
Pipeline([DoubaoRealtimeStage(client), AudioOutputStage()])
```

`DoubaoRealtimeStage` 替代默认管道的 Vad/Asr/Llm/Tts 四个 stage，把豆包事件映射进 core 事件总线
（450→VoiceStarted、459→VoiceStopped+AsrFinalized、SERVER_ACK→TtsAudioChunkReady、359→TtsStopped）；
`AudioOutputStage` 原样复用，负责出站协议时序（stt → tts:start → 音频 → tts:stop）与陈旧轮次过滤。

## 文件

| 文件 | 职责 |
|------|------|
| `config.py` | 全部配置（鉴权、TTS speaker、音频参数、`use_local_llm` 开关），迁移自官方 demo |
| `protocol.py` | 豆包二进制协议纯函数（4 字节 header + event id + gzip payload） |
| `client.py` | 异步 WebSocket 客户端（依赖 `websockets`） |
| `stage.py` | `DoubaoRealtimeStage`：豆包事件 ↔ core 事件桥接，含打断与本地 LLM 接管 |
| `echo_llm.py` | `EchoLlm`：本地 Fake LLM，回复「用户刚说了：」+原话 |
| `local_audio.py` | `MicTransport`：麦克风采集 / 扬声器播放（依赖 `pyaudio`） |
| `demo_mic.py` | 入口：装配 `XiaozhiServer` 跑麦克风实时对话 |

## 运行

1. 在 `config.py` 的 `ws_connect_config["headers"]` 填入火山引擎控制台的
   `X-Api-App-ID` 与 `X-Api-Access-Key`（开通 `volc.speech.dialog` 资源）。
2. 启动：

```bash
uv run --with websockets --with pyaudio python examples/doubao_realtime/demo_mic.py
```

对麦克风说话即可听到回复；说话可随时打断播报。

## 回复路径：两条独立分支 × 装配期自动协商

对应豆包的两个注入事件，按 core 的「装配期能力协商」理念接线——给了什么 adapter 就激活
什么链路，缺失自动降级：

| 分支 | 豆包机制 | 激活条件 | 行为 |
|------|---------|---------|------|
| **照念** | ChatTTSText(500) | `use_local_llm = True` | 本地 LLM 生成回复文本，豆包绕过云端 LLM、仅 TTS 原文照念。prompt 经 `PromptComposer` 拼装（与 core 默认链的 LlmStage 同构），装配了 `MemoryPort` 时记忆走 `{memory}` 占位符进本地 prompt |
| **知识注入** | ChatRAGText(502) | `use_local_llm = False` 且装配了 `MemoryPort` | 把 `memory.query()` 的记忆注入豆包，云端 LLM 据此**重新生成并润色**回答；可选先播 `comfort_text` 安抚话术掩盖检索耗时。记忆为空时自动降级纯端到端 |
| （降级） | — | 都不满足 | 纯云端端到端，豆包自答 |

两条注入路径期间，豆包注入前的自答音频被丢弃，直到 350 事件携带
`tts_type in {"chat_tts_text", "external_rag"}`（与官方 demo 的丢弃逻辑一致）。
同一个 `MemoryPort`、两条消费路径；把 `EchoLlm` 换成任意 `LlmPort` 实现即可接真实自有模型。

## 测试（全离线，无需凭据）

```bash
uv run pytest tests/test_doubao_realtime.py
```

协议层做二进制往返测试；编排层用 `FakeDoubaoClient` 回放事件序列，覆盖完整轮次、打断
（旧轮音频被 turn_id 过滤）、空识别静默取消、本地照念（含 composer/记忆拼装与历史落账）、
记忆注入（502 内容与音频丢弃）、注入降级、开场白直通等场景。

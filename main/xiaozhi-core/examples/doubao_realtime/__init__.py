"""豆包（火山引擎）Realtime Dialog 端到端模型 × xiaozhi-core 对接样例。

豆包是云端融合模型（音频进 -> 文本+音频出，ASR/LLM/TTS 不可拆分），不走
core 的默认四端口链；本样例用一个自定义融合 Stage（``DoubaoRealtimeStage``）
把豆包事件桥接进 core 的事件总线，复用 ``AudioOutputStage`` 的出站协议。
若后续出现第二家融合式供应商（OpenAI Realtime / Gemini Live），再把这里的
映射模式升格为正式的 RealtimeDialogPort。
"""

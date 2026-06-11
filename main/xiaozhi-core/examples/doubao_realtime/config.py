"""样例配置（迁移自官方 demo 的 config.py，全部配置集中在此，不走环境变量）。

运行前在 ``ws_connect_config["headers"]`` 填入火山引擎控制台的 App ID 与 Access Key。
"""

from __future__ import annotations

import uuid

# 回复路径有两条独立分支（装配期自动协商，对齐 core 设计理念）：
#
# 1. 照念分支（ChatTTSText 500）—— use_local_llm = True：
#    本地 LLM（EchoLlm 样例：「用户刚说了：」+原话）生成回复文本，豆包绕过
#    云端 LLM、仅做 TTS 原文照念。记忆（若装配）走 PromptComposer 的
#    {memory} 占位符进本地 prompt。
# 2. 知识注入分支（ChatRAGText 502）—— use_local_llm = False 且装配了 MemoryPort：
#    把 memory.query() 的记忆注入豆包，云端 LLM 据此**重新生成并润色**回答；
#    memory 未装配或查询为空时自动降级为纯端到端。
use_local_llm = False

# 知识注入分支：检索/重生成期间先播报的安抚话术；置 None 或空串则不发
comfort_text = "稍等，我想一下。"

# 演示记忆内容（InMemoryMemory 注入）；空串则不装配 memory、注入分支自动失活
memory_text = "用户叫南陈，住在北京，养了一只叫年糕的猫。"

ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": "",  # 填火山引擎控制台 App ID
        "X-Api-Access-Key": "",  # 填火山引擎控制台 Access Key
        "X-Api-Resource-Id": "volc.speech.dialog",  # 固定值
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",  # 固定值
        "X-Api-Connect-Id": str(uuid.uuid4()),
    },
}

start_session_req = {
    "asr": {
        "extra": {
            "end_smooth_window_ms": 1500,
        },
    },
    "tts": {
        "speaker": "zh_male_yunzhou_jupiter_bigtts",
        "audio_config": {
            "channel": 1,
            "format": "pcm",
            "sample_rate": 24000,
        },
    },
    "dialog": {
        "bot_name": "豆包",
        "system_role": "你使用活泼灵动的女声，性格开朗，热爱生活。",
        "speaking_style": "你的说话风格简洁明了，语速适中，语调自然。",
        "location": {
            "city": "北京",
        },
        "extra": {
            "strict_audit": False,
            "audit_response": "支持客户自定义安全审核回复话术。",
            "recv_timeout": 10,
            "input_mod": "audio",
        },
    },
}

# 开场白（event 300 SayHello）
say_hello_content = "你好，我是豆包，有什么可以帮助你的？"

# 麦克风采集：PCM 16k / 单声道 / 16bit；chunk 为每次读取的采样数（3200 帧 = 200ms）
input_audio_config = {
    "chunk": 3200,
    "channels": 1,
    "sample_rate": 16000,
    "sample_width": 2,  # paInt16
}

# 豆包 TTS 输出：PCM 24k / 单声道 / float32（format=pcm 时服务端返回 f32le）
output_audio_config = {
    "chunk": 3200,
    "channels": 1,
    "sample_rate": 24000,
    "sample_width": 4,  # paFloat32
}

"""适配器层：具体技术实现（litellm / FastAPI / 测试桩）。

框架性依赖只允许出现在这一层；litellm / fastapi 为 optional extras，
按需 ``from xiaozhi_core.adapters.litellm_llm import LiteLlmAdapter`` 引入。
"""

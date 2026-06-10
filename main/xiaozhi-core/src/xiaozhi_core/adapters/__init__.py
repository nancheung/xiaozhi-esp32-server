"""适配器层：具体技术实现（litellm / FastAPI / ...）。

框架性依赖只允许出现在这一层；litellm / fastapi 为 optional extras，
按需 ``from xiaozhi_core.adapters.litellm_llm import LiteLlmAdapter`` 引入。

零依赖的测试桩不在这里——它们是受支持的公共测试工具箱，见 ``xiaozhi_core.testing``。
"""

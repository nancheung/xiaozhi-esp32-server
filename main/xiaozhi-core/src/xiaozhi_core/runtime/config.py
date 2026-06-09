"""核心配置（pydantic-settings，环境变量前缀 ``XIAOZHI_``）。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XIAOZHI_")

    host: str = "0.0.0.0"
    port: int = 8000
    sample_rate: int = 24000
    frame_duration_ms: int = 60
    pre_buffer_frames: int = 5

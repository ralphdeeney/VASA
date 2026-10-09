from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VASA_", env_file=(".local/vasa.env", ".env"), extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6389/0")
    dependency_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    evolution_base_url: str = "http://127.0.0.1:4000"
    evolution_admin_key: SecretStr = SecretStr("")
    evolution_stream_key: SecretStr = SecretStr("")
    evolution_instance_key: SecretStr = SecretStr("")
    speech_model_root: Path = Path(".local/speech")
    tts_provider: Literal["ljspeech", "kokoro-int8"] = "ljspeech"
    kokoro_model_dir: Path = Path(".local/tts-evaluation/models/kokoro-int8")
    kokoro_num_threads: int = Field(default=1, ge=1, le=8)
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-sonnet-4-6"
    llm_primary: Literal["openai", "anthropic"] = "openai"
    webhook_config_path: Path | None = None
    max_active_calls: int = Field(default=2, ge=1, le=10)

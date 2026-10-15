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
    tts_provider: Literal["deepgram", "speechify", "kitten-micro", "kokoro-int8", "piper"] = (
        "deepgram"
    )
    deepgram_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="DEEPGRAM_API_KEY")
    deepgram_model: str = Field(default="aura-2-thalia-en", pattern=r"^aura-2-[a-z]{1,40}-en$")
    speechify_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="SPEECHIFY_API_KEY"
    )
    speechify_voice_id: str = Field(default="geffen_32", min_length=1, max_length=128)
    kitten_model_dir: Path = Path(".local/speech/kitten-micro")
    kitten_num_threads: int = Field(default=1, ge=1, le=8)
    kokoro_model_dir: Path = Path(".local/speech/kokoro-int8")
    kokoro_num_threads: int = Field(default=1, ge=1, le=8)
    stt_num_threads: int = Field(default=1, ge=1, le=8)
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_model: str = "claude-sonnet-4-6"
    llm_primary: Literal["openai", "anthropic"] = "openai"
    webhook_config_path: Path | None = None
    max_active_calls: int = Field(default=2, ge=1, le=10)

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VASA_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6389/0")
    dependency_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

import re
from email.errors import HeaderParseError
from email.headerregistry import AddressHeader, HeaderRegistry
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VASA_",
        env_file=(".local/vasa.env", ".env"),
        extra="ignore",
        hide_input_in_errors=True,
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

    # Additive SaaS features stay off until the separately reviewed migration is applied.
    saas_enabled: bool = False
    public_origin: str = ""
    smtp_host: str = Field(default="", max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    # Hosted SMTP may use the API key as BOTH username and password.
    smtp_username: SecretStr = Field(default=SecretStr(""), max_length=4096)
    smtp_password: SecretStr = Field(default=SecretStr(""), max_length=4096)
    smtp_sender: str = Field(default="", max_length=254)
    smtp_starttls: bool = True
    # Operator attestation only after verified sender + actual mailbox receipt.
    smtp_delivery_verified: bool = False
    contact_recipient: str = Field(default="", max_length=254)
    registration_approval_required: bool = False

    @field_validator("smtp_host")
    @classmethod
    def smtp_hostname(cls, value: str) -> str:
        if value and (
            len(value) > 253
            or any(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is None
                for label in value.split(".")
            )
        ):
            raise ValueError("SMTP host must be a hostname without credentials or a URL")
        return value.lower()

    @field_validator("smtp_username", "smtp_password")
    @classmethod
    def smtp_credential(cls, value: SecretStr) -> SecretStr:
        if any(ord(c) < 32 or ord(c) == 127 for c in value.get_secret_value()):
            raise ValueError("SMTP credential contains invalid control characters")
        return value

    @field_validator("smtp_sender")
    @classmethod
    def smtp_sender_address(cls, value: str) -> str:
        if not value:
            return value
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("SMTP sender must be one valid mailbox")
        try:
            header = HeaderRegistry()("From", value)
            if not isinstance(header, AddressHeader):
                raise ValueError()
            addresses = header.addresses
            if (
                header.defects
                or any(group.display_name is not None for group in header.groups)
                or len(addresses) != 1
                or not addresses[0].username
                or not addresses[0].domain
                or "@" not in addresses[0].addr_spec
            ):
                raise ValueError()
        except (ValueError, IndexError, HeaderParseError):
            raise ValueError("SMTP sender must be one valid mailbox") from None
        return value

    @field_validator("public_origin")
    @classmethod
    def canonical_origin(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (
                parsed.scheme == "http"
                and parsed.hostname not in {"localhost", "127.0.0.1", "testserver"}
            )
        ):
            raise ValueError("public_origin must be a canonical HTTPS origin")
        return value.rstrip("/")

    @field_validator("contact_recipient")
    @classmethod
    def contact_email(cls, value: str) -> str:
        if value and (
            value.count("@") != 1
            or not all(value.split("@"))
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("contact recipient must be an email address")
        return value

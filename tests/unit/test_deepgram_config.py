import pytest
from pydantic import ValidationError

from vasa.config import Settings


def test_deepgram_exact_secret_alias_and_optional_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VASA_TTS_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "component-deepgram-secret")
    settings = Settings(_env_file=None)
    assert settings.tts_provider == "kokoro-int8"
    assert settings.deepgram_api_key.get_secret_value() == "component-deepgram-secret"
    assert "component-deepgram-secret" not in repr(settings)
    assert "component-deepgram-secret" not in settings.model_dump_json()
    monkeypatch.setenv("VASA_TTS_PROVIDER", "deepgram")
    assert Settings(_env_file=None).tts_provider == "deepgram"
    assert settings.deepgram_model == "aura-2-thalia-en"


def test_untrusted_or_unsupported_deepgram_model_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VASA_DEEPGRAM_MODEL", "other-provider-model")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

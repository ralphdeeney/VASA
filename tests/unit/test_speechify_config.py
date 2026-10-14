import pytest

from vasa.config import Settings


def test_optional_speechify_key_uses_exact_environment_name_and_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VASA_TTS_PROVIDER", raising=False)
    monkeypatch.setenv("SPEECHIFY_API_KEY", "component-speechify-secret")
    settings = Settings(_env_file=None)
    assert settings.tts_provider == "kokoro-int8"
    assert settings.speechify_api_key.get_secret_value() == "component-speechify-secret"
    assert "component-speechify-secret" not in repr(settings)
    monkeypatch.setenv("VASA_TTS_PROVIDER", "speechify")
    assert Settings(_env_file=None).tts_provider == "speechify"

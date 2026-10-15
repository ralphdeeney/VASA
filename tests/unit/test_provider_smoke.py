from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from deploy import actions_vps as deploy
from vasa import provider_smoke as smoke
from vasa.contracts.models import AudioFrame

SECRET = "private-key-must-never-appear"


@pytest.fixture
def settings():
    return SimpleNamespace(
        openai_api_key=SecretStr(SECRET),
        deepgram_api_key=SecretStr(SECRET),
        llm_primary="openai",
        openai_model="configured-model",
        openai_base_url="https://gateway.example/v1",
        deepgram_model="aura-2-thalia-en",
    )


@pytest.mark.parametrize("provider", ["llm", "deepgram"])
async def test_success_uses_config_and_closes(settings, monkeypatch, provider):
    seen = {}

    class Client:
        def __init__(self, key, **kwargs):
            seen.update(key=key, **kwargs)

        async def respond(self, context, messages):
            yield {"type": "text", "text": SECRET}

        async def synthesize(self, text):
            yield AudioFrame(b"\x00" * 1920, 16000, 0, 0)

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(smoke, "OpenAIProvider", Client)
    monkeypatch.setattr(smoke, "DeepgramTTS", Client)
    lines = await smoke.probe(settings, provider)
    assert SECRET not in "\n".join(lines)
    assert lines[0].endswith("_SMOKE_OK")
    assert seen["closed"]
    assert seen["model"] == (
        settings.openai_model if provider == "llm" else settings.deepgram_model
    )
    if provider == "llm":
        assert seen["base_url"] == settings.openai_base_url
    else:
        assert "DEEPGRAM_AUDIO_MS=60.00" in lines


@pytest.mark.parametrize("provider", ["llm", "deepgram"])
@pytest.mark.parametrize("failure", [RuntimeError(SECRET), TimeoutError(SECRET)])
async def test_exceptions_redacted(settings, monkeypatch, provider, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(smoke, "OpenAIProvider", fail)
    monkeypatch.setattr(smoke, "DeepgramTTS", fail)
    lines = await smoke.probe(settings, provider)
    assert SECRET not in str(lines)
    assert "_SMOKE_FAILED=" in lines[0]


@pytest.mark.parametrize("provider", ["llm", "deepgram"])
async def test_missing_key_no_request(settings, monkeypatch, provider):
    settings.openai_api_key = settings.deepgram_api_key = SecretStr("")
    monkeypatch.setattr(smoke, "OpenAIProvider", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(smoke, "DeepgramTTS", lambda *a, **k: pytest.fail("network"))
    assert "missing_configuration" in (await smoke.probe(settings, provider))[0]


async def test_independent_failures(settings, monkeypatch, capsys):
    calls = []

    async def probe(config, provider):
        calls.append(provider)
        return ["LLM_SMOKE_FAILED=provider_error" if provider == "llm" else "DEEPGRAM_SMOKE_OK"]

    monkeypatch.setattr(smoke, "Settings", lambda: settings)
    monkeypatch.setattr(smoke, "probe", probe)
    assert await smoke.smoke() == 1
    assert calls == ["llm", "deepgram"]
    assert "DEEPGRAM_SMOKE_OK" in capsys.readouterr().out


async def test_settings_error_is_redacted(monkeypatch, capsys):
    def fail():
        raise ValueError(SECRET)

    monkeypatch.setattr(smoke, "Settings", fail)
    assert await smoke.smoke() == 1
    assert SECRET not in capsys.readouterr().out


def test_actions_filters_untrusted_output(monkeypatch, capsys):
    monkeypatch.setattr(
        deploy,
        "compose",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="\n".join(
                [
                    "LLM_SMOKE_OK",
                    "DEEPGRAM_SMOKE_OK",
                    "LLM_FIRST_TOKEN_MS=12.34",
                    SECRET,
                    "DEEPGRAM_TOTAL_MS=NaN",
                    "LLM_TOTAL_MS=12.34 " + SECRET,
                ]
            ),
            stderr=SECRET,
        ),
    )
    deploy.provider_smoke()
    output = capsys.readouterr().out
    assert SECRET not in output and "NaN" not in output
    assert "LLM_FIRST_TOKEN_MS=12.34" in output


def test_actions_requires_both_providers(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "compose",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="LLM_SMOKE_OK\n" + SECRET, stderr=SECRET
        ),
    )
    with pytest.raises(deploy.Refusal, match="smoke failed"):
        deploy.provider_smoke()


@pytest.mark.parametrize("llm_ok,deepgram_ok", [(False, True), (True, False), (False, False)])
def test_nonzero_smoke_preserves_safe_markers(monkeypatch, capsys, llm_ok, deepgram_ok):
    llm = "LLM_SMOKE_OK" if llm_ok else "LLM_SMOKE_FAILED=provider_error"
    dg = "DEEPGRAM_SMOKE_OK" if deepgram_ok else "DEEPGRAM_SMOKE_FAILED=timeout"
    malicious = [
        SECRET,
        "Authorization: Bearer " + SECRET,
        "https://example.test/?key=" + SECRET,
        "prompt=" + SECRET,
        "LLM_SMOKE_FAILED=" + SECRET,
        "LLM_SMOKE_OK " + SECRET,
        "DEEPGRAM_TOTAL_MS=NaN",
        "DEEPGRAM_SMOKE_FAILED=timeout " + SECRET,
    ]

    def subprocess_run(args, **kwargs):
        assert args[-5:] == ("exec", "-T", "vasa", "python", "scripts/live_provider_smoke.py")
        assert kwargs["capture_output"] and not kwargs["check"]
        return SimpleNamespace(returncode=1, stdout="\n".join([llm, dg, *malicious]), stderr=SECRET)

    monkeypatch.setattr(deploy.subprocess, "run", subprocess_run)
    with pytest.raises(deploy.Refusal, match="smoke failed"):
        deploy.provider_smoke()
    assert capsys.readouterr().out.splitlines() == [llm, dg]


@pytest.mark.parametrize(
    "code",
    [
        "missing_configuration",
        "invalid_configuration",
        "invalid_response",
        "timeout",
        "provider_error",
        "internal_error",
    ],
)
def test_approved_failure_codes(monkeypatch, capsys, code):
    marker = "LLM_SMOKE_FAILED=" + code
    monkeypatch.setattr(
        deploy,
        "compose",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout=marker + "\nDEEPGRAM_SMOKE_OK", stderr=SECRET
        ),
    )
    with pytest.raises(deploy.Refusal):
        deploy.provider_smoke()
    assert marker in capsys.readouterr().out


def test_nonzero_with_ok_markers_still_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="LLM_SMOKE_OK\nDEEPGRAM_SMOKE_OK", stderr=SECRET
        ),
    )
    with pytest.raises(deploy.Refusal):
        deploy.provider_smoke()
    assert SECRET not in capsys.readouterr().out


def test_unchecked_compose_capture_is_smoke_only():
    with pytest.raises(deploy.Refusal, match="restricted"):
        deploy.compose("up", "vasa", capture_smoke=True)


@pytest.mark.parametrize("kind", ["empty", "invalid_pcm", "remote_failure"])
async def test_audio_failure_closes_stream(settings, monkeypatch, kind):
    closed = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def synthesize(self, text):
            try:
                if kind == "remote_failure":
                    raise RuntimeError(SECRET)
                if kind == "invalid_pcm":
                    yield AudioFrame(b"\0" * 960, 8000, 0, 0)
            finally:
                closed.append("stream")

        async def aclose(self):
            closed.append("client")

    monkeypatch.setattr(smoke, "DeepgramTTS", Client)
    lines = await smoke.probe(settings, "deepgram")
    assert "SMOKE_FAILED=" in lines[0] and SECRET not in str(lines)
    assert closed == ["stream", "client"]


@pytest.mark.parametrize("mode", ["check", "bootstrap"])
def test_smoke_rejected_outside_deploy(monkeypatch, capsys, mode):
    monkeypatch.setattr(deploy.sys, "argv", ["controller", mode, "a" * 40, "true"])
    monkeypatch.setattr(deploy, "preflight", lambda: pytest.fail("must reject before SSH checks"))
    assert deploy.main() == 1
    assert "Smoke requires deploy mode" in capsys.readouterr().err

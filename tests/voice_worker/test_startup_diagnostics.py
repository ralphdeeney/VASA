import sys
from uuid import uuid4

import pytest

from tests.voice_worker.test_preflight import PreflightRig
from vasa import voice_worker as worker
from vasa.runtime import RuntimeConfig

PRIVATE = (
    "secret-api-key Authorization: Bearer secret-header private-prompt private-caller "
    "https://user:password@example.invalid/private provider-response-body"
)


class PrivateFailure(RuntimeError):
    def __str__(self) -> str:
        raise AssertionError("Exception must never be rendered")


@pytest.mark.parametrize(
    "stage",
    [
        "settings",
        "speech_verify",
        "database",
        "resolve_instances",
        "redis",
        "evolution_client",
        "knowledge_init",
        "instance_status",
        "persisted_config",
        "tools_config",
        "llm_provider",
        "stt_init",
        "tts_init",
        "runtime_init",
    ],
)
async def test_worker_reports_exact_startup_stage_without_exception_details(
    monkeypatch, capsys, stage
):
    from vasa.knowledge import service
    from vasa.tools import webhooks_config

    rig = PreflightRig(monkeypatch)
    error = PrivateFailure(PRIVATE)

    def fail(*args, **kwargs):
        raise error

    async def async_fail(*args, **kwargs):
        raise error

    if stage == "speech_verify":
        rig.model_failure = error
    elif stage == "redis":
        monkeypatch.setattr(worker.Redis, "from_url", fail)
    elif stage == "instance_status":
        monkeypatch.setattr(worker.EvolutionCalls, "status", async_fail)
    elif stage == "resolve_instances":
        monkeypatch.setattr(worker, "resolve_instance", async_fail)
    elif stage == "persisted_config":
        monkeypatch.setattr(worker, "persisted_config", async_fail)
    elif stage == "knowledge_init":
        monkeypatch.setattr(service, "KnowledgeService", fail)
    elif stage == "tools_config":
        monkeypatch.setattr(webhooks_config, "load_webhooks", fail)
    else:
        name = {
            "settings": "Settings",
            "database": "Database",
            "evolution_client": "EvolutionCalls",
            "llm_provider": "OpenAIProvider",
            "stt_init": "SherpaSTT",
            "tts_init": "SherpaTTS",
            "runtime_init": "ConversationRuntime",
        }[stage]
        monkeypatch.setattr(worker, name, fail)
    with pytest.raises(PrivateFailure) as caught:
        await worker.run("private-operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert caught.value is error
    output = capsys.readouterr()
    assert f"VOICE_STARTUP_STAGE={stage}" in output.out
    assert f"VOICE_STARTUP_FAILED={stage}" in output.out
    assert "VOICE_RUNTIME_FAILED=" not in output.out
    assert PRIVATE not in output.out + output.err
    for private in PRIVATE.split():
        assert private not in output.out + output.err
    markers = [line for line in output.out.splitlines() if line.startswith("VOICE_")]
    assert sum(line.startswith("VOICE_STARTUP_ERROR=") for line in markers) == 1
    assert all(
        line.split("=", 1)[1] in worker.VOICE_STAGES | worker.VOICE_ERRORS for line in markers
    )


@pytest.mark.parametrize(
    "error_type,code", [(ValueError, "invalid_configuration"), (KeyError, "internal_error")]
)
def test_cli_reports_provider_configuration_failure_once_and_hides_response_body(
    monkeypatch,
    capsys,
    error_type,
    code,
):
    PreflightRig(monkeypatch)

    def fail(*args, **kwargs):
        raise error_type(PRIVATE)

    monkeypatch.setattr(worker, "OpenAIProvider", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "voice-worker",
            "--email",
            "private-operator@example.invalid",
            "--instance",
            str(uuid4()),
            "--once",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        worker.main()
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert output.out.count("VOICE_STARTUP_FAILED=llm_provider") == 1
    assert f"VOICE_STARTUP_ERROR={code}" in output.out
    assert "Voice worker unavailable" in output.err
    assert PRIVATE not in output.out + output.err
    assert "Traceback" not in output.out + output.err


async def test_failure_after_readiness_is_runtime_failure(monkeypatch, capsys):
    PreflightRig(monkeypatch)

    async def fail(*args, **kwargs):
        raise PrivateFailure(PRIVATE)

    monkeypatch.setattr(worker, "supervise_calls", fail)
    with pytest.raises(PrivateFailure):
        await worker.run("private-operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    output = capsys.readouterr().out
    assert "VOICE_STARTUP_STAGE=ready" in output
    assert "VOICE_RUNTIME_FAILED=supervision" in output
    assert "VOICE_STARTUP_FAILED=" not in output
    assert PRIVATE not in output


async def test_post_ready_reconciliation_failure_stays_runtime_failure(monkeypatch, capsys):
    rig = PreflightRig(monkeypatch)
    instance = uuid4()

    async def mappings(*args):
        return [(rig.context, instance, rig.external)]

    async def fail_persisted(*args, **kwargs):
        raise PrivateFailure(PRIVATE)

    async def supervise(*args, **kwargs):
        monkeypatch.setattr(worker, "persisted_config", fail_persisted)
        await kwargs["reconcile"]()

    monkeypatch.setattr(worker, "resolve_all", mappings)
    monkeypatch.setattr(worker, "supervise_calls", supervise)
    with pytest.raises(PrivateFailure):
        await worker.run_all(RuntimeConfig())
    output = capsys.readouterr().out
    assert "VOICE_STARTUP_STAGE=ready" in output
    assert "VOICE_RUNTIME_STAGE=" not in output
    assert "VOICE_RUNTIME_FAILED=persisted_config" in output
    assert "VOICE_STARTUP_FAILED=" not in output
    assert PRIVATE not in output


def test_reporter_cannot_emit_arbitrary_stage_values_or_exception_strings(capsys):
    report = worker.StartupReport(current=PRIVATE)
    report.failure(PrivateFailure(PRIVATE))
    output = capsys.readouterr().out
    assert "VOICE_STARTUP_FAILED=settings" in output
    assert PRIVATE not in output

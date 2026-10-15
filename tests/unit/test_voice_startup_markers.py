from types import SimpleNamespace

import pytest

from deploy import actions_vps as controller
from vasa import voice_worker

PRIVATE = "secret-token Authorization: Bearer private-key private-prompt private-caller"


def test_worker_and_actions_marker_allowlists_match() -> None:
    assert controller.VOICE_STAGES == voice_worker.VOICE_STAGES
    assert controller.VOICE_ERRORS == voice_worker.VOICE_ERRORS


@pytest.mark.parametrize(
    "line",
    [
        PRIVATE,
        "VOICE_STARTUP_FAILED=llm_provider " + PRIVATE,
        "prefix VOICE_STARTUP_STAGE=settings",
        "VOICE_STARTUP_ERROR=" + PRIVATE,
        "VOICE_STARTUP_STAGE=https://user:password@example.invalid",
        "\x1b[31mVOICE_STARTUP_FAILED=settings",
        "VOICE_STARTUP_FAILED=llm_provider\r" + PRIVATE,
        "VOICE_STARTUP_STAGE=settings\u2028" + PRIVATE,
        "VOICE_STARTUP_FAILED=llm_provider" + "x" * 1000,
        '{"VOICE_STARTUP_FAILED":"settings","body":"' + PRIVATE + '"}',
        "VOICE_RUNTIME_ERROR=arbitrary_exception_body",
    ],
)
def test_marker_parser_discards_nonexact_and_secret_bearing_lines(line) -> None:
    assert controller.voice_marker_lines(line) == []


def test_marker_parser_emits_only_fixed_values_and_bounds_history() -> None:
    logs = ("VOICE_STARTUP_STAGE=settings\n" + PRIVATE + "\n") * 200
    logs += "VOICE_STARTUP_FAILED=llm_provider\nVOICE_STARTUP_ERROR=invalid_configuration\n"
    markers = controller.voice_marker_lines(logs)
    assert len(markers) == 64
    assert markers[-2:] == [
        "VOICE_STARTUP_FAILED=llm_provider",
        "VOICE_STARTUP_ERROR=invalid_configuration",
    ]
    assert not any(PRIVATE in line for line in markers)


@pytest.mark.parametrize("runtime", [False, True])
def test_health_rejects_sanitized_failure_even_when_ready_marker_precedes_it(monkeypatch, runtime):
    prefix = "VOICE_RUNTIME" if runtime else "VOICE_STARTUP"
    logs = controller.READY_MARKER + f"\n{prefix}_FAILED=llm_provider\n"
    monkeypatch.setattr(controller, "read_container_logs", lambda *args, **kwargs: logs)
    with pytest.raises(controller.Refusal, match="Voice lifecycle failure markers"):
        controller.log_health("f" * 64, "2026-10-15T00:00:00Z", worker=True)


def test_actions_diagnostics_extract_across_restarts_without_dumping_logs(monkeypatch, capsys):
    calls = []
    started = "2026-10-15T00:00:00Z"
    monkeypatch.setattr(
        controller,
        "container",
        lambda service: (
            ("f" if service == "voice" else "e") * 64,
            {"state": {"Status": "restarting", "StartedAt": started}, "restarts": 11},
        ),
    )

    def subprocess_run(args, **kwargs):
        calls.append(args)
        # Return raw untrusted stdout+stderr; only canonical markers may escape.
        return SimpleNamespace(
            returncode=0,
            stdout="VOICE_STARTUP_STAGE=llm_provider\nVOICE_STARTUP_FAILED=llm_provider\n"
            + PRIVATE,
            stderr="VOICE_STARTUP_ERROR=invalid_configuration\n" + PRIVATE,
        )

    monkeypatch.setattr(controller.subprocess, "run", subprocess_run)
    controller.diagnostics()
    output = capsys.readouterr()
    assert "VOICE_STARTUP_FAILED=llm_provider" in output.out
    assert "VOICE_STARTUP_ERROR=invalid_configuration" in output.out
    assert PRIVATE not in output.out + output.err
    for private in PRIVATE.split():
        assert private not in output.out + output.err
    assert ["docker", "logs", "--tail", "200", "f" * 64] in calls


def test_post_rollback_diagnostics_never_emit_old_image_startup_markers(monkeypatch, capsys):
    monkeypatch.setattr(
        controller,
        "container",
        lambda service: (
            "f" * 64,
            {"state": {"Status": "running", "StartedAt": "old-attempt"}, "restarts": 0},
        ),
    )
    monkeypatch.setattr(
        controller,
        "read_container_logs",
        lambda *args, **kwargs: "VOICE_STARTUP_FAILED=speech_verify\n" + PRIVATE,
    )
    controller.diagnostics(report_voice_markers=False)
    output = capsys.readouterr().out
    assert "VOICE_STARTUP_FAILED=" not in output
    assert PRIVATE not in output

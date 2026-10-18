"""Private acceptance orchestration never streams child output or credentials."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_live_saas_acceptance as runner


def test_actions_only(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert runner.main() == 1
    assert capsys.readouterr().out == "LIVE_SAAS_RUNNER_FAILED=actions_required\n"


@pytest.mark.parametrize(
    "failure", ["none", "cleanup_pending", "prepare", "browser", "cleanup", "exception"]
)
def test_private_inputs_cleanup_and_output_allowlist(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    secret = "never-print-secret-body-Authorization"
    operations = []
    directories = []

    def execute(command, environment, timeout):
        path = Path(environment["VASA_LIVE_ACCEPTANCE_FILE"])
        payload = json.loads(path.read_text())
        assert path.stat().st_mode & 0o077 == 0
        assert path.parent.stat().st_mode & 0o077 == 0
        if payload["action"] == "cleanup_pending":
            assert payload == {"action": "cleanup_pending"}
        else:
            assert len(payload["password"]) >= 32
            assert payload["password"] not in " ".join(command)
        directories.append(path.parent)
        if command[0] == "node":
            operations.append("browser")
            assert command == ["node", "scripts/live_saas_acceptance.cjs"]
            result = Path(environment["VASA_LIVE_ACCEPTANCE_RESULT"])
            result.write_text(json.dumps({"sessions": ["a" * 43, secret]}))
            if failure == "exception":
                raise RuntimeError(secret)
            markers = ["LIVE_SAAS_PASS=" + stage for stage in runner.PASS_STAGES]
            markers += ["LIVE_SAAS_EMAIL_FLOWS=blocked_smtp", "LIVE_SAAS_ACCEPTANCE_PARTIAL_OK"]
            markers += [secret, "LIVE_SAAS_FAILED=" + secret, "LIVE_SAAS_PASS=made-up"]
            return SimpleNamespace(returncode=int(failure == "browser"), stdout="\n".join(markers))
        action = payload["action"]
        operations.append(action)
        if action == "cleanup":
            assert payload["sessions"] == (
                [] if failure in {"prepare", "cleanup_pending"} else ["a" * 43]
            )
        code = int(failure == action)
        marker = "LIVE_SAAS_FIXTURE_" + action.upper() + "_OK"
        return SimpleNamespace(returncode=code, stdout=marker + "\n" + secret)

    monkeypatch.setattr(runner, "execute", execute)
    assert runner.main() == int(failure != "none")
    output = capsys.readouterr().out
    assert secret not in output
    assert "made-up" not in output
    assert operations[-1] == "cleanup"
    assert "cleanup_pending" in operations
    assert ("prepare" in operations) == (failure != "cleanup_pending")
    if failure == "cleanup_pending":
        assert "browser" not in operations
    assert all(not path.exists() for path in directories)
    assert ("LIVE_SAAS_ACCEPTANCE_PARTIAL_OK" in output) == (failure == "none")


def test_malicious_markers_are_not_accepted():
    assert (
        runner.safe_browser_markers(
            "LIVE_SAAS_PASS=login_session_persistence Authorization=secret\n"
            "LIVE_SAAS_FAILED=arbitrary-secret\n"
            "LIVE_SAAS_ACCEPTANCE_PARTIAL_OK secret\n"
        )
        == set()
    )


def test_child_timeout_is_sanitized(monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private-secret", 1, output="private-body")

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    result = runner.execute(["node", "script"], {}, 1)
    assert result.returncode == 1 and result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize(
    "body,expected",
    [
        ("ssh: private-host: Connection refused Authorization: secret", "connection_refused"),
        ("SSH host-key scan failed; private-host private-key", "host_scan"),
        ("Private acceptance payload construction failed. private-body", "private_payload"),
        ("Host trust is missing or mismatched private-host", "host_trust"),
        ("private-api-key unexpected secret exception", "unclassified"),
    ],
)
def test_failed_bridge_prints_only_fixed_safe_category(monkeypatch, capsys, body, expected):
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="private-body", stderr=body),
    )
    result = runner.execute(["bash", "deploy/actions-ssh.sh"], {}, 10)
    assert result.returncode == 1
    assert capsys.readouterr().out == "LIVE_SAAS_BRIDGE_FAILED=" + expected + "\n"


def test_successful_bridge_does_not_echo_child_output(monkeypatch, capsys):
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="private-credential", stderr="private-response"
        ),
    )
    runner.execute(["bash", "deploy/actions-ssh.sh"], {}, 10)
    assert capsys.readouterr().out == ""


def test_only_fixed_fixture_diagnostics_survive(capsys):
    runner.emit_fixture_failures(
        "LIVE_SAAS_TASK_FAILED=health\n"
        "LIVE_SAAS_FIXTURE_STAGE=cleanup_sessions\n"
        "LIVE_SAAS_FIXTURE_SQLSTATE=23503\n"
        "LIVE_SAAS_FIXTURE_ERROR=internal_error Authorization=secret\n"
        "LIVE_SAAS_TASK_FAILED=secret\n"
        "raw-private-body\n"
    )
    assert capsys.readouterr().out.splitlines() == [
        "LIVE_SAAS_TASK_FAILED=health",
        "LIVE_SAAS_FIXTURE_STAGE=cleanup_sessions",
        "LIVE_SAAS_FIXTURE_SQLSTATE=23503",
    ]


@pytest.mark.parametrize("recycle", ["true", "false"])
@pytest.mark.parametrize("pending_success", [True, False])
def test_cleanup_only_never_provisions_or_runs_browser(
    tmp_path, monkeypatch, capsys, recycle, pending_success
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("VASA_SAAS_CLEANUP_ONLY", "true")
    monkeypatch.setenv("VASA_API_POOL_RECYCLE", recycle)
    calls = []

    def execute(command, environment, timeout):
        calls.append(command)
        assert command == ["bash", "deploy/actions-ssh.sh"]
        assert environment["VASA_SAAS_CLEANUP_ONLY"] == "true"
        assert environment["VASA_API_POOL_RECYCLE"] == recycle
        document = json.loads(Path(environment["VASA_LIVE_ACCEPTANCE_FILE"]).read_text())
        assert document == {"action": "cleanup_pending"}
        return SimpleNamespace(
            returncode=0 if pending_success else 1,
            stdout="VASA_API_POOL_RECYCLE_OK\nLIVE_SAAS_FIXTURE_CLEANUP_PENDING_OK\nprivate-secret-body",
        )

    monkeypatch.setattr(runner, "execute", execute)
    assert runner.main() == (0 if pending_success else 1)
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "private-secret" not in output
    assert "VASA_API_POOL_RECYCLE_OK" in output
    assert ("LIVE_SAAS_CLEANUP_ONLY_OK" in output) == pending_success
    assert "LIVE_SAAS_ACCEPTANCE_PARTIAL_OK" not in output


@pytest.mark.parametrize(
    "cleanup,recycle", [("false", "true"), ("yes", "false"), ("false", "yes"), ("TRUE", "true")]
)
def test_invalid_cleanup_recycle_configuration_fails_before_ssh(
    monkeypatch, capsys, cleanup, recycle
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("VASA_SAAS_CLEANUP_ONLY", cleanup)
    monkeypatch.setenv("VASA_API_POOL_RECYCLE", recycle)

    def forbidden(*args, **kwargs):
        raise AssertionError("must_not_execute_ssh")

    monkeypatch.setattr(runner, "execute", forbidden)
    assert runner.main() == 1
    assert capsys.readouterr().out == "LIVE_SAAS_RUNNER_FAILED=configuration\n"

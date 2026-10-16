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


@pytest.mark.parametrize("failure", ["none", "prepare", "browser", "cleanup", "exception"])
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
            assert payload["sessions"] == ([] if failure == "prepare" else ["a" * 43])
        code = int(failure == action)
        marker = "LIVE_SAAS_FIXTURE_" + action.upper() + "_OK"
        return SimpleNamespace(returncode=code, stdout=marker + "\n" + secret)

    monkeypatch.setattr(runner, "execute", execute)
    assert runner.main() == int(failure != "none")
    output = capsys.readouterr().out
    assert secret not in output
    assert "made-up" not in output
    assert operations[-1] == "cleanup"
    assert "prepare" in operations
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

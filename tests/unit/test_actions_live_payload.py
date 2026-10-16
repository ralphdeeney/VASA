import json

import pytest

from deploy.actions_live_payload import build


def private_input(tmp_path, **changes):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps({"action": "prepare", "run": "a" * 32, "password": "secret" * 8, **changes})
    )
    path.chmod(0o600)
    return path


def test_payload_private_stdin_has_no_secret_command_argument(tmp_path):
    path = private_input(tmp_path)
    payload = build(path)
    compile(payload, "private_payload", "exec")
    assert "input_text=json.dumps(data)" in payload
    assert '"vasa_actions_acceptance"' in payload
    assert "result.stdout.strip() != expected" in payload
    assert "print(expected" in payload
    assert "print(result.stdout" not in payload


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o777])
def test_payload_refuses_public_private_input(tmp_path, mode):
    path = private_input(tmp_path)
    path.chmod(mode)
    with pytest.raises(ValueError):
        build(path)


def test_payload_refuses_symlink(tmp_path):
    path = private_input(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        build(link)


@pytest.mark.parametrize("change", [{"action": "deploy"}, {"run": "arbitrary"}, {"key": "secret"}])
def test_payload_refuses_unapproved_task(tmp_path, change):
    with pytest.raises(ValueError):
        build(private_input(tmp_path, **change))


@pytest.mark.parametrize("action", ["cleanup", "cleanup_pending", "prepare"])
def test_cleanup_cannot_be_blocked_by_historical_health_logs(tmp_path, monkeypatch, capsys, action):
    from pathlib import Path

    path = private_input(tmp_path, action=action)
    if action == "cleanup_pending":
        path.write_text(json.dumps({"action": action}))
    original = Path.read_text
    controller = """
import re
from types import SimpleNamespace
def preflight(): pass
def health(): raise ValueError("secret historical log")
def container(name): return ("owned-container", None)
def capture(*args, input_text, **kwargs):
    import json
    action = json.loads(input_text)["action"]
    return SimpleNamespace(returncode=0, stdout="LIVE_SAAS_FIXTURE_"+action.upper()+"_OK")
"""

    def read_text(self, *args, **kwargs):
        return (
            controller
            if self.as_posix() == "deploy/actions_vps.py"
            else original(self, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "read_text", read_text)
    payload = build(path)
    if action == "prepare":
        with pytest.raises(SystemExit):
            exec(payload, {})
        assert capsys.readouterr().out == "LIVE_SAAS_TASK_FAILED=health\n"
    else:
        exec(payload, {})
        assert capsys.readouterr().out == "LIVE_SAAS_FIXTURE_" + action.upper() + "_OK\n"

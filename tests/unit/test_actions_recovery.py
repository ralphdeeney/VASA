from types import SimpleNamespace

import pytest

from deploy import actions_vps as deployment


def test_investigation_preserves_dirty_files_and_discards_secret_material(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    (tmp_path / ".local").mkdir()
    secret = "DO-NOT-PRINT-private-body-password"
    (tmp_path / ".local/llm.env").write_text("VASA_SMTP_PASSWORD=" + secret)
    (tmp_path / "deploy").mkdir()
    source = tmp_path / "deploy/compose.yaml"
    source.write_text(secret)
    before = source.read_bytes()
    commands = []

    def git(*args):
        commands.append(args)
        if args[0] == "ls-tree":
            return "deploy/compose.yaml"
        if args[0] == "diff":
            return "+" + secret + "\n-old-private-content"
        if args[0] == "log":
            return "a" * 40
        if args[0] == "worktree":
            return "worktree /opt/vasa\n"
        raise AssertionError("Unexpected command")

    monkeypatch.setattr(deployment, "git", git)
    monkeypatch.setattr(
        deployment,
        "capture",
        lambda *a: SimpleNamespace(
            returncode=0, stdout=" M deploy/compose.yaml\0?? " + secret + "\0"
        ),
    )
    monkeypatch.setattr(
        deployment, "config", lambda: (_ for _ in ()).throw(deployment.Refusal("private-error"))
    )
    monkeypatch.setattr(
        deployment,
        "compose",
        lambda *a, **k: (
            "VPS_LOGIN_PROBE_REASON=invalid_origin\n"
            + secret
            + "\nVPS_RUNTIME_BINDING_VASA_SMTP_PASSWORD=present"
        ),
    )
    deployment.investigate()
    output = capsys.readouterr().out
    assert secret not in output and "private-error" not in output
    assert '"path": "deploy/compose.yaml"' in output
    assert '"status": " M"' in output
    assert '"present": ["VASA_SMTP_PASSWORD"]' in output
    assert "VPS_LOGIN_PROBE_REASON=invalid_origin" in output
    assert "VASA_INVESTIGATION_OK" in output
    assert source.read_bytes() == before
    assert {c[0] for c in commands} == {"ls-tree", "diff", "log", "worktree"}


@pytest.mark.parametrize(
    "mode,smoke,recovery",
    [
        ("deploy", "false", "investigate"),
        ("bootstrap", "false", "investigate"),
        ("check", "true", "investigate"),
        ("check", "false", "evil"),
    ],
)
def test_recovery_never_runs_in_deployment_or_smoke_mode(
    monkeypatch, capsys, mode, smoke, recovery
):
    monkeypatch.setattr(deployment.sys, "argv", ["controller", mode, "b" * 40, smoke, recovery])
    monkeypatch.setattr(
        deployment, "preflight", lambda: pytest.fail("Must reject before preflight")
    )
    assert deployment.main() == 1
    assert "VASA_INVESTIGATION_BEGIN" not in capsys.readouterr().out


def test_runtime_probe_allowlist_rejects_injected_markers(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment, "git", lambda *a: "")
    monkeypatch.setattr(deployment, "capture", lambda *a: SimpleNamespace(returncode=0, stdout=""))
    monkeypatch.setattr(
        deployment, "config", lambda: (_ for _ in ()).throw(deployment.Refusal("safe"))
    )
    monkeypatch.setattr(
        deployment,
        "compose",
        lambda *a, **k: (
            "VPS_LOGIN_PROBE_REASON=private-secret\nVPS_DB_REVISION=0006\n"
            "VPS_DB_COUNT_USERS=3 secret\nVPS_DB_COUNT_USERS=2\nAuthorization: secret"
        ),
    )
    deployment.investigate()
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "VPS_DB_REVISION=0006" in output
    assert "VPS_DB_COUNT_USERS=2" in output

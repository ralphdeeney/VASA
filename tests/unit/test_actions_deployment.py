import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import actions_vps as deployment

PREVIOUS = "a" * 40
TARGET = "b" * 40


@pytest.fixture
def origin_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(origin="", rootless_checked=False)
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(
        deployment.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name="vasa-builder")
    )
    monkeypatch.setattr(deployment.os, "chdir", lambda _: None)
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

    def git(*args: str) -> str:
        return {
            ("rev-parse", "--show-toplevel"): str(tmp_path),
            ("remote", "get-url", "origin"): state.origin,
            ("branch", "--show-current"): deployment.BRANCH,
            ("rev-parse", "HEAD"): PREVIOUS,
        }[args]

    def rootless() -> None:
        state.rootless_checked = True

    monkeypatch.setattr(deployment, "git", git)
    monkeypatch.setattr(deployment, "rootless", rootless)
    return state


@pytest.mark.parametrize(
    "origin",
    [
        "git@github-vasa:ralphdeeney/VASA.git",
        "https://github.com/ralphdeeney/VASA",
        "https://github.com/ralphdeeney/VASA.git",
        "git@github.com:ralphdeeney/VASA.git",
        "ssh://git@github.com/ralphdeeney/VASA.git",
    ],
)
def test_preflight_accepts_exact_vasa_origins(origin_preflight, origin: str) -> None:
    origin_preflight.origin = origin
    assert deployment.preflight() == (deployment.BRANCH, PREVIOUS)
    assert origin_preflight.rootless_checked


@pytest.mark.parametrize(
    "origin",
    [
        "git@github-vasa-evil:ralphdeeney/VASA.git",
        "git@github-vasa:other-owner/VASA.git",
        "git@github-vasa:ralphdeeney/other-repository.git",
        "git@github-vasa:ralphdeeney/VASA",
        "git@github-vasa:ralphdeeney/../VASA.git",
        "git@github-vasa:ralphdeeney/VASA.git;echo malicious",
        "git@github-vasa:ralphdeeney/VASA.git\nmalicious",
        "git@github.com:other-owner/VASA.git",
        "https://github.com.evil.invalid/ralphdeeney/VASA.git",
        "https://github.com@evil.invalid/ralphdeeney/VASA.git",
    ],
)
def test_preflight_rejects_unrelated_and_malicious_origins(origin_preflight, origin: str) -> None:
    origin_preflight.origin = origin
    with pytest.raises(deployment.Refusal, match="Unexpected repository identity"):
        deployment.preflight()
    assert not origin_preflight.rootless_checked


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    (tmp_path / ".local").mkdir()
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment.signal, "signal", lambda *_: None)
    state = SimpleNamespace(
        calls=[],
        current=PREVIOUS,
        dirty=False,
        fail_up=False,
        fail_rollback=False,
        changes=["src/vasa/app.py"],
        fail_build=False,
        foreign_config=False,
    )

    def git(*args: str) -> str:
        state.calls.append(("git", *args))
        if args[0] == "status":
            return " M local.txt" if state.dirty else ""
        if args[0] == "rev-parse":
            return TARGET if args[1].startswith("origin/") else state.current
        if args[0] == "diff":
            return "\n".join(state.changes)
        if args[0] == "pull":
            state.current = TARGET
        if args[0] == "reset":
            state.current = PREVIOUS
        return ""

    def compose(*args: str, **kwargs: object) -> str:
        state.calls.append(("compose", *args))
        if args[0] == "up" and state.fail_up:
            state.fail_up = False
            raise deployment.Refusal("Simulated failed start")
        if args[0] == "build" and state.fail_build:
            raise deployment.Refusal("Simulated failed build")
        return ""

    def config() -> dict[str, object]:
        return {
            "name": "vasa-vps",
            "services": {
                "vasa": {},
                "voice": {},
                "postgres": {},
                "redis": {},
                "evolution": {"changed": state.current == TARGET and state.foreign_config},
            },
        }

    def health() -> None:
        state.calls.append(("health",))
        if state.fail_rollback and state.current == PREVIOUS and len(state.calls) > 10:
            raise deployment.Refusal("Simulated rollback health failure")

    monkeypatch.setattr(deployment, "git", git)
    monkeypatch.setattr(deployment, "compose", compose)
    monkeypatch.setattr(deployment, "config", config)
    monkeypatch.setattr(deployment, "health", health)
    monkeypatch.setattr(deployment, "private_hashes", lambda: {"env": "unchanged"})
    monkeypatch.setattr(deployment, "container", lambda _: ("c" * 64, {"image": "old-image"}))
    monkeypatch.setattr(deployment, "diagnostics", lambda: state.calls.append(("diagnostics",)))
    monkeypatch.setattr(deployment, "run", lambda *args, **kw: state.calls.append(args) or "")
    return state


def test_check_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["controller", "check", TARGET])
    monkeypatch.setattr(deployment, "preflight", lambda: (deployment.BRANCH, PREVIOUS))
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment, "deploy", lambda *_: pytest.fail("check must not deploy"))
    assert deployment.main() == 0
    assert list(tmp_path.iterdir()) == []
    assert "VASA_VPS_CONNECTIVITY_OK" in capsys.readouterr().out


def test_dirty_tree_is_preserved(rig, capsys) -> None:
    rig.dirty = True
    with pytest.raises(deployment.Refusal, match="local modifications"):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert rig.calls == [("git", "status", "--porcelain", "--untracked-files=all")]
    assert "VASA_DEPLOYMENT_OK" not in capsys.readouterr().out


def test_schema_update_is_refused_before_checkout(rig) -> None:
    rig.changes = ["migrations/versions/0007_new.py"]
    with pytest.raises(deployment.Refusal, match="Schema changes"):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert not any(call[:2] in (("git", "checkout"), ("git", "reset")) for call in rig.calls)


def test_targeted_deploy_and_receipt(rig, capsys) -> None:
    deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    builds = [call for call in rig.calls if call[:2] == ("compose", "build")]
    assert builds == [("compose", "build", "vasa")]
    ups = [call for call in rig.calls if call[:2] == ("compose", "up")]
    assert len(ups) == 1
    assert "--no-deps" in ups[0] and ups[0][-2:] == ("vasa", "voice")
    receipt = json.loads((deployment.ROOT / ".local/actions-deployment.json").read_text())
    assert receipt["previous_sha"] == PREVIOUS and receipt["status"] == "healthy"
    assert rig.calls[-1] == ("health",)
    assert "VASA_DEPLOYMENT_OK" in capsys.readouterr().out


def test_docs_only_update_does_not_restart(rig) -> None:
    rig.changes = ["docs/DEPLOYMENT_ACTIONS.md", ".github/workflows/vasa-vps-deploy.yml"]
    deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert not any(call[0] == "compose" for call in rig.calls)
    assert rig.current == TARGET


def test_failed_start_rolls_back_only_same_services(rig, capsys) -> None:
    rig.fail_up = True
    with pytest.raises(deployment.Refusal, match="Deployment failed"):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert rig.current == PREVIOUS
    assert ("git", "reset", "--hard", PREVIOUS) in rig.calls
    ups = [call for call in rig.calls if call[:2] == ("compose", "up")]
    assert len(ups) == 2 and ups[0] == ups[1]
    assert rig.calls[-1] == ("health",)
    output = capsys.readouterr().out
    assert "VASA_ROLLBACK_OK" in output and "VASA_DEPLOYMENT_OK" not in output


def test_failed_rollback_is_explicit_and_never_success(rig, capsys) -> None:
    rig.fail_up = rig.fail_rollback = True
    with pytest.raises(deployment.Refusal):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    output = capsys.readouterr().out
    assert "VASA_ROLLBACK_FAILED" in output and "VASA_DEPLOYMENT_OK" not in output


def test_build_failure_can_restore_original_image_without_network(rig, capsys) -> None:
    rig.fail_build = True
    with pytest.raises(deployment.Refusal):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert (
        "docker",
        "image",
        "tag",
        "vasa-app:rollback-" + PREVIOUS,
        "vasa-app:pinned",
    ) in rig.calls
    assert "VASA_ROLLBACK_OK" in capsys.readouterr().out


def test_evolution_config_changes_do_not_restart_evolution(rig, capsys) -> None:
    rig.foreign_config = True
    with pytest.raises(deployment.Refusal):
        deployment.deploy(TARGET, deployment.BRANCH, PREVIOUS)
    assert not any(call[:2] == ("compose", "up") for call in rig.calls)
    assert "VASA_ROLLBACK_OK" in capsys.readouterr().out


def test_rootful_or_foreign_socket_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment.os, "getuid", lambda: 12345)
    monkeypatch.setenv("DOCKER_HOST", "tcp://other-docker:2375")
    with pytest.raises(deployment.Refusal, match="owned local Unix"):
        deployment.rootless()


def test_command_failure_does_not_include_output_or_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        deployment.subprocess,
        "run",
        lambda *args, **kw: SimpleNamespace(
            returncode=1, stdout="secret-output", stderr="secret-key"
        ),
    )
    with pytest.raises(deployment.Refusal) as caught:
        deployment.run("command", "private-argument")
    assert "secret" not in str(caught.value)
    assert "private-argument" not in str(caught.value)
    assert capsys.readouterr().out == ""


def test_startup_failure_logs_are_not_printed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        deployment.subprocess,
        "run",
        lambda *args, **kw: SimpleNamespace(returncode=0, stdout="", stderr="ERROR secret-value"),
    )
    with pytest.raises(deployment.Refusal, match="failure markers"):
        deployment.log_health("c" * 64, "2026-10-15T00:00:00Z", worker=True)
    assert "secret-value" not in capsys.readouterr().out


def test_ssh_wrapper_refuses_execution_outside_actions() -> None:
    environment = dict(os.environ)
    environment.pop("GITHUB_ACTIONS", None)
    result = subprocess.run(
        ["bash", "deploy/actions-ssh.sh"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "GitHub Actions runner required" in result.stderr


def test_health_rejects_oom_and_unhealthy_containers() -> None:
    assert not deployment.state_ok({"state": {"Status": "running", "OOMKilled": True}})
    assert not deployment.state_ok(
        {"state": {"Status": "running", "Health": {"Status": "unhealthy"}}}
    )


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.parametrize("mode", ["check", "bootstrap", "deploy"])
def test_ssh_requires_pinned_host_and_cleans_temporary_key(tmp_path, trusted, mode) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    programs = {
        "ssh-keygen": '#!/bin/sh\nif [ "$1" != -y ]; then '
        'printf "256 SHA256:trusted test (ED25519)\\n"; fi\n',
        "ssh-keyscan": '#!/bin/sh\nprintf "example.invalid ssh-ed25519 fake-key\\n"\n',
        "ssh": '#!/bin/sh\ncat > /dev/null\ntouch "$SSH_CALLED"\n'
        'printf "VASA_VPS_CONNECTIVITY_OK\\n"\n',
    }
    for name, content in programs.items():
        executable = commands / name
        executable.write_text(content)
        executable.chmod(0o700)
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    called = tmp_path / "called"
    environment = dict(os.environ)
    environment.update(
        {
            "PATH": str(commands) + os.pathsep + environment["PATH"],
            "GITHUB_ACTIONS": "true",
            "GITHUB_SHA": TARGET,
            "VASA_DEPLOY_MODE": mode,
            "VASA_VPS_USER": "vasa-builder",
            "VASA_VPS_HOST": "example.invalid",
            "VASA_VPS_SSH_KEY": "fake-unit-test-key",
            "VASA_VPS_HOST_KEY_SHA256": "SHA256:trusted" if trusted else "SHA256:wrong",
            "RUNNER_TEMP": str(runner_temp),
            "SSH_CALLED": str(called),
        }
    )
    result = subprocess.run(
        ["bash", "deploy/actions-ssh.sh"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is trusted
    assert called.exists() is trusted
    assert list(runner_temp.iterdir()) == []
    assert "fake-unit-test-key" not in result.stdout + result.stderr
    assert "example.invalid" not in result.stdout + result.stderr

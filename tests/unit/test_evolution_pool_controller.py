"""Stateful regression coverage for the complete guarded Evolution rollout."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import actions_evolution_pool as pool

TARGET = "a" * 40
CANONICAL = "b" * 40
OLD_IMAGE = "sha256:" + "1" * 64
CANDIDATE_IMAGE = "sha256:" + "2" * 64
FALLBACK_IMAGE = "sha256:" + "3" * 64
SECRET = "Authorization: Bearer private-secret caller-id raw-provider-body"
CAPACITY = """
def diagnose_sockets(ns):
    ns["capacity_reads"].append(True)
    value = 95 if len(ns["capacity_reads"]) == 1 else 2
    print("DB_SOCKET_EVOLUTION=" + str(value))
    print("DB_SOCKET_VASA=5")
    print("DB_SOCKET_VOICE=5")
    print("DB_SOCKET_OTHER=1")
    print("DB_SOCKET_TOTAL=" + str(value + 11))
    print("DB_CONFIG_MAX_CONNECTIONS=100")
    print("Authorization: Bearer private-secret caller-id raw-provider-body")
"""
BACKUPS = """
def backup(ns):
    ns["events"].append(("backup_verified",))
    return {"identity": "preserved", "backup_sha256": "safe-hash"}
def snapshot(ns):
    ns["events"].append(("identity_checked",))
    return "preserved"
"""


class Refusal(Exception):
    pass


class Runtime:
    def __init__(
        self,
        root: Path,
        *,
        active_at: int = 0,
        replacement_fails: bool = False,
        health_fails: bool = False,
        missing_image: bool = False,
        fallback_build_fails: bool = False,
    ):
        self.root = root
        (root / ".local").mkdir()
        (root / ".local/actions-release.json").write_text(json.dumps({"active_sha": CANONICAL}))
        self.events = []
        self.gate_calls = 0
        self.active_at = active_at
        self.replacement_fails = replacement_fails
        self.health_fails = health_fails
        self.health_calls = 0
        self.missing_image = missing_image
        self.fallback_build_fails = fallback_build_fails
        self.rollback_image = OLD_IMAGE
        self.evolution_image = OLD_IMAGE
        self.before = {
            service: {
                "image": OLD_IMAGE if service == "evolution" else service + "-image",
                "id": service + "-container",
            }
            for service in ("postgres", "redis", "evolution", "vasa", "voice")
        }
        self.ns = {
            "ROOT": root,
            "PROJECT": "vasa-vps",
            "BRANCH": "build/vasa-foundation",
            "DEPENDENCIES": ("postgres", "redis", "evolution"),
            "SERVICES": ("vasa", "voice"),
            "Refusal": Refusal,
            "preflight": lambda: self.events.append(("preflight",)),
            "require": self.require,
            "git": self.git,
            "run": self.command,
            "capture": self.capture,
            "container": self.container,
            "snapshot_services": lambda services: self.before,
            "private_hashes": lambda: {"private": "unchanged"},
            "assert_unchanged": lambda state: self.events.append(("unchanged", tuple(state))),
            "health": self.health,
            "signal_failure": lambda *args: None,
            "capacity_reads": [],
            "events": self.events,
        }

    @staticmethod
    def require(condition, message):
        if not condition:
            raise Refusal(message)

    def git(self, *args):
        self.events.append(("git", *args))
        if args[:2] == ("rev-parse", "HEAD"):
            return CANONICAL
        if args[0] == "rev-parse":
            return TARGET
        if args[0] == "status":
            return "?? edge/Caddyfile"
        if args[:2] == ("worktree", "add"):
            Path(args[-2]).mkdir()
        return ""

    def container(self, service):
        image = self.evolution_image if service == "evolution" else service + "-image"
        return service + "-container", {"image": image}

    def command(self, *args, **kwargs):
        self.events.append(("command", args, kwargs))
        if args[:3] == ("docker", "image", "inspect"):
            image = args[-1]
            return CANDIDATE_IMAGE if "pool-" in image else self.rollback_image
        if args[:2] == ("docker", "build") and "rollback-" in args[3]:
            if self.fallback_build_fails:
                raise RuntimeError(SECRET)
            self.rollback_image = FALLBACK_IMAGE
        if args[:2] == ("docker", "compose") and "up" in args:
            image = json.loads(kwargs["input_text"])["services"]["evolution"]["image"]
            if "pool-" in image:
                if self.replacement_fails:
                    raise RuntimeError(SECRET)
                self.evolution_image = CANDIDATE_IMAGE
            else:
                self.evolution_image = self.rollback_image
        return ""

    def capture(self, *args, **kwargs):
        self.events.append(("capture", args))
        if args[:3] == ("docker", "image", "inspect"):
            return SimpleNamespace(
                returncode=int(self.missing_image),
                stdout=SECRET if self.missing_image else OLD_IMAGE + "\n",
            )
        if args[-1] in ("/proc/net/udp", "/proc/net/udp6"):
            return SimpleNamespace(returncode=0, stdout="sl local_address rem_address st\n")
        if "GATE" in args:
            self.gate_calls += 1
            if self.gate_calls == self.active_at:
                return SimpleNamespace(
                    returncode=1,
                    stdout=(
                        SECRET + "\nEVOLUTION_CALL_GATE_DB_ACTIVE=1\n"
                        "EVOLUTION_CALL_GATE_REDIS_ACTIVE=0\n"
                        "EVOLUTION_CALL_GATE_FAILED=active_calls\n"
                    ),
                )
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    SECRET + "\nEVOLUTION_CALL_GATE_DB_ACTIVE=0\n"
                    "EVOLUTION_CALL_GATE_REDIS_ACTIVE=0\nEVOLUTION_CALL_GATE_OK\n"
                ),
            )
        return SimpleNamespace(
            returncode=0, stdout=SECRET + "\nEVOLUTION_REGISTERED_INSTANCES_OK\n"
        )

    def health(self):
        self.events.append(("health",))
        self.health_calls += 1
        if self.health_fails and self.health_calls == 1:
            raise RuntimeError(SECRET)

    def run(self, deploy=True):
        return pool.run(self.ns, TARGET, deploy, "GATE", "INSTANCES", BACKUPS, CAPACITY)

    def commands(self):
        return [event[1] for event in self.events if event[0] == "command"]

    def replacements(self):
        return [
            event
            for event in self.events
            if event[0] == "command" and event[1][:2] == ("docker", "compose") and "up" in event[1]
        ]


@pytest.fixture(autouse=True)
def isolated_signals_and_clock(monkeypatch):
    monkeypatch.setattr(pool.signal, "signal", lambda *args: None)
    monkeypatch.setattr(pool.time, "sleep", lambda *args: None)


def test_preflight_is_read_only_and_reports_capacity(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    assert runtime.run(deploy=False) == 0
    assert runtime.commands() == []
    assert runtime.replacements() == []
    assert not (tmp_path / ".local/evolution-releases").exists()
    output = capsys.readouterr().out
    assert "EVOLUTION_POOL_PREFLIGHT_OK" in output
    assert "DB_SOCKET_EVOLUTION=95" in output
    assert SECRET not in output


def test_active_calls_defer_before_preparation_or_runtime_mutation(tmp_path, capsys):
    runtime = Runtime(tmp_path, active_at=1)
    assert runtime.run() == 2
    assert runtime.commands() == []
    assert not any(event[0] == "backup_verified" for event in runtime.events)
    assert not any(event[:2] == ("git", "fetch") for event in runtime.events)
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLOUT_DEFERRED=call_or_instance_inspection" in output
    assert SECRET not in output


def test_success_replaces_only_evolution_preserves_other_services(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    assert runtime.run() == 0
    assert runtime.gate_calls == 3
    assert len(runtime.replacements()) == 1
    command = runtime.replacements()[0][1]
    assert command[-1] == "evolution"
    assert "--no-deps" in command and "--no-build" in command and "--wait" in command
    assert ("docker", "pause", "voice-container") in runtime.commands()
    assert ("docker", "unpause", "voice-container") in runtime.commands()
    assert runtime.evolution_image == CANDIDATE_IMAGE
    assert ("unchanged", ("postgres", "redis", "vasa", "voice")) in runtime.events
    backup_index = runtime.events.index(("backup_verified",))
    pause_index = next(
        i
        for i, event in enumerate(runtime.events)
        if event[0] == "command" and event[1][:2] == ("docker", "pause")
    )
    assert backup_index < pause_index
    journal = json.loads((tmp_path / ".local/actions-evolution-pool.json").read_text())
    assert journal["status"] == "healthy" and journal["target_sha"] == TARGET
    assert journal["connections_before"]["DB_SOCKET_EVOLUTION"] == 95
    assert journal["connections_after"]["DB_SOCKET_EVOLUTION"] == 2
    output = capsys.readouterr().out
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" in output
    assert "EVOLUTION_DEPLOYED_SHA=" + TARGET in output
    assert SECRET not in output
    all_commands = repr(runtime.commands())
    for forbidden in ("sudo", "prune", "down", "restart", "n8n", "cloudflare"):
        assert forbidden not in all_commands


def test_post_pause_call_race_defers_and_always_unpauses(tmp_path, capsys):
    runtime = Runtime(tmp_path, active_at=3)
    with pytest.raises(Refusal, match="sanitized markers only"):
        runtime.run()
    assert not runtime.replacements()
    assert ("docker", "pause", "voice-container") in runtime.commands()
    assert ("docker", "unpause", "voice-container") in runtime.commands()
    assert runtime.evolution_image == OLD_IMAGE
    assert not (tmp_path / ".local/actions-evolution-pool.json").exists()
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLOUT_DEFERRED=active_or_unknown_after_quiesce" in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output


@pytest.mark.parametrize("failure", ["replacement", "health"])
def test_failed_replacement_or_health_restores_verified_old_image(tmp_path, capsys, failure):
    runtime = Runtime(
        tmp_path, replacement_fails=failure == "replacement", health_fails=failure == "health"
    )
    with pytest.raises(Refusal, match="sanitized markers only"):
        runtime.run()
    replacements = runtime.replacements()
    assert len(replacements) == 2
    assert "pool-" in replacements[0][2]["input_text"]
    assert "rollback-" in replacements[1][2]["input_text"]
    assert all(event[1][-1] == "evolution" for event in replacements)
    assert runtime.evolution_image == OLD_IMAGE
    assert runtime.health_calls >= 1
    assert ("docker", "unpause", "voice-container") in runtime.commands()
    assert not (tmp_path / ".local/actions-evolution-pool.json").exists()
    output = capsys.readouterr().out
    assert "VASA_EVOLUTION_POOL_ROLLBACK_OK" in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output


def test_call_started_during_build_defers_before_voice_pause(tmp_path, capsys):
    runtime = Runtime(tmp_path, active_at=2)
    with pytest.raises(pool.Deferred):
        runtime.run()
    assert runtime.replacements() == []
    assert not any(command[:2] == ("docker", "pause") for command in runtime.commands())
    assert ("backup_verified",) in runtime.events
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in capsys.readouterr().out


def test_missing_instance_proof_defers_without_mutation(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    original = runtime.capture

    def capture(*args, **kwargs):
        if "INSTANCES" in args:
            return SimpleNamespace(returncode=1, stdout=SECRET)
        return original(*args, **kwargs)

    runtime.ns["capture"] = capture
    assert runtime.run() == 2
    assert runtime.commands() == []
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLOUT_DEFERRED=call_or_instance_inspection" in output
    assert SECRET not in output


def test_unknown_media_inspection_defers_without_mutation(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    original = runtime.capture

    def capture(*args, **kwargs):
        if args[-1] == "/proc/net/udp":
            return SimpleNamespace(returncode=1, stdout=SECRET)
        return original(*args, **kwargs)

    runtime.ns["capture"] = capture
    assert runtime.run() == 2
    assert runtime.commands() == []
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLOUT_DEFERRED=media_inspection" in output
    assert SECRET not in output


def test_excessive_connections_after_replacement_roll_back(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    failing_capacity = CAPACITY.replace("else 2", "else 95")
    with pytest.raises(Refusal):
        pool.run(runtime.ns, TARGET, True, "GATE", "INSTANCES", BACKUPS, failing_capacity)
    assert runtime.evolution_image == OLD_IMAGE
    assert len(runtime.replacements()) == 2
    output = capsys.readouterr().out
    assert "VASA_EVOLUTION_POOL_ROLLBACK_OK" in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output


def test_rollback_failure_still_unpauses_voice_without_secret_output(tmp_path, capsys):
    runtime = Runtime(tmp_path, replacement_fails=True)
    original = runtime.command

    def command(*args, **kwargs):
        if args[:2] == ("docker", "compose") and "up" in args:
            runtime.events.append(("command", args, kwargs))
            raise RuntimeError(SECRET)
        return original(*args, **kwargs)

    runtime.ns["run"] = command
    with pytest.raises(Refusal):
        runtime.run()
    assert ("docker", "unpause", "voice-container") in runtime.commands()
    output = capsys.readouterr().out
    assert "VASA_EVOLUTION_POOL_ROLLBACK_FAILED" in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output


def test_missing_old_image_builds_verified_rollback_before_target_or_runtime_changes(
    tmp_path, capsys
):
    runtime = Runtime(tmp_path, missing_image=True)
    assert runtime.run() == 0
    commands = runtime.commands()
    fallback_prepare = next(
        i for i, command in enumerate(commands) if "--rollback-source" in command
    )
    fallback_build = next(
        i
        for i, command in enumerate(commands)
        if command[:2] == ("docker", "build") and "rollback-" in command[3]
    )
    fallback_verify = next(
        i
        for i, command in enumerate(commands)
        if command[:3] == ("docker", "image", "inspect") and "rollback-" in command[-1]
    )
    target_build = next(
        i
        for i, command in enumerate(commands)
        if command[:2] == ("docker", "build") and "pool-" in command[3]
    )
    pause = commands.index(("docker", "pause", "voice-container"))
    assert fallback_prepare < fallback_build < fallback_verify < target_build < pause
    assert "VASA_REVISION=e21ce0dd7634f3047410c893b5e4d1c082034b84" in commands[fallback_build]
    assert commands[fallback_build][-1].endswith("/.local/evolution-rollback-source")
    assert runtime.evolution_image == CANDIDATE_IMAGE
    assert runtime.rollback_image == FALLBACK_IMAGE
    assert ("unchanged", tuple(runtime.before)) in runtime.events
    assert not any(command[:2] == ("docker", "commit") for command in commands)
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLBACK_IMAGE=previous_source_build" in output
    assert "EVOLUTION_ROLLBACK_IMAGE_VERIFIED" in output
    assert SECRET not in output


def test_failed_fallback_build_preserves_checkout_and_all_running_services(tmp_path, capsys):
    runtime = Runtime(tmp_path, missing_image=True, fallback_build_fails=True)
    with pytest.raises(RuntimeError):
        runtime.run()
    assert runtime.evolution_image == OLD_IMAGE
    assert runtime.replacements() == []
    assert not any(command[:2] == ("docker", "pause") for command in runtime.commands())
    assert not any(
        command[:2] == ("docker", "build") and "pool-" in command[3]
        for command in runtime.commands()
    )
    assert not any(
        event[:2] in (("git", "checkout"), ("git", "pull"), ("git", "reset"))
        for event in runtime.events
    )
    assert not (tmp_path / ".local/actions-evolution-pool.json").exists()
    assert not any(event[0] == "backup_verified" for event in runtime.events)
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLBACK_IMAGE_VERIFIED" not in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output


def test_health_failure_rolls_back_to_verified_fallback_image(tmp_path, capsys):
    runtime = Runtime(tmp_path, missing_image=True, health_fails=True)
    with pytest.raises(Refusal):
        runtime.run()
    assert runtime.evolution_image == FALLBACK_IMAGE
    assert len(runtime.replacements()) == 2
    assert "rollback-" in runtime.replacements()[1][2]["input_text"]
    assert ("docker", "unpause", "voice-container") in runtime.commands()
    assert runtime.health_calls == 2
    assert ("unchanged", ("postgres", "redis", "vasa", "voice")) in runtime.events
    assert not (tmp_path / ".local/actions-evolution-pool.json").exists()
    output = capsys.readouterr().out
    assert "EVOLUTION_ROLLBACK_IMAGE_VERIFIED" in output
    assert "VASA_EVOLUTION_POOL_ROLLBACK_OK" in output
    assert "VASA_EVOLUTION_POOL_DEPLOYMENT_OK" not in output
    assert SECRET not in output

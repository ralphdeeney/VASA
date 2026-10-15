import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import actions_vps as controller

PREVIOUS = "a" * 40
TARGET = "b" * 40
OLD_IMAGE = "sha256:" + "1" * 64
NEW_IMAGE = "sha256:" + "2" * 64
ROLLBACK_IMAGE = "sha256:" + "3" * 64
FAKE_KEY = "FAKE-BOOTSTRAP-SECRET-DO-NOT-PRINT"


def item(cid: str, image: str = OLD_IMAGE) -> tuple[str, dict]:
    return cid * 64, {
        "image": image,
        "restarts": 0,
        "state": {"Status": "running", "OOMKilled": False, "StartedAt": "2026-10-15T00:00:00Z"},
    }


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/llm.env").write_text("DEEPGRAM_API_KEY=" + FAKE_KEY + "\n")
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    monkeypatch.setattr(controller, "post_validation", lambda _: None)
    monkeypatch.setattr(controller.signal, "signal", lambda *_: None)
    state = SimpleNamespace(
        calls=[],
        current=PREVIOUS,
        key=FAKE_KEY,
        dirty=False,
        tracked=False,
        tracked_target=False,
        changes=["src/vasa/app.py"],
        remote_target=TARGET,
        containers={
            "postgres": item("a"),
            "redis": item("b"),
            "evolution": item("c"),
            "vasa": item("e"),
        },
        tags={"vasa-app:pinned": OLD_IMAGE},
        built_image=NEW_IMAGE,
        fail_voice=False,
        fail_build=False,
        fail_app=False,
        fail_worker_health=False,
        fail_rollback_health=False,
        dependency_restart=False,
        config_change=False,
        secret_change=False,
        image_available=True,
        fail_image_tag=False,
        fail_rollback_build=False,
        fail_rollback_inspect=False,
        rollback_builds=[],
        fail_up_once=False,
        original_diagnostics=controller.diagnostics,
    )

    def git(*args: str) -> str:
        state.calls.append(("git", *args))
        if args[0] == "status":
            return " M local.txt" if state.dirty else ""
        if args[0] == "ls-files":
            return ".local/llm.env" if state.tracked else ""
        if args[0] == "ls-tree":
            return ".env" if state.tracked_target else ""
        if args[0] == "rev-parse":
            return state.remote_target if args[1].startswith("origin/") else state.current
        if args[0] == "diff":
            return "\n".join(state.changes)
        if args[0] == "pull":
            state.current = TARGET
        if args[0] == "reset":
            state.current = PREVIOUS
        return ""

    def run(*args: str, **kwargs: object) -> str:
        state.calls.append(args)
        if args[:3] == ("docker", "ps", "--all"):
            return "\n".join(value[0] for value in state.containers.values())
        if args[:3] == ("docker", "image", "tag"):
            if args[3] == OLD_IMAGE and (not state.image_available or state.fail_image_tag):
                raise controller.Refusal("Running image cannot be tagged")
            state.tags[args[4]] = state.tags.get(args[3], args[3])
            return ""
        if args[:3] == ("docker", "image", "inspect"):
            reference = args[-1]
            if reference == OLD_IMAGE and not state.image_available:
                raise controller.Refusal("Running image no longer exists")
            if state.fail_rollback_inspect and "rollback-" in reference:
                raise controller.Refusal("Rollback image cannot be verified")
            if reference in state.tags:
                return state.tags[reference]
            if reference in state.tags.values():
                return reference
            raise controller.Refusal("Missing image")
        if args[:4] == ("docker", "container", "rm", "--force"):
            assert args[4] == state.containers["voice"][0]
            del state.containers["voice"]
            return ""
        pytest.fail("Unexpected command: " + repr(args))

    def compose(*args: str, **kwargs: object) -> str:
        state.calls.append(("compose", *args))
        if args[:4] == ("ps", "--all", "--quiet", "voice"):
            return state.containers["voice"][0] if "voice" in state.containers else ""
        if args == ("build", "vasa"):
            if kwargs.get("image_override"):
                tag = kwargs["image_override"]
                state.calls.append(("rollback_build", tag, state.current))
                state.rollback_builds.append((tag, state.current))
                if state.fail_rollback_build:
                    raise controller.Refusal("Rollback source build failed")
                state.tags[tag] = ROLLBACK_IMAGE
                return ""
            state.tags["vasa-app:pinned"] = state.built_image
            if state.fail_build:
                raise controller.Refusal("Simulated failed build")
            return ""
        if args[0] == "up":
            assert args[1:6] == ("-d", "--no-deps", "--wait", "--wait-timeout", "150")
            for service in args[6:]:
                assert service in ("vasa", "voice")
                state.containers[service] = item(
                    "d" if service == "vasa" else "f", state.tags["vasa-app:pinned"]
                )
                if service == "voice":
                    if state.dependency_restart:
                        state.containers["redis"][1]["restarts"] += 1
                    if state.secret_change:
                        (tmp_path / ".local/llm.env").write_text("changed-private-environment")
                    if state.fail_voice:
                        raise controller.Refusal("Simulated creation followed by failed start")
                if service == "vasa" and state.fail_app:
                    state.fail_app = False
                    raise controller.Refusal("Simulated failed app restart")
            if state.fail_up_once:
                state.fail_up_once = False
                raise controller.Refusal("Simulated failed app start")
            return ""
        pytest.fail("Unexpected Compose operation: " + repr(args))

    def container(service: str) -> tuple[str, dict]:
        if service not in state.containers:
            raise controller.Refusal("Expected exactly one existing VASA container for " + service)
        return copy.deepcopy(state.containers[service])

    def config() -> dict:
        return {
            "name": "vasa-vps",
            "services": {
                "postgres": {},
                "redis": {},
                "evolution": {},
                "vasa": {"config": state.config_change and state.current == TARGET},
                "voice": {"environment": {"DEEPGRAM_API_KEY": state.key}},
            },
        }

    def health(*, include_voice: bool = True) -> None:
        state.calls.append(("health", include_voice))
        for service in controller.DEPENDENCIES + (
            ("vasa", "voice") if include_voice else ("vasa",)
        ):
            container(service)
        if include_voice and state.fail_worker_health:
            raise controller.Refusal("Simulated missing worker readiness")
        if (
            not include_voice
            and state.current == PREVIOUS
            and state.fail_rollback_health
            and any(call[:2] == ("git", "reset") for call in state.calls)
        ):
            raise controller.Refusal("Simulated unhealthy rollback")

    monkeypatch.setattr(controller, "git", git)
    monkeypatch.setattr(controller, "run", run)
    monkeypatch.setattr(controller, "compose", compose)
    monkeypatch.setattr(controller, "container", container)
    monkeypatch.setattr(controller, "config", config)
    monkeypatch.setattr(controller, "health", health)
    monkeypatch.setattr(
        controller, "diagnostics", lambda **kwargs: state.calls.append(("diagnostics",))
    )
    return state


def test_bootstrap_creates_voice_and_updates_only_required_app(rig, capsys) -> None:
    before = controller.snapshot_services(controller.DEPENDENCIES)
    hashes = controller.private_hashes()
    controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert [c[-1] for c in rig.calls if c[:2] == ("compose", "up")] == ["vasa", "voice"]
    assert [c for c in rig.calls if c[:2] == ("compose", "build")] == [("compose", "build", "vasa")]
    assert controller.snapshot_services(controller.DEPENDENCIES) == before
    assert controller.private_hashes() == hashes
    assert rig.containers["vasa"][1]["image"] == rig.containers["voice"][1]["image"] == NEW_IMAGE
    output = capsys.readouterr().out
    assert "VASA_BOOTSTRAP_OK" in output and FAKE_KEY not in output
    receipt = (controller.ROOT / ".local/actions-bootstrap.json").read_text()
    assert json.loads(receipt)["status"] == "healthy" and FAKE_KEY not in receipt


def test_identical_image_and_config_only_creates_voice(rig) -> None:
    rig.built_image = OLD_IMAGE
    before = controller.snapshot_services(("vasa",))
    controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert [c[-1] for c in rig.calls if c[:2] == ("compose", "up")] == ["voice"]
    assert controller.snapshot_services(("vasa",)) == before


def test_config_change_updates_app_even_when_image_identical(rig) -> None:
    rig.built_image = OLD_IMAGE
    rig.config_change = True
    controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert [c[-1] for c in rig.calls if c[:2] == ("compose", "up")] == ["vasa", "voice"]


def test_bootstrap_enables_subsequent_update_only_deploy(rig, capsys) -> None:
    controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    rig.changes = []
    controller.deploy(TARGET, controller.BRANCH, TARGET)
    assert "VASA_DEPLOYMENT_OK" in capsys.readouterr().out


def test_normal_deploy_does_not_bootstrap_missing_voice(rig) -> None:
    with pytest.raises(controller.Refusal, match="voice"):
        controller.deploy(TARGET, controller.BRANCH, PREVIOUS)
    assert not any(
        c[:2] in (("git", "fetch"), ("compose", "build"), ("compose", "up")) for c in rig.calls
    )


@pytest.mark.parametrize(
    "problem", ["existing-voice", "missing-dependency", "unhealthy", "extra-container"]
)
def test_unexpected_bootstrap_topology_is_refused_before_fetch(rig, problem: str) -> None:
    if problem == "existing-voice":
        rig.containers["voice"] = item("f")
    elif problem == "missing-dependency":
        del rig.containers["redis"]
    elif problem == "unhealthy":
        rig.containers["postgres"][1]["state"]["Status"] = "exited"
    else:
        rig.containers["unexpected"] = item("9")
    with pytest.raises(controller.Refusal):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert not any(c[:2] == ("git", "fetch") for c in rig.calls)


def test_dirty_bootstrap_does_not_fetch_or_modify_apps(rig) -> None:
    rig.dirty = True
    with pytest.raises(controller.Refusal, match="local modifications"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert rig.calls == [("git", "status", "--porcelain", "--untracked-files=all")]


@pytest.mark.parametrize("key", [None, "", " \t"])
def test_missing_deepgram_key_is_explicit_and_precedes_fetch(rig, key, capsys) -> None:
    rig.key = key
    with pytest.raises(controller.Refusal, match="^DEEPGRAM_VPS_KEY_REQUIRED$"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert not any(c[:2] == ("git", "fetch") for c in rig.calls)
    assert FAKE_KEY not in capsys.readouterr().out


@pytest.mark.parametrize("tracked_target", [False, True])
def test_runtime_secrets_must_stay_untracked(rig, tracked_target: bool) -> None:
    rig.tracked = not tracked_target
    rig.tracked_target = tracked_target
    with pytest.raises(controller.Refusal, match="(?:untracked|track private)"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert not any(c[:2] == ("git", "checkout") for c in rig.calls)


def test_migrations_are_refused_before_checkout(rig) -> None:
    rig.changes = ["migrations/versions/new_schema.py"]
    with pytest.raises(controller.Refusal, match="Schema changes"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert not any(c[:2] == ("git", "checkout") for c in rig.calls)


@pytest.mark.parametrize("failure", ["fail_voice", "fail_worker_health", "fail_app", "fail_build"])
def test_bootstrap_rollback_restores_image_and_only_removes_new_voice(rig, failure, capsys) -> None:
    setattr(rig, failure, True)
    dependencies = controller.snapshot_services(controller.DEPENDENCIES)
    hashes = controller.private_hashes()
    with pytest.raises(controller.Refusal, match="Bootstrap failed"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert rig.current == PREVIOUS
    assert "voice" not in rig.containers
    assert rig.containers["vasa"][1]["image"] == OLD_IMAGE
    assert rig.tags["vasa-app:pinned"] == OLD_IMAGE
    assert controller.snapshot_services(controller.DEPENDENCIES) == dependencies
    assert controller.private_hashes() == hashes
    removals = [c for c in rig.calls if c[:3] == ("docker", "container", "rm")]
    assert removals == (
        []
        if failure in ("fail_app", "fail_build")
        else [("docker", "container", "rm", "--force", "f" * 64)]
    )
    ups = [c[-1] for c in rig.calls if c[:2] == ("compose", "up")]
    assert all(service in ("vasa", "voice") for service in ups)
    assert rig.calls[-1] == (
        "docker",
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.project=vasa-vps",
        "--format",
        "{{.ID}}",
    )
    output = capsys.readouterr().out
    assert "VASA_BOOTSTRAP_ROLLBACK_OK" in output and "VASA_BOOTSTRAP_OK" not in output
    assert FAKE_KEY not in output


def test_rollback_failure_stays_nonzero_without_success_marker(rig, capsys) -> None:
    rig.fail_voice = rig.fail_rollback_health = True
    with pytest.raises(controller.Refusal):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    output = capsys.readouterr().out
    assert "VASA_BOOTSTRAP_ROLLBACK_FAILED" in output
    assert "VASA_BOOTSTRAP_ROLLBACK_OK" not in output and "VASA_BOOTSTRAP_OK" not in output
    assert FAKE_KEY not in output


def test_voice_only_failure_preserves_existing_api_container(rig, capsys) -> None:
    rig.built_image = OLD_IMAGE
    rig.fail_voice = True
    before = controller.snapshot_services(controller.DEPENDENCIES + ("vasa",))
    with pytest.raises(controller.Refusal):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    assert controller.snapshot_services(controller.DEPENDENCIES + ("vasa",)) == before
    assert [c[-1] for c in rig.calls if c[:2] == ("compose", "up")] == ["voice"]
    assert "VASA_BOOTSTRAP_ROLLBACK_OK" in capsys.readouterr().out


def test_dependency_restart_prevents_bootstrap_and_rollback_success(rig, capsys) -> None:
    rig.dependency_restart = True
    with pytest.raises(controller.Refusal):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    output = capsys.readouterr().out
    assert "VASA_BOOTSTRAP_OK" not in output and "VASA_BOOTSTRAP_ROLLBACK_FAILED" in output


def test_changed_private_environment_prevents_success(rig, capsys) -> None:
    rig.secret_change = True
    with pytest.raises(controller.Refusal):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    output = capsys.readouterr().out
    assert "VASA_BOOTSTRAP_OK" not in output and FAKE_KEY not in output


@pytest.mark.parametrize("mode", ["bootstrap", "deploy"])
def test_main_routes_modes_explicitly(monkeypatch, mode) -> None:
    calls = []
    monkeypatch.setattr(controller.sys, "argv", ["controller", mode, TARGET])
    monkeypatch.setattr(controller, "preflight", lambda: (controller.BRANCH, PREVIOUS))
    monkeypatch.setattr(controller, "bootstrap", lambda *args: calls.append(("bootstrap", args)))
    monkeypatch.setattr(controller, "deploy", lambda *args: calls.append(("deploy", args)))
    assert controller.main() == 0
    assert calls == [(mode, (TARGET, controller.BRANCH, PREVIOUS))]


@pytest.mark.parametrize(
    "label",
    [
        "com.docker.compose.project",
        "com.docker.compose.service",
        "com.docker.compose.project.working_dir",
    ],
)
def test_voice_removal_refuses_foreign_ownership(monkeypatch, label) -> None:
    value = {
        "labels": {
            "com.docker.compose.project": "vasa-vps",
            "com.docker.compose.service": "voice",
            "com.docker.compose.project.working_dir": str(controller.ROOT / "deploy"),
        }
    }
    value["labels"][label] = "unrelated"
    calls = []
    monkeypatch.setattr(controller, "compose", lambda *args: "f" * 64)

    def run(*args, **kwargs):
        calls.append(args)
        assert args[:2] == ("docker", "inspect")
        return json.dumps(value)

    monkeypatch.setattr(controller, "run", run)
    with pytest.raises(controller.Refusal, match="ownership"):
        controller.remove_bootstrapped_voice()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "label",
    [
        "com.docker.compose.project",
        "com.docker.compose.service",
        "com.docker.compose.project.working_dir",
    ],
)
def test_bootstrap_topology_refuses_foreign_dependency(monkeypatch, label) -> None:
    labels = {
        "com.docker.compose.project": "vasa-vps",
        "com.docker.compose.service": "postgres",
        "com.docker.compose.project.working_dir": str(controller.ROOT / "deploy"),
    }
    labels[label] = "unrelated"
    monkeypatch.setattr(controller, "compose", lambda *args: "a" * 64)
    monkeypatch.setattr(controller, "run", lambda *args, **kwargs: json.dumps({"labels": labels}))
    with pytest.raises(controller.Refusal, match="ownership"):
        controller.bootstrap_topology()


def test_existing_running_image_is_verified_and_tagged_without_source_build(rig) -> None:
    before = copy.deepcopy(rig.containers)
    tag = "vasa-app:bootstrap-rollback-" + PREVIOUS
    assert controller.acquire_rollback_image(OLD_IMAGE, PREVIOUS, tag) == OLD_IMAGE
    assert rig.tags[tag] == OLD_IMAGE and rig.tags["vasa-app:pinned"] == OLD_IMAGE
    assert rig.rollback_builds == [] and rig.containers == before
    assert ("docker", "image", "inspect", "--format", "{{.Id}}", OLD_IMAGE) in rig.calls
    assert ("docker", "image", "tag", OLD_IMAGE, tag) in rig.calls
    assert ("docker", "image", "inspect", "--format", "{{.Id}}", tag) in rig.calls


def test_inspectable_but_untaggable_running_image_also_uses_previous_source(rig) -> None:
    rig.fail_image_tag = True
    tag = "vasa-app:bootstrap-rollback-" + PREVIOUS
    assert controller.acquire_rollback_image(OLD_IMAGE, PREVIOUS, tag) == ROLLBACK_IMAGE
    assert rig.rollback_builds == [(tag, PREVIOUS)]
    assert rig.tags["vasa-app:pinned"] == OLD_IMAGE


@pytest.mark.parametrize("mode", ["bootstrap", "deploy"])
def test_missing_old_image_builds_and_verifies_previous_source_before_checkout(rig, mode, capsys):
    rig.image_available = False
    if mode == "deploy":
        rig.containers["voice"] = item("f")
    dependencies = controller.snapshot_services(controller.DEPENDENCIES)
    hashes = controller.private_hashes()
    getattr(controller, mode)(TARGET, controller.BRANCH, PREVIOUS)
    tag = "vasa-app:" + ("bootstrap-" if mode == "bootstrap" else "") + "rollback-" + PREVIOUS
    assert rig.rollback_builds == [(tag, PREVIOUS)]
    build = rig.calls.index(("rollback_build", tag, PREVIOUS))
    verify = rig.calls.index(("docker", "image", "inspect", "--format", "{{.Id}}", tag))
    checkout = rig.calls.index(("git", "checkout", controller.BRANCH))
    assert build < verify < checkout
    assert rig.tags[tag] == ROLLBACK_IMAGE
    assert rig.containers["vasa"][1]["image"] == NEW_IMAGE
    assert controller.snapshot_services(controller.DEPENDENCIES) == dependencies
    assert controller.private_hashes() == hashes
    assert not any(c[0] == "docker" and "commit" in c for c in rig.calls)
    assert not any(".Config.Env" in str(c) for c in rig.calls)
    output = capsys.readouterr().out
    for name in (
        "git_fetch",
        "rollback_image",
        "checkout",
        "target_build",
        "vasa_update",
        "health",
    ):
        assert mode.upper() + "_STAGE=" + name in output
    assert FAKE_KEY not in output


@pytest.mark.parametrize("mode", ["bootstrap", "deploy"])
@pytest.mark.parametrize("failure", ["fail_rollback_build", "fail_rollback_inspect"])
def test_failed_rollback_acquisition_never_changes_checkout_or_running_services(
    rig, mode, failure, capsys
):
    rig.image_available = False
    setattr(rig, failure, True)
    if mode == "deploy":
        rig.containers["voice"] = item("f")
    before = copy.deepcopy(rig.containers)
    hashes = controller.private_hashes()
    with pytest.raises(controller.Refusal):
        getattr(controller, mode)(TARGET, controller.BRANCH, PREVIOUS)
    assert rig.current == PREVIOUS and rig.containers == before
    assert rig.tags["vasa-app:pinned"] == OLD_IMAGE
    assert controller.private_hashes() == hashes
    assert not any(
        c[:2]
        in (
            ("git", "checkout"),
            ("git", "pull"),
            ("git", "reset"),
            ("compose", "up"),
            ("docker", "container"),
        )
        for c in rig.calls
    )
    assert not any(c[0] == "docker" and "commit" in c for c in rig.calls)
    output = capsys.readouterr().out
    assert mode.upper() + "_STAGE=rollback_image" in output
    assert mode.upper() + "_STAGE=checkout" not in output
    assert FAKE_KEY not in output


@pytest.mark.parametrize("mode", ["bootstrap", "deploy"])
def test_rollback_restores_verified_fallback_image_after_target_start_failure(rig, mode, capsys):
    rig.image_available = False
    if mode == "deploy":
        rig.containers["voice"] = item("f")
        rig.fail_up_once = True
    else:
        rig.fail_voice = True
    dependencies = controller.snapshot_services(controller.DEPENDENCIES)
    hashes = controller.private_hashes()
    with pytest.raises(controller.Refusal):
        getattr(controller, mode)(TARGET, controller.BRANCH, PREVIOUS)
    assert rig.current == PREVIOUS
    assert rig.tags["vasa-app:pinned"] == ROLLBACK_IMAGE
    assert rig.containers["vasa"][1]["image"] == ROLLBACK_IMAGE
    if mode == "deploy":
        assert rig.containers["voice"][1]["image"] == ROLLBACK_IMAGE
    else:
        assert "voice" not in rig.containers
    assert controller.snapshot_services(controller.DEPENDENCIES) == dependencies
    assert controller.private_hashes() == hashes
    output = capsys.readouterr().out
    marker = "VASA_BOOTSTRAP_ROLLBACK_OK" if mode == "bootstrap" else "VASA_ROLLBACK_OK"
    assert marker in output and FAKE_KEY not in output
    assert mode.upper() + "_STAGE=rollback_health" in output
    assert not any(c[0] == "docker" and "commit" in c for c in rig.calls)
    for path in (controller.ROOT / ".local").glob("actions-*.json"):
        assert FAKE_KEY not in path.read_text()


@pytest.mark.parametrize("mode", ["bootstrap", "deploy"])
def test_target_build_failure_leaves_original_containers_running_after_source_fallback(
    rig, mode, capsys
):
    rig.image_available = False
    rig.fail_build = True
    if mode == "deploy":
        rig.containers["voice"] = item("f")
    before = copy.deepcopy(rig.containers)
    with pytest.raises(controller.Refusal):
        getattr(controller, mode)(TARGET, controller.BRANCH, PREVIOUS)
    assert rig.current == PREVIOUS and rig.containers == before
    assert rig.tags["vasa-app:pinned"] == ROLLBACK_IMAGE
    assert not any(c[:2] == ("compose", "up") for c in rig.calls)
    marker = "VASA_BOOTSTRAP_ROLLBACK_OK" if mode == "bootstrap" else "VASA_ROLLBACK_OK"
    assert marker in capsys.readouterr().out


def test_rollback_build_overrides_only_image_and_reuses_compose_inputs(monkeypatch):
    calls = []
    tag = "vasa-app:bootstrap-rollback-" + PREVIOUS
    monkeypatch.setattr(
        controller, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or ""
    )
    controller.compose("build", "vasa", timeout=900, image_override=tag)
    args, kwargs = calls[0]
    assert args == (
        "docker",
        "compose",
        "--project-name",
        "vasa-vps",
        "--env-file",
        ".local/vps.env",
        "-f",
        "deploy/compose.yaml",
        "-f",
        "-",
        "--profile",
        "voice",
        "build",
        "vasa",
    )
    assert json.loads(kwargs["input_text"]) == {"services": {"vasa": {"image": tag}}}
    assert kwargs["timeout"] == 900
    assert FAKE_KEY not in kwargs["input_text"]


def test_stage_failure_diagnostic_does_not_include_subprocess_output(monkeypatch, capsys):
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=FAKE_KEY, stderr=FAKE_KEY),
    )
    controller.stage("BOOTSTRAP", "rollback_image")
    with pytest.raises(controller.Refusal) as error:
        controller.run("docker", "build")
    assert "BOOTSTRAP_STAGE=rollback_image" in str(error.value)
    assert FAKE_KEY not in str(error.value) + capsys.readouterr().out


def test_compose_override_is_passed_to_subprocess_stdin_without_environment_values(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *args, **kwargs: (
            calls.append((args, kwargs)) or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    tag = "vasa-app:bootstrap-rollback-" + PREVIOUS
    controller.compose("build", "vasa", image_override=tag)
    _, kwargs = calls[0]
    assert "stdin" not in kwargs
    assert json.loads(kwargs["input"]) == {"services": {"vasa": {"image": tag}}}
    assert "env" not in kwargs


def test_rollback_helper_refuses_unrelated_image_tags_before_any_commands(rig):
    with pytest.raises(controller.Refusal, match="Invalid VASA rollback image target"):
        controller.acquire_rollback_image(OLD_IMAGE, PREVIOUS, "unrelated-app:latest")
    assert rig.calls == []


def test_failed_bootstrap_reports_target_voice_markers_before_removal_and_git_rollback(
    rig,
    monkeypatch,
    capsys,
):
    rig.fail_voice = True
    monkeypatch.setattr(controller, "diagnostics", rig.original_diagnostics)

    def logs(cid, *, since=None):
        if cid != "f" * 64:
            return ""
        assert rig.current == TARGET
        assert rig.containers["voice"][1]["image"] == NEW_IMAGE
        rig.calls.append(("target_voice_logs", cid, rig.current))
        return (
            "VOICE_STARTUP_STAGE=llm_provider\nVOICE_STARTUP_FAILED=llm_provider\n"
            "VOICE_STARTUP_ERROR=invalid_configuration\n"
            + FAKE_KEY
            + "\nAuthorization: Bearer private-header\nhttps://user:password@example.invalid"
        )

    monkeypatch.setattr(controller, "read_container_logs", logs)
    with pytest.raises(controller.Refusal, match="Bootstrap failed"):
        controller.bootstrap(TARGET, controller.BRANCH, PREVIOUS)
    output = capsys.readouterr().out
    assert output.index("VOICE_STARTUP_FAILED=llm_provider") < output.index(
        "BOOTSTRAP_STAGE=rollback\n"
    )
    assert "VASA_BOOTSTRAP_ROLLBACK_OK" in output
    for secret in (FAKE_KEY, "private-header", "https://user:password@example.invalid"):
        assert secret not in output
    capture = rig.calls.index(("target_voice_logs", "f" * 64, TARGET))
    removal = rig.calls.index(("docker", "container", "rm", "--force", "f" * 64))
    reset = rig.calls.index(("git", "reset", "--hard", PREVIOUS))
    assert capture < removal < reset

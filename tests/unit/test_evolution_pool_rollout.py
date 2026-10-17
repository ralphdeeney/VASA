"""Fail-closed maintenance probes and private Actions payload regression checks."""

from types import SimpleNamespace

import pytest

from deploy import actions_evolution_payload as payload
from deploy import actions_evolution_pool as pool


@pytest.mark.parametrize("code", [0, 1])
def test_probe_never_emits_arbitrary_output(code, capsys):
    secret = "Authorization: Bearer private-secret"
    ns = {
        "container": lambda _: ("owned-vasa", {}),
        "capture": lambda *a, **k: SimpleNamespace(
            returncode=code,
            stdout=secret + "\nEVOLUTION_CALL_GATE_DB_ACTIVE=0\nEVOLUTION_CALL_GATE_OK\n",
        ),
    }
    if code:
        with pytest.raises(pool.Deferred):
            pool.emit_probe(ns, "source", "EVOLUTION_CALL_GATE_OK")
    else:
        pool.emit_probe(ns, "source", "EVOLUTION_CALL_GATE_OK")
    output = capsys.readouterr().out
    assert secret not in output
    assert "EVOLUTION_CALL_GATE_DB_ACTIVE=0" in output


@pytest.mark.parametrize(
    "row,refused",
    [
        ("", False),
        (" 0: 0B00007F:1234 00000000:0000 07", False),
        (" 0: 00000000:1234 00000000:0000 07", True),
        ("malformed", True),
    ],
)
def test_media_socket_inspection_fails_closed(row, refused):
    ns = {
        "container": lambda _: ("owned-evolution", {}),
        "capture": lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="sl local_address rem_address st\n" + row
        ),
    }
    if refused:
        with pytest.raises(pool.Deferred):
            pool.udp_gate(ns)
    else:
        pool.udp_gate(ns)


def test_payload_is_compilable_and_contains_only_reviewed_sources():
    source = payload.build()
    compile(source, "payload", "exec")
    assert "evolution_check" in source
    assert "evolution_deploy" in source
    assert "EVOLUTION_POOL_ROLLOUT_FAILED" in source
    assert "docker commit" not in source


def test_targeted_compose_rejects_untrusted_image(tmp_path):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    calls = []
    ns = {
        "require": require,
        "ROOT": tmp_path,
        "PROJECT": "vasa-vps",
        "run": lambda *a, **k: calls.append((a, k)),
    }
    with pytest.raises(ValueError):
        pool.compose_evolution(ns, "untrusted:latest", "up")
    assert not calls
    pool.compose_evolution(ns, "vasa-evolution:pool-" + "a" * 40, "up", "--no-deps", "evolution")
    assert calls[0][0][-3:] == ("up", "--no-deps", "evolution")
    assert "down" not in calls[0][0]


def test_evolution_modes_do_not_require_application_migration_approval():
    from pathlib import Path

    script = Path("deploy/actions-ssh.sh").read_text()
    approval = script.split("VASA_MIGRATION_SQL_SHA256=${VASA_MIGRATION_SQL_SHA256:-}")[1]
    approval = approval.split('[[ "$VASA_RECOVERY" == none || (')[0]
    assert 'if [[ "$VASA_RECOVERY" == activate ]]; then' in approval
    assert "evolution_" not in approval


@pytest.mark.parametrize("available,build_failed", [(True, False), (False, False), (False, True)])
def test_rollback_image_acquisition_never_mutates_running_services(
    tmp_path, capsys, available, build_failed
):
    commands = []
    image = "sha256:" + "b" * 64
    fallback = "sha256:" + "c" * 64

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("docker", "build") and build_failed:
            raise ValueError("private-build-output")
        if args[:3] == ("docker", "image", "inspect"):
            return image if available else fallback
        return ""

    ns = {
        "capture": lambda *a, **k: SimpleNamespace(returncode=0 if available else 1, stdout=image),
        "run": run,
        "require": require,
        "assert_unchanged": lambda before: commands.append(("unchanged",)),
    }
    before = {"evolution": {"image": image}}
    if build_failed:
        with pytest.raises(ValueError):
            pool.acquire_rollback(ns, before, tmp_path, "vasa-evolution:rollback-" + "a" * 40)
    else:
        actual = pool.acquire_rollback(ns, before, tmp_path, "vasa-evolution:rollback-" + "a" * 40)
        assert actual == (image if available else fallback)
        assert commands[-1] == ("unchanged",)
    assert not any(
        "compose" in command or "pause" in command or "commit" in command for command in commands
    )
    if not available:
        assert "--rollback-source" in commands[0]
    assert "private-build-output" not in capsys.readouterr().out

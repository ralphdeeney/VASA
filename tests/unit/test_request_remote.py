"""Private request receipts prevent repeated mutation and hide failure details."""

import hashlib
import json

import pytest

from deploy import request_remote as subject

ID = "6e1328c2-3554-4c2d-8153-5639304a6b18"
TRIGGER = "a" * 40


def request(operation="application_check"):
    return {
        "request_id": ID,
        "target_commit": "b" * 40,
        "expires_at": "2099-01-01T00:00:00Z",
        "operation": operation,
        "expected_markers": ["VASA_VPS_CONNECTIVITY_OK"],
    }


def setup(tmp_path, fail=None):
    (tmp_path / ".local").mkdir(exist_ok=True)
    calls = []

    def invoke(name):
        def run(*args):
            calls.append(name)
            if name == fail:
                raise RuntimeError("Authorization: Bearer SUPERSECRET")
            return {}

        return run

    ns = {
        "ROOT": tmp_path,
        "DEPENDENCIES": ["postgres", "redis", "evolution"],
        "SERVICES": ["vasa", "voice"],
        "preflight": invoke("preflight"),
        "snapshot_services": invoke("snapshot"),
        "health": invoke("health"),
        "private_hashes": lambda: {"runtime": "hash"},
        "assert_unchanged": invoke("unchanged"),
        "container": lambda name: ("container", {"image": "verified-image"}),
        "git": lambda *args: TRIGGER if "origin/build/vasa-foundation" in args else "old",
        "deploy": invoke("deploy"),
    }
    return ns, calls


def receipt(tmp_path, value, state):
    directory = tmp_path / ".local/deployment-requests"
    directory.mkdir(parents=True, mode=0o700)
    subject.save(
        directory / (ID + ".json"),
        {
            "digest": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
            "trigger_sha": TRIGGER,
            "state": state,
        },
    )


def test_completed_request_does_not_repeat_operation(tmp_path, capsys):
    value = request()
    receipt(tmp_path, value, "SUCCEEDED")
    ns, calls = setup(tmp_path)
    assert subject.execute(ns, value, TRIGGER, {}, {}) == 0
    assert calls == ["preflight", "health"]
    assert "VASA_REQUEST_ALREADY_SUCCEEDED" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["DEPLOYING", "ROLLBACK", "FAILED"])
def test_uncertain_mutation_is_not_replayed(tmp_path, state, capsys):
    value = request("application_deploy")
    receipt(tmp_path, value, state)
    ns, calls = setup(tmp_path)
    assert subject.execute(ns, value, TRIGGER, {}, {}) == 2
    assert calls == ["preflight"]
    assert "uncertain_or_failed_attempt" in capsys.readouterr().out


def test_changed_receipt_identity_is_refused(tmp_path):
    value = request()
    receipt(tmp_path, value, "SUCCEEDED")
    value["operation"] = "application_deploy"
    ns, calls = setup(tmp_path)
    with pytest.raises(subject.GateBlocked):
        subject.execute(ns, value, TRIGGER, {}, {})
    assert calls == ["preflight"]


def test_health_failure_is_fixed_marker_not_exception_text(tmp_path, capsys):
    ns, calls = setup(tmp_path, fail="health")
    assert subject.execute(ns, request(), TRIGGER, {}, {}) == 2
    output = capsys.readouterr().out
    assert "SUPERSECRET" not in output
    assert "Authorization" not in output
    assert "VASA_REQUEST_BLOCKED=safety_or_health_gate" in output
    path = tmp_path / ".local/deployment-requests" / (ID + ".json")
    assert subject.read(path)["state"] == "BLOCKED"


def test_successful_check_records_private_receipt_and_all_health(tmp_path):
    ns, calls = setup(tmp_path)
    assert subject.execute(ns, request(), TRIGGER, {}, {}) == 0
    assert calls == ["preflight", "snapshot", "health"]
    path = tmp_path / ".local/deployment-requests" / (ID + ".json")
    assert path.stat().st_mode & 0o077 == 0
    assert subject.read(path)["state"] == "SUCCEEDED"


def test_unknown_operation_never_executes_commands(tmp_path, capsys):
    ns, calls = setup(tmp_path)
    assert subject.execute(ns, request("shell"), TRIGGER, {}, {}) == 2
    assert calls == ["preflight"]
    assert "safety_or_health_gate" in capsys.readouterr().out


def test_unsafe_receipt_permissions_are_rejected(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(subject.GateBlocked):
        subject.read(path)


@pytest.mark.parametrize("same_owner", [True, False])
def test_consumed_maintenance_grant_cannot_authorize_a_new_attempt(tmp_path, same_owner):
    ns, calls = setup(tmp_path)
    directory = tmp_path / ".local/deployment-requests"
    directory.mkdir(mode=0o700)
    subject.save(
        directory / "grant-evolution-pool-2026-10-17.json",
        {"request_id": ID if same_owner else "another-request", "trigger_sha": TRIGGER},
    )
    mutations = []
    evolution = {"run": lambda *args: mutations.append(args[2]) or 0}
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    try:
        outcome = subject.execute(
            ns, request("evolution_pool_rollout"), TRIGGER, evolution, sources
        )
    except subject.GateBlocked:
        outcome = 2
    assert outcome == 2
    assert True not in mutations


def test_preflight_failure_never_writes_ledger_or_starts_mutation(tmp_path):
    ns, calls = setup(tmp_path, fail="preflight")
    with pytest.raises(RuntimeError):
        subject.execute(ns, request("application_deploy"), TRIGGER, {}, {})
    assert calls == ["preflight"]
    assert not (tmp_path / ".local/deployment-requests").exists()


def interrupted(tmp_path, value):
    receipt(tmp_path, value, "DEPLOYING")
    path = tmp_path / ".local/deployment-requests" / (ID + ".json")
    previous = subject.read(path)
    previous.update(
        before={"evolution": {"image": "old"}, "vasa": {"image": "app"}},
        private_hashes={"runtime": "hash"},
    )
    subject.save(path, previous)
    subject.save(
        tmp_path / ".local/actions-evolution-pool.json",
        {"status": "healthy", "target_sha": TRIGGER, "image": "verified-image"},
    )
    return path


def test_interrupted_success_resumes_by_verification_without_mutating(tmp_path, capsys):
    value = request("evolution_pool_rollout")
    path = interrupted(tmp_path, value)
    ns, calls = setup(tmp_path)
    evolution = {"public_health": lambda: calls.append("public_health")}
    assert subject.execute(ns, value, TRIGGER, evolution, {}) == 0
    assert calls == ["preflight", "health", "unchanged", "public_health"]
    assert subject.read(path)["state"] == "SUCCEEDED"
    assert "VASA_REQUEST_RESUMED_VERIFIED" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["image", "private_hash", "target", "missing"])
def test_interrupted_receipt_must_match_live_state(tmp_path, change):
    value = request("evolution_pool_rollout")
    path = interrupted(tmp_path, value)
    ns, calls = setup(tmp_path)
    if change == "image":
        ns["container"] = lambda name: ("container", {"image": "unexpected"})
    elif change == "private_hash":
        ns["private_hashes"] = lambda: {"runtime": "changed"}
    elif change == "target":
        subject.save(
            tmp_path / ".local/actions-evolution-pool.json",
            {"status": "healthy", "target_sha": "c" * 40, "image": "verified-image"},
        )
    else:
        (tmp_path / ".local/actions-evolution-pool.json").unlink()
    assert subject.execute(ns, value, TRIGGER, {}, {}) == 2
    assert "deploy" not in calls
    assert subject.read(path)["state"] == "DEPLOYING"


def test_active_call_defers_without_consuming_maintenance_grant(tmp_path):
    ns, calls = setup(tmp_path)
    attempts = []
    evolution = {"run": lambda *args: attempts.append(args[2]) or 2}
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    assert subject.execute(ns, request("evolution_pool_rollout"), TRIGGER, evolution, sources) == 2
    assert attempts == [False]
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()


def test_backup_failure_is_a_hard_stop_without_consuming_grant(tmp_path, capsys):
    ns, calls = setup(tmp_path)
    attempts = []

    def run(*args):
        attempts.append(args[2])
        if args[2]:
            args[0]["request_stage"]("backup")
            raise RuntimeError("backup failed: SECRET")
        return 0

    evolution = {"run": run}
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    value = request("evolution_pool_rollout")
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert attempts == [False, True]
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()
    assert "SECRET" not in capsys.readouterr().out


def test_failure_after_production_admission_hook_consumes_grant_and_cannot_retry(tmp_path):
    ns, calls = setup(tmp_path)
    attempts = []

    def run(*args):
        attempts.append(args[2])
        if args[2]:
            args[0]["before_evolution_mutation"]()
            raise RuntimeError("failure after admission paused")
        return 0

    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    value = request("evolution_pool_rollout")
    evolution = {"run": run}
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert attempts == [False, True]
    assert (tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json").exists()


def test_reversible_preparation_failure_can_resume_without_consuming_grant(tmp_path):
    ns, calls = setup(tmp_path)
    attempts = []

    def run(*args):
        attempts.append(args[2])
        if args[2]:
            raise RuntimeError("target build failed before any production mutation")
        return 0

    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    value = request("evolution_pool_rollout")
    evolution = {"run": run}
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert subject.execute(ns, value, TRIGGER, evolution, sources) == 2
    assert attempts == [False, True, False, True]
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()
    ledger = tmp_path / ".local/deployment-requests" / (ID + ".json")
    assert subject.read(ledger)["state"] == "BLOCKED"


def test_expired_request_never_reaches_remote_preflight(tmp_path):
    ns, calls = setup(tmp_path)
    value = request()
    value["expires_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(subject.GateBlocked):
        subject.execute(ns, value, TRIGGER, {}, {})
    assert calls == []


def test_branch_superseded_during_preparation_cannot_consume_grant(tmp_path):
    ns, calls = setup(tmp_path)
    ns["git"] = lambda *args: "c" * 40

    def run(*args):
        if args[2]:
            args[0]["before_evolution_mutation"]()
        return 0

    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    assert (
        subject.execute(ns, request("evolution_pool_rollout"), TRIGGER, {"run": run}, sources) == 2
    )
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()


def test_expiry_is_rechecked_after_preparation_before_mutation(tmp_path, monkeypatch):
    ns, calls = setup(tmp_path)

    def stale(_):
        raise subject.GateBlocked()

    def run(*args):
        if args[2]:
            monkeypatch.setattr(subject, "ensure_current", stale)
            args[0]["before_evolution_mutation"]()
        return 0

    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    assert (
        subject.execute(ns, request("evolution_pool_rollout"), TRIGGER, {"run": run}, sources) == 2
    )
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()


def test_evolution_check_reports_public_gate_failure_without_mutation(tmp_path, capsys):
    ns, calls = setup(tmp_path)

    def public_health():
        print("EVOLUTION_PUBLIC_FAILURE=certificate")
        raise RuntimeError("private network exception")

    evolution = {"run": lambda *args: 0, "public_health": public_health}
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    assert subject.execute(ns, request("evolution_check"), TRIGGER, evolution, sources) == 2
    assert calls == ["preflight", "health"]
    output = capsys.readouterr().out
    assert "EVOLUTION_PUBLIC_FAILURE=certificate" in output
    assert "private network exception" not in output
    assert "VASA_REQUEST_STATE=SUCCEEDED" not in output

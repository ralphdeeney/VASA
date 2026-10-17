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
    assert calls == ["preflight", "snapshot", "health"]
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


@pytest.mark.parametrize("preflight", [0, 2])
def test_completed_evolution_check_requires_fresh_call_instance_and_public_gates(
    tmp_path, capsys, preflight
):
    value = request("evolution_check")
    value["expected_markers"] = ["EVOLUTION_POOL_PREFLIGHT_OK"]
    receipt(tmp_path, value, "SUCCEEDED")
    ns, calls = setup(tmp_path)
    evolution = {
        "run": lambda *args: preflight,
        "public_health": lambda: calls.append("public_health"),
    }
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "source")
    if preflight:
        with pytest.raises(subject.GateBlocked):
            subject.execute(ns, value, TRIGGER, evolution, sources)
        assert "EVOLUTION_POOL_PREFLIGHT_OK" not in capsys.readouterr().out
        assert calls == ["preflight"]
    else:
        assert subject.execute(ns, value, TRIGGER, evolution, sources) == 0
        assert calls == ["preflight", "health", "public_health"]


def test_completed_paid_smoke_is_not_recharged_or_reported_as_fresh(tmp_path, capsys):
    value = request("provider_smoke")
    value["expected_markers"] = ["LLM_SMOKE_OK", "DEEPGRAM_SMOKE_OK"]
    receipt(tmp_path, value, "SUCCEEDED")
    ns, calls = setup(tmp_path)
    ns["provider_smoke"] = lambda: pytest.fail("unauthorized extra API charge")
    with pytest.raises(subject.GateBlocked):
        subject.execute(ns, value, TRIGGER, {}, {})
    assert "SMOKE_OK" not in capsys.readouterr().out


def test_readonly_diagnostics_survive_public_failure_without_authorizing_rollout(tmp_path, capsys):
    ns, calls = setup(tmp_path)
    ns["event"] = calls.append
    ns["require"] = lambda condition, _: condition or pytest.fail("changed private files")
    sources = dict.fromkeys(["gate", "instances", "backups", "capacity"], "")
    sources["audit"] = 'def run(ns, evolution, sources): ns["event"]("audit")'
    sources["health_diagnostics"] = (
        "def run(vantage, include_private): return [vantage, include_private]\n"
        'def emit(records): print("DIAGNOSTIC_CAPTURED")'
    )

    def public():
        raise RuntimeError("Authorization: Bearer private-response")

    evolution = {
        "run": lambda *args: 0,
        "public_health": public,
        "capacity": lambda *args: calls.append("capacity"),
    }
    assert subject.execute(ns, request("evolution_check"), TRIGGER, evolution, sources) == 2
    assert calls == ["preflight", "health", "snapshot", "audit", "capacity", "unchanged"]
    output = capsys.readouterr().out
    assert "DIAGNOSTIC_CAPTURED" in output
    assert "VASA_RECOVERY_PRESERVATION_OK" in output
    assert "VASA_REQUEST_STATE=SUCCEEDED" not in output
    assert "private-response" not in output
    assert not (
        tmp_path / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
    ).exists()


def test_diagnostic_failure_still_checks_container_preservation(tmp_path, capsys):
    ns, calls = setup(tmp_path)
    ns["require"] = lambda condition, _: condition or pytest.fail("changed private files")
    sources = {"audit": 'def run(*args): raise RuntimeError("private-body")'}
    with pytest.raises(RuntimeError):
        subject.readonly_diagnostics(ns, {}, sources)
    assert calls == ["snapshot", "unchanged"]
    assert "private-body" not in capsys.readouterr().out


def test_renewed_grant_is_dormant_and_old_consumed_grant_remains_authoritative(tmp_path):
    from deploy.deployment_policy import RENEWED_EVOLUTION_GRANT

    assert RENEWED_EVOLUTION_GRANT is None
    ns, _ = setup(tmp_path)
    assert subject.renewed_prerequisite(ns, request(), tmp_path) == "evolution-pool-2026-10-17"


def test_renewed_grant_requires_fresh_matching_private_readiness_receipt(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    ns, _ = setup(tmp_path)
    now = datetime.now(UTC)
    pre = "11111111-1111-4111-8111-111111111111"
    grant = {
        "grant_id": "evolution-pool-renewed-test",
        "request_id": ID,
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "prerequisite_request_id": pre,
        "prerequisite_trigger_sha": TRIGGER,
        "source_manifest": {
            "docker/evolution-db-pool.patch": hashlib.sha256(b"exact\n").hexdigest()
        },
    }
    ns["approved_evolution_grant"] = grant
    value = request("evolution_pool_rollout")
    value["authorization"] = grant["grant_id"]
    evidence = {
        "state": "SUCCEEDED",
        "operation": "evolution_check",
        "trigger_sha": TRIGGER,
        "readiness_contract": "identified-health-v1",
        "public_health_verified": True,
        "completed_at": now.isoformat(),
    }
    directory = tmp_path / ".local/deployment-requests"
    directory.mkdir(mode=0o700)
    path = directory / (pre + ".json")
    subject.save(path, evidence)
    monkeypatch.setattr(
        subject.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"exact\n")
    )
    assert subject.renewed_prerequisite(ns, value, directory, TRIGGER) == grant["grant_id"]
    for key, bad in [
        ("state", "FAILED"),
        ("operation", "application_check"),
        ("trigger_sha", "c" * 40),
        ("public_health_verified", False),
        ("readiness_contract", "legacy"),
        ("completed_at", (now - timedelta(hours=13)).isoformat()),
        ("completed_at", (now + timedelta(hours=1)).isoformat()),
    ]:
        subject.save(path, dict(evidence, **{key: bad}))
        with pytest.raises(subject.GateBlocked):
            subject.renewed_prerequisite(ns, value, directory, TRIGGER)
    subject.save(path, evidence)
    monkeypatch.setattr(
        subject.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"changed\n")
    )
    with pytest.raises(subject.GateBlocked):
        subject.renewed_prerequisite(ns, value, directory, TRIGGER)


def test_evolution_deployment_receipt_is_append_only_private_and_exact(tmp_path):
    ns, _ = setup(tmp_path)
    directory = tmp_path / ".local/deployment-requests"
    directory.mkdir(mode=0o700)
    controller = {"status": "healthy", "target_sha": TRIGGER, "image": "sha256:" + "c" * 64}
    subject.save(tmp_path / ".local/actions-evolution-pool.json", controller)
    state = {
        "target_sha": "b" * 40,
        "completed_at": "2026-10-17T12:00:00Z",
        "before": {"evolution": {"image": "sha256:" + "d" * 64}},
    }
    subject.immutable_evolution_receipt(ns, directory, ID, TRIGGER, state)
    path = directory / (ID + ".deployment.json")
    assert path.stat().st_mode & 0o777 == 0o600
    saved = subject.read(path)
    assert saved["controller_receipt"] == controller
    assert saved["source_sha"] == "b" * 40
    with pytest.raises(FileExistsError):
        subject.immutable_evolution_receipt(ns, directory, ID, TRIGGER, state)
    assert subject.read(path) == saved
    controller["target_sha"] = "e" * 40
    subject.save(tmp_path / ".local/actions-evolution-pool.json", controller)
    with pytest.raises(subject.GateBlocked):
        subject.immutable_evolution_receipt(ns, directory, "different", TRIGGER, state)


def test_renewed_prerequisite_fetches_before_manifest_and_rejects_superseded_tip(tmp_path):
    ns, calls = setup(tmp_path)
    ns["approved_evolution_grant"] = {"prerequisite_request_id": ID}

    def git(*args):
        calls.append(args)
        return "changed-head" if args[0] == "rev-parse" else ""

    ns["git"] = git
    with pytest.raises(subject.GateBlocked):
        subject.renewed_prerequisite(ns, request(), tmp_path, TRIGGER)
    assert calls == [
        ("fetch", "origin", "build/vasa-foundation"),
        ("rev-parse", "origin/build/vasa-foundation"),
    ]

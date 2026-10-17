"""Private VPS request ledger around the existing guarded controllers (stdlib only)."""

import fcntl
import hashlib
import json
import os
import re
from datetime import UTC, datetime


class GateBlocked(Exception):
    pass


def save(path, value):
    temporary = path.with_suffix(".pending")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read(path):
    if path.is_symlink() or path.stat().st_size > 65536 or path.stat().st_mode & 0o077:
        raise GateBlocked()
    return json.loads(path.read_text())


def resume_verified(ns, request, previous, evolution):
    """Observe an already-written successful receipt; never repeat a mutation."""
    operation = request["operation"]
    if operation not in {"evolution_pool_rollout", "application_deploy"}:
        return False
    filename = (
        "actions-evolution-pool.json"
        if operation == "evolution_pool_rollout"
        else "actions-deployment.json"
    )
    receipt_path = ns["ROOT"] / ".local" / filename
    if not receipt_path.exists():
        return False
    receipt = read(receipt_path)
    if receipt.get("status") != "healthy" or receipt.get("target_sha") != previous["trigger_sha"]:
        return False
    if "before" not in previous or "private_hashes" not in previous:
        return False
    if ns["private_hashes"]() != previous["private_hashes"]:
        return False
    ns["health"]()
    if operation == "evolution_pool_rollout":
        if ns["container"]("evolution")[1]["image"] != receipt.get("image"):
            return False
        ns["assert_unchanged"]({k: v for k, v in previous["before"].items() if k != "evolution"})
        evolution["public_health"]()
    else:
        if ns["git"]("rev-parse", "HEAD") != previous["trigger_sha"]:
            return False
        ns["assert_unchanged"](
            {k: v for k, v in previous["before"].items() if k in ns["DEPENDENCIES"]}
        )
    return True


def ensure_current(request):
    try:
        expires = datetime.fromisoformat(request["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or datetime.now(UTC) >= expires:
            raise GateBlocked()
    except (KeyError, ValueError, TypeError):
        raise GateBlocked() from None


def execute(ns, request, trigger, evolution, sources):
    """No request text is evaluated as a command; dispatch is an exact allowlist."""
    ensure_current(request)
    ns["preflight"]()
    root = ns["ROOT"]
    local = root / ".local"
    if local.is_symlink() or local.stat().st_uid != os.getuid():
        raise GateBlocked()
    directory = local / "deployment-requests"
    if directory.is_symlink():
        raise GateBlocked()
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise GateBlocked()
    identifier = request["request_id"]
    if re.fullmatch(r"[a-f0-9-]{36}", identifier) is None:
        raise GateBlocked()
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    path = directory / (identifier + ".json")
    descriptor = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = read(path) if path.exists() else None
        if previous:
            if previous["digest"] != digest or previous["trigger_sha"] != trigger:
                raise GateBlocked()
            if previous["state"] == "SUCCEEDED":
                # Fresh verification, no repeated deployment or stale-image success.
                if request["operation"] in {"evolution_pool_rollout", "application_deploy"}:
                    if not resume_verified(ns, request, previous, evolution):
                        raise GateBlocked()
                else:
                    ns["health"]()
                print("VASA_REQUEST_ALREADY_SUCCEEDED", flush=True)
                for marker in request["expected_markers"]:
                    print(marker, flush=True)
                return 0
            if previous["state"] == "DEPLOYING" and resume_verified(
                ns, request, previous, evolution
            ):
                previous["state"] = "SUCCEEDED"
                save(path, previous)
                print("VASA_REQUEST_RESUMED_VERIFIED", flush=True)
                for marker in request["expected_markers"]:
                    print(marker, flush=True)
                return 0
            if previous["state"] in {"DEPLOYING", "ROLLBACK", "FAILED"}:
                print("VASA_REQUEST_BLOCKED=uncertain_or_failed_attempt", flush=True)
                return 2
        state = {
            "digest": digest,
            "trigger_sha": trigger,
            "target_sha": request["target_commit"],
            "state": "PREFLIGHT",
        }
        save(path, state)
        print("VASA_REQUEST_STATE=PREFLIGHT", flush=True)
        operation = request["operation"]
        mutating = operation in {"application_deploy", "evolution_pool_rollout"}
        if mutating:
            state["before"] = ns["snapshot_services"](ns["DEPENDENCIES"] + ns["SERVICES"])
            state["private_hashes"] = ns["private_hashes"]()
            if operation == "evolution_pool_rollout":
                # Do not consume maintenance approval merely because calls are active.
                preflight = evolution["run"](
                    ns,
                    trigger,
                    False,
                    sources["gate"],
                    sources["instances"],
                    sources["backups"],
                    sources["capacity"],
                )
                if preflight:
                    print("VASA_REQUEST_BLOCKED=active_or_unknown_preflight", flush=True)
                    return 2

                grant = directory / "grant-evolution-pool-2026-10-17.json"
                if grant.exists():
                    print("VASA_REQUEST_BLOCKED=maintenance_grant_consumed", flush=True)
                    return 2

                def record_stage(stage):
                    state["stage"] = stage
                    save(path, state)

                ns["request_stage"] = record_stage

                def claim_mutation():
                    # Refresh expiry and branch immediately before production changes.
                    ensure_current(request)
                    ns["git"]("fetch", "origin", "build/vasa-foundation")
                    if ns["git"]("rev-parse", "origin/build/vasa-foundation") != trigger:
                        raise GateBlocked()
                    # Consume only after source/build/backups pass, immediately before
                    # admission is paused. Preparation failures may resume safely.
                    grant = directory / "grant-evolution-pool-2026-10-17.json"
                    if grant.exists():
                        print("VASA_REQUEST_BLOCKED=maintenance_grant_consumed", flush=True)
                        raise GateBlocked()
                    save(grant, {"request_id": identifier, "trigger_sha": trigger})
                    state["state"] = "DEPLOYING"
                    save(path, state)
                    print("VASA_REQUEST_STATE=DEPLOYING", flush=True)

                ns["before_evolution_mutation"] = claim_mutation
            else:
                state["state"] = "DEPLOYING"
                save(path, state)
                print("VASA_REQUEST_STATE=DEPLOYING", flush=True)
        try:
            if operation in {"evolution_check", "evolution_pool_rollout"}:
                result = evolution["run"](
                    ns,
                    trigger,
                    operation == "evolution_pool_rollout",
                    sources["gate"],
                    sources["instances"],
                    sources["backups"],
                    sources["capacity"],
                )
                if result:
                    raise GateBlocked()
                if operation == "evolution_check":
                    ns["health"]()
                    evolution["public_health"]()
            elif operation == "application_check":
                ns["snapshot_services"](ns["DEPENDENCIES"] + ns["SERVICES"])
                ns["health"]()
                print("VASA_VPS_CONNECTIVITY_OK", flush=True)
            elif operation == "application_deploy":
                branch, previous_sha = (
                    ns["git"]("branch", "--show-current"),
                    ns["git"]("rev-parse", "HEAD"),
                )
                ns["deploy"](trigger, branch, previous_sha)
            elif operation == "provider_smoke":
                # Trusted policy is supplied separately from request data. No paid
                # grant is currently configured, but the supported path is ready.
                approved = ns.get("approved_provider_grant")
                if not approved or request.get("authorization") != approved:
                    raise GateBlocked()
                ns["provider_smoke"]()
            else:
                raise GateBlocked()
            state["state"] = "VERIFYING"
            save(path, state)
            print("VASA_REQUEST_STATE=VERIFYING", flush=True)
            # Controller markers and health are authoritative, not a request's claims.
            print("VASA_SERVICES_HEALTH_OK", flush=True)
            state["state"] = "SUCCEEDED"
            save(path, state)
            print("VASA_REQUEST_STATE=SUCCEEDED", flush=True)
            return 0
        except BaseException:
            state["state"] = (
                "FAILED"
                if state["state"] == "DEPLOYING" or state.get("stage") == "backup"
                else "BLOCKED"
            )
            save(path, state)
            print("VASA_REQUEST_STATE=" + state["state"], flush=True)
            print("VASA_REQUEST_BLOCKED=safety_or_health_gate", flush=True)
            return 2

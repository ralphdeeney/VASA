"""Auditable push-driven delivery using GitHub state and the existing SSH bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from deploy.deployment_policy import BRANCH, EVOLUTION_PATCH_SHA256, EVOLUTION_UPSTREAM, REPOSITORY
from deploy.request_validator import RequestRejected, load_request, validate_request

STATES = {
    "REQUESTED",
    "VALIDATING",
    "TESTING",
    "READY",
    "PREFLIGHT",
    "DEPLOYING",
    "VERIFYING",
    "SUCCEEDED",
    "BLOCKED",
    "FAILED",
    "ROLLBACK",
}
FIXED_MARKERS = {
    "VASA_VPS_CONNECTIVITY_OK",
    "EVOLUTION_POOL_PREFLIGHT_OK",
    "VASA_DEPLOYMENT_OK",
    "VASA_EVOLUTION_POOL_DEPLOYMENT_OK",
    "VASA_EVOLUTION_POOL_ROLLBACK_OK",
    "VASA_EVOLUTION_POOL_ROLLBACK_FAILED",
    "EVOLUTION_CALL_GATE_OK",
    "EVOLUTION_REGISTERED_INSTANCES_OK",
    "EVOLUTION_REGISTERED_INSTANCES_FAILED",
    "EVOLUTION_BACKUP_RESTORE_OK",
    "EVOLUTION_PAIRING_AND_SCHEMA_PRESERVED",
    "EVOLUTION_ROLLBACK_IMAGE_VERIFIED",
    "EVOLUTION_PUBLIC_HEALTH_OK",
    "VASA_SERVICES_HEALTH_OK",
    "EVOLUTION_CONNECTIONS_BEFORE",
    "EVOLUTION_CONNECTIONS_AFTER",
    "VASA_REQUEST_ALREADY_SUCCEEDED",
    "VASA_REQUEST_RESUMED_VERIFIED",
    "LLM_SMOKE_OK",
    "DEEPGRAM_SMOKE_OK",
}
SAFE_VALUES = {
    "EVOLUTION_POOL_STAGE": {
        "rollback_image",
        "rollback_prepare",
        "rollback_build",
        "prepare_source",
        "target_build",
        "backup",
        "quiesce",
        "replace",
        "rollback",
    },
    "EVOLUTION_ROLLOUT_DEFERRED": {
        "call_or_instance_inspection",
        "media_inspection",
        "media_sockets",
        "active_or_unknown_after_quiesce",
    },
    "EVOLUTION_ROLLBACK_IMAGE": {"previous_source_build"},
    "EVOLUTION_INSTANCE_STAGE": {"database", "list", "paired_device", "status"},
    "EVOLUTION_INSTANCE_BASELINE": {"online", "offline"},
    "EVOLUTION_CALL_GATE_FAILED": {"active_calls", "inspection_failed"},
    "VASA_REQUEST_BLOCKED": {
        "uncertain_or_failed_attempt",
        "maintenance_grant_consumed",
        "safety_or_health_gate",
        "active_or_unknown_preflight",
        "remote_preflight",
    },
    "VASA_REQUEST_STATE": STATES,
}
MARKER_PATTERN = re.compile(
    r"(?:DB_(?:SOCKET_[A-Z_]+|CONFIG_MAX_CONNECTIONS)|EVOLUTION_(?:MEDIA_SOCKETS|"
    r"CALL_GATE_(?:DB|REDIS)_ACTIVE|INSTANCE_(?:REGISTERED_COUNT|UPSTREAM_COUNT|CONNECTED|LOGGED_IN)))"
    r"=[0-9]{1,10}\Z|EVOLUTION_DEPLOYED_SHA=[0-9a-f]{40}\Z|"
    r"EVOLUTION_POOL_FAILURE=(?:rollback_prepare|rollback_build|prepare_source|target_build):"
    r"(?:timeout|command_failed)\Z"
)


class Blocked(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def command(
    *args: str,
    timeout: int = 60,
    data: str | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=data,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
        check=False,
    )


def api(path: str, body: dict[str, Any] | None = None) -> Any:
    args = ["gh", "api", path]
    if body is not None:
        args += ["--method", "POST", "--input", "-"]
    try:
        result = command(*args, data=json.dumps(body) if body is not None else None)
        if result.returncode:
            raise Blocked("github_api_unavailable")
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise Blocked("github_api_unavailable") from None


def git(*args: str) -> str:
    result = command("git", *args)
    if result.returncode:
        raise Blocked("git_inspection_failed")
    return result.stdout.strip()


def ci_status(sha: str) -> str:
    data = api(
        f"repos/{REPOSITORY}/actions/workflows/verify.yml/runs?head_sha={sha}&event=push&per_page=100"
    )
    runs = [r for r in data["workflow_runs"] if r["head_sha"] == sha and r["head_branch"] == BRANCH]
    if not runs:
        return "pending"
    newest = max(runs, key=lambda value: value["id"])
    return str(newest["conclusion"]) if newest["status"] == "completed" else "pending"


def wait_ci(shas: list[str], *, timeout: int = 1200) -> None:
    deadline = time.monotonic() + timeout
    while True:
        statuses = [ci_status(sha) for sha in shas]
        if all(status == "success" for status in statuses):
            return
        if any(status not in {"success", "pending"} for status in statuses):
            raise Blocked("ci_failed")
        if time.monotonic() >= deadline:
            raise Blocked("ci_timeout")
        time.sleep(20)


def markers(stdout: str) -> list[str]:
    # All arbitrary command output (including stderr) is discarded.
    result = []
    for line in stdout.splitlines():
        key, _, value = line.partition("=")
        if len(line) <= 160 and (
            line in FIXED_MARKERS
            or MARKER_PATTERN.fullmatch(line)
            or value in SAFE_VALUES.get(key, set())
        ):
            result.append(line)
    return result


def transport_failure(result: subprocess.CompletedProcess[str]) -> str | None:
    # Retry only failures known to occur before an authenticated remote request.
    if "SSH host-key scan failed; no connection was attempted." in result.stdout:
        return "ssh_scan_unavailable"
    if "Host trust is missing or mismatched." in result.stdout:
        raise Blocked("ssh_host_trust")
    if result.returncode == 255 and not markers(result.stdout):
        # A dropped connection might have executed remotely: never blindly retry.
        raise Blocked("ssh_outcome_unknown")
    return None


def context(trigger: str) -> dict[str, Any]:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise Blocked("actions_runner_required")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    actor = os.environ.get("GITHUB_ACTOR", "")
    rerunner = os.environ.get("GITHUB_TRIGGERING_ACTOR", actor)
    if repository != REPOSITORY or actor != "ralphdeeney" or rerunner != actor:
        raise Blocked("unauthorized_actor")
    parent = git("rev-list", "--parents", "-n", "1", trigger).split()
    if len(parent) != 2 or parent[0] != trigger:
        raise Blocked("invalid_request_commit")
    permission = api(f"repos/{REPOSITORY}/collaborators/{actor}/permission")["permission"]
    head = api(f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")["object"]["sha"]
    changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", trigger).splitlines()
    return {
        "repository": repository,
        "branch": os.environ.get("GITHUB_REF_NAME", ""),
        "actor": actor,
        "actor_permission": permission,
        "trigger_sha": trigger,
        "parent_sha": parent[1],
        "changed_paths": changed,
        "head_sha": head,
        "source_ci": "success",
        "trigger_ci": "success",
        "completed_ids": [],
    }


class Journal:
    def __init__(self, request: dict[str, Any], trigger: str) -> None:
        self.request = request
        self.trigger = trigger
        self.digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        self.identifier: int | None = None
        self.previous = "REQUESTED"

    def claim(self) -> None:
        found = []
        for page in range(1, 6):
            records = api(
                f"repos/{REPOSITORY}/deployments?environment=staging&per_page=100&page={page}"
            )
            for record in records:
                payload = record.get("payload", {})
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("vasa_request_id") == self.request["request_id"]:
                    if payload.get("digest") != self.digest or record["sha"] != self.trigger:
                        raise Blocked("replayed_request")
                    found.append(record)
            if len(records) < 100:
                break
        else:
            raise Blocked("deployment_history_limit")
        if found:
            self.identifier = min(found, key=lambda record: record["id"])["id"]
            statuses = api(
                f"repos/{REPOSITORY}/deployments/{self.identifier}/statuses?per_page=100"
            )
            if statuses:
                match = re.fullmatch(
                    r"VASA_REQUEST_STATE=([A-Z]+)", statuses[0].get("description", "")
                )
                if match:
                    self.previous = match[1]
            if self.previous in {"FAILED", "ROLLBACK"}:
                raise Blocked("failed_attempt_requires_review")
            return
        created = api(
            f"repos/{REPOSITORY}/deployments",
            {
                "ref": self.trigger,
                "environment": "staging",
                "auto_merge": False,
                "required_contexts": [],
                "production_environment": False,
                "description": "Validated VASA deployment request",
                "payload": {
                    "vasa_request_id": self.request["request_id"],
                    "digest": self.digest,
                    "source_sha": self.request["target_commit"],
                    "schema_version": 1,
                },
            },
        )
        self.identifier = created["id"]
        self.state("REQUESTED")

    def state(self, state: str) -> None:
        if state not in STATES:
            raise Blocked("invalid_state")
        status = {
            "SUCCEEDED": "success",
            "BLOCKED": "failure",
            "FAILED": "failure",
            "ROLLBACK": "failure",
            "REQUESTED": "queued",
        }.get(state, "in_progress")
        api(
            f"repos/{REPOSITORY}/deployments/{self.identifier}/statuses",
            {
                "state": status,
                "description": "VASA_REQUEST_STATE=" + state,
                "auto_inactive": False,
                "log_url": f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            },
        )
        print("VASA_REQUEST_STATE=" + state, flush=True)


def run_request() -> int:
    journal = None
    try:
        trigger = os.environ.get("GITHUB_SHA", "")
        if re.fullmatch(r"[a-f0-9]{40}", trigger) is None:
            raise Blocked("invalid_commit")
        facts = context(trigger)
        paths = facts["changed_paths"]
        if len(paths) != 1 or not re.fullmatch(r"deploy/requests/[a-f0-9-]{36}\.json", paths[0]):
            raise Blocked("invalid_request_commit")
        request = load_request(paths[0])
        # Validate every security fact before recording or invoking a deployment.
        validate_request(request, facts)
        if request["operation"] == "evolution_pool_rollout":
            from scripts.prepare_evolution import COMMIT, POOL_PATCH_SHA256

            if COMMIT != EVOLUTION_UPSTREAM or POOL_PATCH_SHA256 != EVOLUTION_PATCH_SHA256:
                raise Blocked("incompatible_revision")
            if (
                hashlib.sha256(Path("docker/evolution-db-pool.patch").read_bytes()).hexdigest()
                != EVOLUTION_PATCH_SHA256
            ):
                raise Blocked("incompatible_patch")
        journal = Journal(request, trigger)
        journal.claim()
        if journal.previous == "SUCCEEDED":
            print("VASA_REQUEST_ALREADY_SUCCEEDED", flush=True)
            return 0
        journal.state("VALIDATING")
        journal.state("TESTING")
        wait_ci([facts["parent_sha"], trigger])
        facts["head_sha"] = api(f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")["object"]["sha"]
        validate_request(request, facts)
        journal.state("READY")
        environment = dict(os.environ)
        environment.update(
            VASA_REQUEST_FILE=paths[0],
            VASA_DEPLOY_MODE="check",
            VASA_RECOVERY="none",
            VASA_PROVIDER_SMOKE="false",
            VASA_RELEASE_SHA="",
            VASA_MIGRATION_SQL_SHA256="",
        )
        for attempt in range(3):
            if attempt:
                journal.state("READY")
                time.sleep((10, 30)[attempt - 1])
            # A queued newer commit supersedes this request before every attempt.
            head = api(f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")["object"]["sha"]
            if head != trigger:
                raise Blocked("superseded_request")
            journal.state("PREFLIGHT")
            try:
                result = command(
                    "bash", "deploy/actions-ssh.sh", timeout=3500, environment=environment
                )
            except subprocess.TimeoutExpired:
                raise Blocked("remote_outcome_unknown") from None
            safe = markers(result.stdout)
            for line in safe:
                if line in {"VASA_REQUEST_STATE=DEPLOYING", "VASA_REQUEST_STATE=VERIFYING"}:
                    journal.state(line.split("=")[1])
                print(line, flush=True)
            transient = transport_failure(result)
            if transient and attempt < 2:
                print("VASA_REQUEST_RETRY=" + str(attempt + 1), flush=True)
                continue
            if transient:
                raise Blocked("ssh_retry_limit")
            if any("ROLLBACK" in line for line in safe):
                journal.state("ROLLBACK")
                raise Blocked("rollback_performed")
            if result.returncode or not all(
                marker in safe for marker in request["expected_markers"]
            ):
                raise Blocked("remote_safety_or_health_gate")
            journal.state("VERIFYING")
            journal.state("SUCCEEDED")
            return 0
        raise Blocked("retry_limit")
    except (Blocked, RequestRejected) as error:
        if journal and journal.identifier is not None and error.code != "rollback_performed":
            try:
                journal.state("BLOCKED")
            except Exception:
                pass
        print("VASA_REQUEST_BLOCKED=" + error.code, flush=True)
        return 1
    except Exception:
        if journal and journal.identifier is not None:
            try:
                journal.state("FAILED")
            except Exception:
                pass
        print("VASA_REQUEST_BLOCKED=internal_error", flush=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-ci", metavar="SHA")
    args = parser.parse_args()
    if args.wait_ci:
        try:
            if re.fullmatch(r"[a-f0-9]{40}", args.wait_ci) is None:
                raise Blocked("invalid_commit")
            wait_ci([args.wait_ci])
            print("VASA_CI_OK", flush=True)
            return 0
        except Blocked as error:
            print("VASA_CI_BLOCKED=" + error.code, flush=True)
            return 1
    return run_request()


if __name__ == "__main__":
    raise SystemExit(main())

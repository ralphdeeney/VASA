"""Create one public audit request; Codex commits/pushes it separately from code."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from deploy.deployment_policy import BRANCH, OPERATIONS, active_evolution_grant


def create(operation: str, reason: str) -> Path:
    profile = dict(OPERATIONS[operation])
    if operation == "evolution_pool_rollout":
        profile["authorization"] = active_evolution_grant()["grant_id"]
    if profile["authorization"] is None:
        raise ValueError("authorization_required")
    result = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    if result.stdout:
        raise ValueError("clean_source_required")
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    if branch != BRANCH:
        raise ValueError("wrong_branch")
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    identifier = (
        str(active_evolution_grant()["request_id"])
        if operation == "evolution_pool_rollout"
        else str(uuid4())
    )
    now = datetime.now(UTC).replace(microsecond=0)
    expires = now + timedelta(hours=12)
    if operation == "evolution_pool_rollout" and "expires_at" in active_evolution_grant():
        deadline = datetime.fromisoformat(
            str(active_evolution_grant()["expires_at"]).replace("Z", "+00:00")
        )
        if deadline.tzinfo is None or deadline <= now:
            raise ValueError("authorization_expired")
        expires = min(expires, deadline)
    request = {
        "request_id": identifier,
        "operation": operation,
        "target_commit": target,
        "branch": BRANCH,
        "environment": "staging",
        "scope": profile["scope"],
        "policy": profile["policy"],
        "authorization": profile["authorization"],
        "reason": reason,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "expected_markers": profile["expected_markers"],
    }
    path = Path("deploy/requests") / (identifier + ".json")
    path.parent.mkdir(exist_ok=True)
    with path.open("x") as output:
        json.dump(request, output, indent=2)
        output.write("\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--reason", required=True, help="Public, credential-free audit reason")
    args = parser.parse_args()
    try:
        path = create(args.operation, args.reason)
    except (ValueError, OSError, subprocess.SubprocessError):
        print("VASA_REQUEST_CREATION_BLOCKED")
        return 1
    print("VASA_REQUEST_FILE=" + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

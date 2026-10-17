"""Create one public audit request; Codex commits/pushes it separately from code."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from deploy.deployment_policy import BRANCH, EVOLUTION_REQUEST_ID, OPERATIONS


def create(operation: str, reason: str) -> Path:
    profile = OPERATIONS[operation]
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
    identifier = EVOLUTION_REQUEST_ID if operation == "evolution_pool_rollout" else str(uuid4())
    now = datetime.now(UTC).replace(microsecond=0)
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
        "expires_at": (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
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

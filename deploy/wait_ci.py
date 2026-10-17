"""Stdlib-only CI gate for the existing normal deployment workflow."""

import json
import os
import re
import subprocess
import time


def main():
    sha = os.environ.get("GITHUB_SHA", "")
    if (
        os.environ.get("GITHUB_REPOSITORY") != "ralphdeeney/VASA"
        or re.fullmatch(r"[a-f0-9]{40}", sha) is None
    ):
        print("VASA_CI_BLOCKED=invalid_context")
        return 1
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "gh",
                "api",
                "repos/ralphdeeney/VASA/actions/workflows/verify.yml/runs"
                f"?head_sha={sha}&event=push&per_page=100",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            print("VASA_CI_BLOCKED=github_api_unavailable")
            return 1
        try:
            runs = [
                run
                for run in json.loads(result.stdout)["workflow_runs"]
                if run["head_sha"] == sha and run["head_branch"] == "build/vasa-foundation"
            ]
            latest = max(runs, key=lambda run: run["id"]) if runs else None
            if latest and latest["status"] == "completed":
                if latest["conclusion"] == "success":
                    print("VASA_CI_OK")
                    return 0
                print("VASA_CI_BLOCKED=ci_failed")
                return 1
        except (ValueError, KeyError, TypeError):
            print("VASA_CI_BLOCKED=invalid_ci_response")
            return 1
        time.sleep(20)
    print("VASA_CI_BLOCKED=ci_timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

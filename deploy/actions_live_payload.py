"""Build private SSH stdin for an Actions-only disposable acceptance task."""

import json
import os
import re
import stat
import sys
from pathlib import Path

DIAGNOSTIC_CODES = {
    "LIVE_SAAS_FIXTURE_DATABASE_CLASS": {
        "dbapi",
        "integrity",
        "interface",
        "operational",
        "programming",
    },
    "LIVE_SAAS_FIXTURE_DRIVER_CLASS": {
        "connection_failure",
        "connection_limit",
        "connection_missing",
        "duplicate_statement",
        "foreign_key",
        "insufficient_privilege",
        "interface",
        "invalid_catalog",
        "invalid_password",
        "unavailable",
        "unclassified",
        "undefined_column",
        "undefined_table",
        "unique_constraint",
        "unsupported_feature",
    },
    "LIVE_SAAS_FIXTURE_ERROR": {"invalid_configuration", "internal_error", "database_error"},
    "LIVE_SAAS_FIXTURE_SQLSTATE": {
        "08001",
        "08003",
        "08004",
        "08006",
        "0A000",
        "23503",
        "23505",
        "23514",
        "28P01",
        "3D000",
        "40001",
        "40P01",
        "42501",
        "42703",
        "42P01",
        "42P05",
        "53300",
        "57014",
        "57P03",
    },
    "LIVE_SAAS_FIXTURE_STAGE": {
        "cleanup_database",
        "cleanup_ownership",
        "cleanup_sessions",
        "database_commit",
        "database_connection",
        "database_open",
        "database_select_users",
        "discover_pending",
        "input",
        "pending_connection",
        "prepare_database",
        "settings",
    },
    "LIVE_SAAS_TASK_FAILED": {"preflight", "fixture", "health"},
}


def build(path: Path) -> str:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_size > 8192
    ):
        raise ValueError("private_input_required")
    data = json.loads(path.read_text())
    if (
        not isinstance(data, dict)
        or set(data) - {"action", "run", "password", "sessions"}
        or data.get("action") not in {"prepare", "cleanup", "cleanup_pending"}
        or (data.get("action") == "cleanup_pending" and set(data) != {"action"})
        or (
            data.get("action") != "cleanup_pending"
            and (
                not isinstance(data.get("run"), str)
                or re.fullmatch(r"[a-f0-9]{32}", data["run"]) is None
            )
        )
    ):
        raise ValueError("invalid_input")
    controller = Path("deploy/actions_vps.py").read_text()
    fixture = Path("scripts/live_saas_fixture.py").read_text()
    # All three values travel encrypted on SSH stdin, never argv or logs.
    return f"""import json
namespace = {{"__name__": "vasa_actions_acceptance"}}
exec(compile({controller!r}, "actions_vps", "exec"), namespace)
data = {data!r}
stage = "preflight"
try:
    namespace["preflight"]()
    if data["action"] == "prepare":
        stage = "health"
        namespace["health"]()
    stage = "fixture"
    cid, _ = namespace["container"]("vasa")
    result = namespace["capture"](
        "docker", "exec", "-i", cid, "python", "-c", {fixture!r},
        input_text=json.dumps(data), timeout=90,
    )
    expected = "LIVE_SAAS_FIXTURE_" + data["action"].upper() + "_OK"
    if result.returncode != 0 or result.stdout.strip() != expected:
        approved = {DIAGNOSTIC_CODES!r}
        for line in result.stdout.splitlines():
            name, separator, value = line.partition("=")
            if separator and value in approved.get(name, set()):
                print(line, flush=True)
        raise ValueError()
    print(expected, flush=True)
except BaseException:
    print("LIVE_SAAS_TASK_FAILED=" + stage, flush=True)
    raise SystemExit(1) from None
"""


def main() -> None:
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) != 2:
            raise ValueError("runner_required")
        sys.stdout.write(build(Path(sys.argv[1])))
    except Exception:
        print("Private acceptance payload construction failed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

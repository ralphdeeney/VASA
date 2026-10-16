"""Actions-only live acceptance orchestration; credentials remain in private files."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

PASS_STAGES = frozenset(
    {
        "login_session_persistence",
        "workspace_tenant_platform_boundaries",
        "admin_directory_audit",
        "mobile_desktop",
        "logout_revocation",
    }
)
FAIL_STAGES = frozenset(
    {
        "configuration",
        "login_0",
        "login_1",
        "tenant_boundaries",
        "admin",
        "responsive",
        "logout",
        "private_result",
        "internal",
    }
)


def execute(command: list[str], environment: dict[str, str], timeout: int):
    """Capture all child output; neither exceptions nor stderr are displayed."""
    try:
        return subprocess.run(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")


def safe_browser_markers(output: str) -> set[str]:
    allowed = set()
    for line in output.splitlines():
        if (
            line.startswith("LIVE_SAAS_PASS=")
            and line.removeprefix("LIVE_SAAS_PASS=") in PASS_STAGES
        ):
            allowed.add(line)
        elif (
            line.startswith("LIVE_SAAS_FAILED=")
            and line.removeprefix("LIVE_SAAS_FAILED=") in FAIL_STAGES
        ):
            allowed.add(line)
        elif line in {"LIVE_SAAS_EMAIL_FLOWS=blocked_smtp", "LIVE_SAAS_ACCEPTANCE_PARTIAL_OK"}:
            allowed.add(line)
    return allowed


def emit_fixture_failures(output: str) -> None:
    codes = {
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
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if line == "LIVE_SAAS_FIXTURE_FAILED" or (separator and value in codes.get(name, set())):
            print(line, flush=True)


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("LIVE_SAAS_RUNNER_FAILED=actions_required", flush=True)
        return 1
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    if not runner_temp.is_absolute() or not runner_temp.is_dir() or runner_temp.is_symlink():
        print("LIVE_SAAS_RUNNER_FAILED=private_directory", flush=True)
        return 1
    success = False
    cleanup_ok = False
    with tempfile.TemporaryDirectory(prefix="vasa-live-", dir=runner_temp) as directory:
        root = Path(directory)
        root.chmod(0o700)
        payload_file = root / "input.json"
        result_file = root / "result.json"
        payload = {
            "action": "cleanup_pending",
            "run": secrets.token_hex(16),
            "password": secrets.token_urlsafe(36),
        }
        fd = os.open(payload_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"action": "cleanup_pending"}, stream)
        environment = dict(os.environ)
        environment.update(
            VASA_LIVE_ACCEPTANCE_FILE=str(payload_file),
            VASA_DEPLOY_MODE="check",
            VASA_RECOVERY="none",
            VASA_PROVIDER_SMOKE="false",
        )
        try:
            pending = execute(["bash", "deploy/actions-ssh.sh"], environment, 180)
            if (
                pending.returncode != 0
                or "LIVE_SAAS_FIXTURE_CLEANUP_PENDING_OK" not in pending.stdout.splitlines()
            ):
                emit_fixture_failures(pending.stdout)
                print("LIVE_SAAS_RUNNER_FAILED=fixture_pending_cleanup", flush=True)
                return 1
            print("LIVE_SAAS_FIXTURE_CLEANUP_PENDING_OK", flush=True)
            payload["action"] = "prepare"
            payload_file.write_text(json.dumps(payload))
            prepared = execute(["bash", "deploy/actions-ssh.sh"], environment, 180)
            if (
                prepared.returncode != 0
                or "LIVE_SAAS_FIXTURE_PREPARE_OK" not in prepared.stdout.splitlines()
            ):
                emit_fixture_failures(prepared.stdout)
                print("LIVE_SAAS_RUNNER_FAILED=fixture_prepare", flush=True)
            else:
                print("LIVE_SAAS_FIXTURE_PREPARE_OK", flush=True)
                browser_environment = dict(environment)
                browser_environment.update(
                    VASA_LIVE_ACCEPTANCE_INPUT=str(payload_file),
                    VASA_LIVE_ACCEPTANCE_RESULT=str(result_file),
                )
                browser = execute(
                    ["node", "scripts/live_saas_acceptance.cjs"], browser_environment, 240
                )
                markers = safe_browser_markers(browser.stdout)
                for marker in sorted(markers - {"LIVE_SAAS_ACCEPTANCE_PARTIAL_OK"}):
                    print(marker, flush=True)
                required = {"LIVE_SAAS_PASS=" + stage for stage in PASS_STAGES}
                required.update(
                    {"LIVE_SAAS_EMAIL_FLOWS=blocked_smtp", "LIVE_SAAS_ACCEPTANCE_PARTIAL_OK"}
                )
                success = (
                    browser.returncode == 0
                    and required.issubset(markers)
                    and not any(marker.startswith("LIVE_SAAS_FAILED=") for marker in markers)
                )
                if not success:
                    print("LIVE_SAAS_RUNNER_FAILED=browser", flush=True)
        except Exception:
            print("LIVE_SAAS_RUNNER_FAILED=internal", flush=True)
        finally:
            sessions = []
            try:
                if (
                    result_file.is_file()
                    and not result_file.is_symlink()
                    and result_file.stat().st_size <= 8192
                ):
                    document = json.loads(result_file.read_text())
                    values = document.get("sessions", []) if isinstance(document, dict) else []
                    if isinstance(values, list) and len(values) <= 16:
                        sessions = [
                            v
                            for v in values
                            if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", v)
                        ]
            except (OSError, ValueError):
                pass
            payload["action"] = "cleanup"
            payload["sessions"] = sessions
            payload_file.write_text(json.dumps(payload))
            cleaned = execute(["bash", "deploy/actions-ssh.sh"], environment, 180)
            cleanup_ok = (
                cleaned.returncode == 0
                and "LIVE_SAAS_FIXTURE_CLEANUP_OK" in cleaned.stdout.splitlines()
            )
            if not cleanup_ok:
                emit_fixture_failures(cleaned.stdout)
            print(
                "LIVE_SAAS_FIXTURE_CLEANUP_OK"
                if cleanup_ok
                else "LIVE_SAAS_RUNNER_FAILED=fixture_cleanup",
                flush=True,
            )
    if success and cleanup_ok:
        print("LIVE_SAAS_ACCEPTANCE_PARTIAL_OK", flush=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

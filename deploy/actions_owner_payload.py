"""Trusted Actions owner setup; password travels only through private encrypted stdin."""

import json
import os
import re
import sys
from pathlib import Path


def build() -> str:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_ACTOR") != "ralphdeeney"
        or os.environ.get("GITHUB_REPOSITORY") != "ralphdeeney/VASA"
        or os.environ.get("GITHUB_REF") != "refs/heads/build/vasa-foundation"
        or os.environ.get("VASA_OWNER_PROVISION") != "true"
    ):
        raise ValueError("trusted_actions_required")
    password = os.environ.get("VASA_PLATFORM_ADMIN_PASSWORD", "")
    email = os.environ.get("VASA_OWNER_EMAIL", "")
    target = os.environ.get("VASA_OWNER_RELEASE", "")
    if not 8 <= len(password) <= 256 or len(password.encode()) > 1024:
        raise ValueError("secret_required")
    if len(email) > 254 or not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", email
    ):
        raise ValueError("invalid_input")
    if re.fullmatch(r"[a-f0-9]{40}", target) is None:
        raise ValueError("invalid_input")
    controller = Path("deploy/actions_vps.py").read_text()
    payload = json.dumps({"email": email, "password": password})
    verifier = Path("scripts/verify_platform_owner.py").read_text()
    return f"""import json, os, sys, time, hashlib
stage = "preflight"
try:
    if sys.argv[1] != "check" or sys.argv[3:5] != ["false", "none"]:
        raise ValueError()
    ns = {{"__name__": "vasa_owner_controller"}}
    exec(compile({controller!r}, "private_controller", "exec"), ns)
    ns["preflight"]()
    stage = "backup"
    ns["prepare_recovery"]({target!r}, exact_tip=False)
    root = ns["ROOT"]
    fd = os.open(root / ".local/actions-deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        ns["fcntl"].flock(lock, ns["fcntl"].LOCK_EX | ns["fcntl"].LOCK_NB)
        before = ns["snapshot_services"](ns["DEPENDENCIES"] + ns["SERVICES"])
        hashes = ns["private_hashes"]()
        git_state = ns["git"]("status", "--porcelain=v1", "--untracked-files=all")
        stage = "release"
        journal_path = root / ".local/actions-release.json"
        ns["require"](not journal_path.is_symlink() and journal_path.stat().st_uid == os.getuid()
            and journal_path.stat().st_mode & 0o077 == 0, "Private journal required.")
        journal = json.loads(journal_path.read_text())
        ns["require"](journal.get("status") == "active" and journal.get("active_sha") == {target!r}
            and all(before[s]["image"] == journal.get("active_image") for s in ns["SERVICES"]),
            "Active release differs.")
        stage = "backup"
        candidates = list((root / ".local/recovery-preparations").glob({target!r} + "-*.json"))
        ns["require"](bool(candidates), "Fresh backup receipt required.")
        receipt = max(candidates, key=lambda p: p.stat().st_mtime_ns)
        ns["require"](receipt.resolve().parent == root / ".local/recovery-preparations"
            and not receipt.is_symlink() and receipt.stat().st_uid == os.getuid()
            and receipt.stat().st_mode & 0o077 == 0
            and 0 <= time.time() - receipt.stat().st_mtime <= 3600,
            "Fresh backup receipt required.")
        prepared = json.loads(receipt.read_text())
        backup = root / prepared["backup"]
        ns["require"](prepared.get("target_sha") == {target!r}
            and prepared.get("restore_verified") is True
            and prepared.get("migration_clone_verified") is True
            and backup.resolve().parent == root / ".local/backups" and not backup.is_symlink()
            and backup.stat().st_uid == os.getuid() and backup.stat().st_mode & 0o077 == 0,
            "Verified private backup required.")
        with backup.open("rb") as stream:
            ns["require"](hashlib.file_digest(stream, "sha256").hexdigest()
                == prepared.get("backup_sha256"),
                "Backup checksum differs.")
        ns["health"]()
        stage = "provision"
        cid, _ = ns["container"]("vasa")
        try:
            result = ns["capture"]("docker", "exec", "-i", cid,
                "python", "-m", "vasa.saas.provision_owner",
                input_text={payload!r}, timeout=90)
            allowed = {{"PLATFORM_OWNER_PROVISIONED", "PLATFORM_OWNER_ALREADY_PROVISIONED"}}
            if result.returncode != 0 or result.stdout.strip() not in allowed:
                for line in result.stdout.splitlines():
                    if line in {{"PLATFORM_OWNER_PROVISION_FAILED=" + c for c in
                        ("environment_refused", "invalid_input", "owner_conflict",
                         "identity_refused", "internal_error")}}:
                        print(line, flush=True)
                raise ValueError()
            print(result.stdout.strip(), flush=True)
            stage = "login"
            checked = ns["capture"]("docker", "exec", "-i", cid,
                "python", "-c", {verifier!r}, input_text={payload!r}, timeout=90)
            if checked.returncode != 0 or checked.stdout.strip() != "PLATFORM_OWNER_LOGIN_OK":
                raise ValueError()
            print("PLATFORM_OWNER_LOGIN_OK", flush=True)
        finally:
            ns["assert_unchanged"](before)
            ns["require"](ns["private_hashes"]() == hashes and
                ns["git"]("status", "--porcelain=v1", "--untracked-files=all") == git_state,
                "Private/operator state changed.")
    print("VASA_PLATFORM_OWNER_SETUP_OK", flush=True)
except BaseException:
    print("PLATFORM_OWNER_SETUP_FAILED=" + stage, flush=True)
    raise SystemExit(1) from None
"""


def main() -> int:
    try:
        sys.stdout.write(build())
    except Exception:
        print("PLATFORM_OWNER_PRIVATE_INPUT_REQUIRED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

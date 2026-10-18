"""Actions-only secret payload: fixed private setup, encrypted SSH stdin, no argv key."""

import os
import re
import sys
from pathlib import Path


def build() -> str:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("VASA_RECOVERY") != "smtp_configure"
    ):
        raise ValueError("actions_required")
    key = os.environ.get("VASA_RELOOP_API_KEY", "")
    if re.fullmatch(r"[A-Za-z0-9_./:+-]{16,4096}", key) is None:
        raise ValueError("secret_required")
    controller = Path("deploy/actions_vps.py").read_text()
    helper = Path("scripts/configure_smtp.py").read_text()
    return f"""import sys
try:
    if sys.argv[1] != "check" or sys.argv[3:5] != ["false", "smtp_configure"]:
        raise ValueError()
    ns = {{"__name__": "vasa_private_smtp_controller"}}
    exec(compile({controller!r}, "private_controller", "exec"), ns)
    ns["preflight"]()
    root = ns["ROOT"]
    os = ns["os"]
    fd = os.open(root / ".local/actions-deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        ns["fcntl"].flock(lock, ns["fcntl"].LOCK_EX | ns["fcntl"].LOCK_NB)
        before = ns["snapshot_services"](ns["DEPENDENCIES"] + ns["SERVICES"])
        hashes = ns["private_hashes"]()
        state = ns["git"]("status", "--porcelain=v1", "--untracked-files=all")
        config = {{"__name__": "vasa_private_smtp_helper"}}
        exec(compile({helper!r}, "private_helper", "exec"), config)
        try:
            written = config["configure"](root, secret={key!r})
        finally:
            ns["assert_unchanged"](before)
            after = ns["private_hashes"]()
            ns["require"](
                all(after[k] == v for k, v in hashes.items() if k != ".local/smtp.env"),
                "Private state changed.",
            )
            ns["require"](
                ns["git"]("status", "--porcelain=v1", "--untracked-files=all") == state,
                "Operator state changed.",
            )
    marker = "WRITTEN" if written else "PRESENT"
    print("VASA_SMTP_PRIVATE_CONFIG_" + marker, flush=True)
    print("SMTP_MAILBOX_VERIFIED=false", flush=True)
except BaseException as error:
    code = "setup_unavailable"
    if "config" in globals() and isinstance(error, config.get("ConfigurationRefused", ValueError)):
        candidate = str(error)
        if candidate in config.get("FAILURE_CODES", set()):
            code = candidate
    print("SMTP_PRIVATE_CONFIG_FAILED=" + code, flush=True)
    raise SystemExit(1) from None
"""


def main() -> int:
    try:
        sys.stdout.write(build())
    except Exception:
        print("SMTP_GITHUB_SECRET_REQUIRED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

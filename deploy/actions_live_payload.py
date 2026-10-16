"""Build private SSH stdin for an Actions-only disposable acceptance task."""

import json
import os
import re
import stat
import sys
from pathlib import Path


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
        or data.get("action") not in {"prepare", "cleanup"}
        or not isinstance(data.get("run"), str)
        or re.fullmatch(r"[a-f0-9]{32}", data["run"]) is None
    ):
        raise ValueError("invalid_input")
    controller = Path("deploy/actions_vps.py").read_text()
    fixture = Path("scripts/live_saas_fixture.py").read_text()
    # All three values travel encrypted on SSH stdin, never argv or logs.
    return f"""import json
namespace = {{"__name__": "vasa_actions_acceptance"}}
exec(compile({controller!r}, "actions_vps", "exec"), namespace)
data = {data!r}
try:
    namespace["preflight"]()
    namespace["health"]()
    cid, _ = namespace["container"]("vasa")
    result = namespace["capture"](
        "docker", "exec", "-i", cid, "python", "-c", {fixture!r},
        input_text=json.dumps(data), timeout=90,
    )
    expected = "LIVE_SAAS_FIXTURE_" + data["action"].upper() + "_OK"
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise ValueError()
    print(expected, flush=True)
except BaseException:
    print("LIVE_SAAS_FIXTURE_FAILED", flush=True)
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

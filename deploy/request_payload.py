"""Serialize reviewed request/controller code to the existing encrypted SSH stdin."""

import sys
from pathlib import Path

from deploy.deployment_policy import OPERATIONS
from deploy.request_validator import load_request


def build(path: str) -> str:
    request = load_request(path)
    if Path(path).as_posix() != "deploy/requests/" + request["request_id"] + ".json":
        raise ValueError("invalid_request_path")
    files = {
        "controller": "deploy/actions_vps.py",
        "remote": "deploy/request_remote.py",
        "evolution": "deploy/actions_evolution_pool.py",
        "gate": "scripts/evolution_call_gate.py",
        "instances": "scripts/evolution_instance_check.py",
        "backups": "deploy/evolution_backups.py",
        "capacity": "deploy/actions_db_capacity.py",
        "health_diagnostics": "deploy/health_diagnostics.py",
        "audit": "deploy/recovery_audit.py",
    }
    sources = {key: Path(value).read_text() for key, value in files.items()}
    provider_grant = OPERATIONS["provider_smoke"]["authorization"]
    return f"""import sys
sources = {sources!r}
request = {request!r}
try:
    if sys.argv[1] != "check" or sys.argv[3] != "false" or sys.argv[4] != "none":
        raise ValueError()
    modules = {{}}
    for name in ("controller", "remote", "evolution"):
        module = {{"__name__": "vasa_request_" + name}}
        exec(compile(sources[name], name, "exec"), module)
        modules[name] = module
    modules["controller"]["approved_provider_grant"] = {provider_grant!r}
    result = modules["remote"]["execute"](modules["controller"], request, sys.argv[2],
        modules["evolution"], sources)
except BaseException:
    print("VASA_REQUEST_BLOCKED=remote_preflight", flush=True)
    raise SystemExit(2) from None
raise SystemExit(result)
"""


if __name__ == "__main__":
    print(build(sys.argv[1]))

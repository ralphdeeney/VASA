"""Assemble reviewed Evolution rollout code for encrypted Actions SSH stdin."""

from pathlib import Path


def build() -> str:
    files = {
        "controller": "deploy/actions_vps.py",
        "rollout": "deploy/actions_evolution_pool.py",
        "gate": "scripts/evolution_call_gate.py",
        "instances": "scripts/evolution_instance_check.py",
        "backups": "deploy/evolution_backups.py",
        "capacity": "deploy/actions_db_capacity.py",
    }
    values = {name: Path(path).read_text() for name, path in files.items()}
    return f"""import sys
namespace = {{"__name__": "vasa_evolution_controller"}}
exec(compile({values["controller"]!r}, "controller", "exec"), namespace)
rollout = {{"__name__": "vasa_evolution_rollout"}}
exec(compile({values["rollout"]!r}, "rollout", "exec"), rollout)
try:
    if (sys.argv[1] != "check" or sys.argv[3] != "false"
        or sys.argv[4] not in ("evolution_check", "evolution_deploy")):
        raise ValueError()
    result = rollout["run"](namespace, sys.argv[2], sys.argv[4] == "evolution_deploy",
        {values["gate"]!r}, {values["instances"]!r}, {values["backups"]!r}, {values["capacity"]!r})
except BaseException as error:
    print("EVOLUTION_POOL_ROLLOUT_FAILED", flush=True)
    raise SystemExit(1) from None
raise SystemExit(result)
"""


if __name__ == "__main__":
    print(build())

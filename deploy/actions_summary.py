"""Only allowlisted workflow metadata may reach the Actions summary."""

import os
import re
from pathlib import Path


def summary(environment: dict[str, str]) -> str:
    fields = {
        "Trigger": ("VASA_TRIGGER", {"push", "workflow_dispatch"}),
        "Mode": ("VASA_RESOLVED_MODE", {"check", "bootstrap", "deploy"}),
        "Provider smoke": ("VASA_SMOKE", {"true", "false"}),
        "Deployment result": ("VASA_RESULT", {"success", "failure", "cancelled", "skipped"}),
    }
    values = {}
    for label, (key, allowed) in fields.items():
        value = environment.get(key, "")
        values[label] = value if value in allowed else "invalid"
    sha = environment.get("VASA_TARGET_SHA", "")
    values["Target SHA"] = sha if re.fullmatch("[0-9a-f]{40}", sha) else "invalid"
    return (
        "\n".join(
            f"- {label}: {values[label]}"
            for label in ("Trigger", "Target SHA", "Mode", "Provider smoke", "Deployment result")
        )
        + "\n"
    )


if __name__ == "__main__":
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
        output.write(summary(dict(os.environ)))

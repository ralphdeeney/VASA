"""Maintenance-only pushes never replace the active application release."""

from fnmatch import fnmatchcase
from pathlib import Path

import pytest


def ignored(path: str) -> bool:
    workflow = Path(".github/workflows/vasa-vps-deploy.yml").read_text()
    section = workflow.split("    paths-ignore:\n", 1)[1].split("\npermissions:", 1)[0]
    patterns = [
        line.strip()[3:-1] for line in section.splitlines() if line.strip().startswith("- '")
    ]
    return any(fnmatchcase(path, pattern) for pattern in patterns)


@pytest.mark.parametrize(
    "path",
    [
        "deploy/actions_evolution_pool.py",
        "deploy/deployment_policy.py",
        "deploy/request_remote.py",
        "deploy/requests/example.json",
        "docs/health-recovery/README.md",
        "CURRENT_STATE.md",
        "tests/unit/test_identified_public_health.py",
        ".github/workflows/vasa-vps-deploy.yml",
    ],
)
def test_controller_only_push_uses_explicit_request(path):
    assert ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/vasa/voice_worker.py",
        "deploy/compose.yaml",
        "Dockerfile",
        "uv.lock",
        "pyproject.toml",
    ],
)
def test_runtime_push_preserves_normal_deploy(path):
    assert not ignored(path)

"""Request values remain data in the private reviewed SSH payload."""

import ast
from pathlib import Path

import pytest

from deploy import request_payload


def test_private_payload_is_valid_python_and_never_interpolates_reason_as_code(monkeypatch):
    identifier = "c5c21995-25a5-4933-9c6e-a19a815f520f"
    reason = "'); __import__('os').system('arbitrary-shell'); #"
    document = {"request_id": identifier, "operation": "application_check", "reason": reason}
    monkeypatch.setattr(request_payload, "load_request", lambda path: document)
    source = request_payload.build(f"deploy/requests/{identifier}.json")
    parsed = ast.parse(source)
    assignment = next(
        node
        for node in parsed.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "request"
    )
    assert ast.literal_eval(assignment.value)["reason"] == reason
    compile(source, "private-payload", "exec")


def test_payload_cannot_be_selected_from_an_unrelated_path(monkeypatch):
    monkeypatch.setattr(request_payload, "load_request", lambda path: {"request_id": "known"})
    with pytest.raises(ValueError, match="invalid_request_path"):
        request_payload.build("unrelated.json")


def test_request_only_push_cannot_select_normal_application_replacement():
    normal = Path(".github/workflows/vasa-vps-deploy.yml").read_text()
    request = Path(".github/workflows/vasa-deployment-request.yml").read_text()
    assert "paths-ignore:\n      - 'deploy/requests/**'" in normal
    assert "paths: ['deploy/requests/*.json']" in request
    assert "group: vasa-staging-vps" in normal and "group: vasa-staging-vps" in request
    assert "deployments: write" in request
    bridge = Path("deploy/actions-ssh.sh").read_text()
    assert "StrictHostKeyChecking=yes" in bridge
    assert "StrictHostKeyChecking=no" not in bridge

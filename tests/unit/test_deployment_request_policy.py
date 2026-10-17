from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from deploy.deployment_policy import EVOLUTION_REQUEST_ID, OPERATIONS
from deploy.request_validator import RequestRejected, load_request, validate_request

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
REQUEST_ID = "b0ead602-d4e2-41eb-a625-6d5f0d053889"


def request(operation="application_check"):
    policy = OPERATIONS[operation]
    return {
        "request_id": EVOLUTION_REQUEST_ID if operation == "evolution_pool_rollout" else REQUEST_ID,
        "operation": operation,
        "target_commit": "a" * 40,
        "branch": "build/vasa-foundation",
        "environment": "staging",
        "scope": policy["scope"],
        "policy": policy["policy"],
        "authorization": policy["authorization"] or "invented-grant",
        "expected_markers": deepcopy(policy["expected_markers"]),
        "reason": "Approved staging verification",
        "created_at": "2026-10-17T11:00:00Z",
        "expires_at": "2026-10-17T13:00:00Z",
    }


def context(document):
    return {
        "repository": "ralphdeeney/VASA",
        "branch": "build/vasa-foundation",
        "actor": "ralphdeeney",
        "actor_permission": "write",
        "trigger_sha": "b" * 40,
        "parent_sha": "a" * 40,
        "head_sha": "b" * 40,
        "changed_paths": [f"deploy/requests/{document['request_id']}.json"],
        "source_ci": "success",
        "trigger_ci": "success",
        "completed_ids": [],
    }


@pytest.mark.parametrize("operation", [x for x in OPERATIONS if x != "provider_smoke"])
def test_reviewed_operations(operation):
    doc = request(operation)
    assert validate_request(doc, context(doc), now=NOW) == doc


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("repository", "attacker/VASA", "untrusted_repository_or_branch"),
        ("branch", "main", "untrusted_repository_or_branch"),
        ("actor", "attacker", "unauthorized_actor"),
        ("actor_permission", "read", "unauthorized_actor"),
        ("source_ci", "failure", "ci_required"),
        ("trigger_ci", "pending", "ci_required"),
        ("head_sha", "c" * 40, "superseded_request"),
        ("trigger_sha", "malicious", "invalid_commit"),
        ("parent_sha", "b" * 40, "invalid_commit"),
        ("version", 2, "incompatible_version"),
        ("completed_ids", [REQUEST_ID], "replayed_request"),
        ("changed_paths", [], "invalid_request_commit"),
        ("changed_paths", ["deploy/requests/other.json"], "invalid_request_commit"),
        (
            "changed_paths",
            [f"deploy/requests/{REQUEST_ID}.json", "src/a.py"],
            "invalid_request_commit",
        ),
    ],
)
def test_untrusted_context_rejected(field, value, code):
    doc = request()
    ctx = context(doc)
    ctx[field] = value
    with pytest.raises(RequestRejected, match=f"^{code}$"):
        validate_request(doc, ctx, now=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", True),
        ("command", "echo secret"),
        ("operation", "shell"),
        ("target_commit", "a" * 39),
        ("branch", "main"),
        ("environment", "production"),
        ("created_at", "2026-10-17T11:00:00+02:00"),
        ("reason", "\nsecret"),
        ("reason", " "),
        ("expected_markers", ["ARBITRARY"]),
    ],
)
def test_strict_schema_rejected(field, value):
    doc = request()
    ctx = context(doc)
    doc[field] = value
    with pytest.raises(RequestRejected, match="^invalid_schema$"):
        validate_request(doc, ctx, now=NOW)


@pytest.mark.parametrize("field", ["scope", "policy", "authorization", "expected_markers"])
def test_operation_profile_exact(field):
    doc = request()
    doc[field] = request("application_deploy")[field]
    if field == "authorization":
        doc[field] = "invented-grant"
    with pytest.raises(RequestRejected, match="^policy_mismatch$"):
        validate_request(doc, context(doc), now=NOW)


@pytest.mark.parametrize("delta", [timedelta(hours=-2), timedelta(days=2)])
def test_stale_or_future_request(delta):
    doc = request()
    with pytest.raises(RequestRejected, match="^stale_request$"):
        validate_request(doc, context(doc), now=NOW + delta)


def test_expiry_limited_to_twenty_four_hours():
    doc = request()
    doc["expires_at"] = "2026-10-18T12:00:00Z"
    with pytest.raises(RequestRejected, match="^stale_request$"):
        validate_request(doc, context(doc), now=NOW)


def test_target_parent_required():
    doc = request()
    doc["target_commit"] = "c" * 40
    with pytest.raises(RequestRejected, match="^target_mismatch$"):
        validate_request(doc, context(doc), now=NOW)


def test_evolution_grant_cannot_be_recycled():
    doc = request("evolution_pool_rollout")
    doc["request_id"] = REQUEST_ID
    with pytest.raises(RequestRejected, match="^authorization_required$"):
        validate_request(doc, context(doc), now=NOW)


def test_provider_smoke_requires_separate_grant():
    doc = request("provider_smoke")
    with pytest.raises(RequestRejected, match="^authorization_required$"):
        validate_request(doc, context(doc), now=NOW)


@pytest.mark.parametrize("body", ['{"a":1,"a":2}', '{"a":NaN}', "[]", "{secret"])
def test_json_loader_rejects_without_exposing_body(tmp_path, body):
    path = tmp_path / "request.json"
    path.write_text(body)
    with pytest.raises(RequestRejected) as caught:
        load_request(path)
    assert str(caught.value) == "invalid_json"


def test_json_loader_limits_and_symlinks(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(" " * 16385)
    with pytest.raises(RequestRejected):
        load_request(path)
    path.write_text('{"valid":true}')
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(RequestRejected):
        load_request(link)
    assert load_request(path) == {"valid": True}


def test_renewed_policy_binding_and_absolute_expiry(monkeypatch):
    from deploy import deployment_policy

    grant = {
        "grant_id": "evolution-pool-renewed-test",
        "request_id": REQUEST_ID,
        "expires_at": "2026-10-17T13:00:00Z",
    }
    monkeypatch.setattr(deployment_policy, "RENEWED_EVOLUTION_GRANT", grant)
    doc = request("evolution_pool_rollout")
    with pytest.raises(RequestRejected, match="policy_mismatch"):
        validate_request(doc, context(doc), now=NOW)
    doc.update(request_id=REQUEST_ID, authorization=grant["grant_id"])
    assert validate_request(doc, context(doc), now=NOW) == doc
    doc["expires_at"] = "2026-10-17T14:00:00Z"
    with pytest.raises(RequestRejected, match="stale_request"):
        validate_request(doc, context(doc), now=NOW)

from urllib.parse import quote
from uuid import UUID

import pytest

from tests.control.fixtures import ControlHarness
from vasa.contracts.models import TenantContext
from vasa.knowledge.embedding import CPUEmbedder
from vasa.storage.calls import CallRepository

pytestmark = pytest.mark.integration


async def test_agent_configuration_authentication_csrf_and_tenant_isolation(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    a, b = harness.client(), harness.client()
    assert a.get("/api/agent").status_code == 401
    token_a, token_b = harness.login(a, 0), harness.login(b, 1)
    body = {"name": "A voice", "business_name": "A shop", "greeting": "Welcome"}
    assert a.put("/api/agent", json=body).status_code == 403
    assert (
        a.put(
            "/api/agent",
            json={**body, "tenant_id": str(harness.tenants[1].id)},
            headers={"x-csrf-token": token_a},
        ).status_code
        == 422
    )
    saved = a.put("/api/agent", json=body, headers={"x-csrf-token": token_a})
    assert saved.status_code == 200
    assert saved.json()["name"] == "A voice"
    assert saved.headers["cache-control"] == "no-store"
    assert b.get("/api/agent").json()["name"] == "Assistant"
    assert (
        b.put("/api/agent", json={"name": "B voice"}, headers={"x-csrf-token": token_b}).status_code
        == 200
    )
    assert a.get("/api/agent").json()["name"] == "A voice"
    assert (
        a.put(
            "/api/agent", json={**body, "language": "xx"}, headers={"x-csrf-token": token_a}
        ).status_code
        == 422
    )
    assert (
        a.put(
            "/api/agent",
            json={**body, "instructions": "x" * 2000, "business_description": "y" * 2000},
            headers={"x-csrf-token": token_a},
        ).status_code
        == 422
    )


async def test_knowledge_api_vector_storage_upload_and_foreign_delete(
    control_harness: ControlHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Native semantic accuracy is independently evaluated; this isolates HTTP/SQL ownership.
    monkeypatch.setattr(
        CPUEmbedder, "embed", lambda self, texts: [[1.0] + [0.0] * 383 for _ in texts]
    )
    harness = control_harness
    a, b = harness.client(), harness.client()
    token_a, token_b = harness.login(a, 0), harness.login(b, 1)
    assert (
        a.post("/api/knowledge", json={"name": "FAQ", "text": "We open Monday"}).status_code == 403
    )
    created = a.post(
        "/api/knowledge",
        json={"name": "FAQ", "text": "We open Monday"},
        headers={"x-csrf-token": token_a},
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    assert created.json()["chunk_count"] == 1
    assert len(a.get("/api/knowledge").json()["sources"]) == 1
    assert b.get("/api/knowledge").json() == {"sources": []}
    assert (
        b.delete(f"/api/knowledge/{source_id}", headers={"x-csrf-token": token_b}).status_code
        == 404
    )
    uploaded = a.post(
        "/api/knowledge/upload",
        content="Café hours: Tuesday".encode(),
        headers={"x-csrf-token": token_a, "x-file-name": quote("Café.txt")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["name"] == "Café.txt"
    invalid = a.post(
        "/api/knowledge/upload",
        content=b"malicious",
        headers={"x-csrf-token": token_a, "x-file-name": "../bad.txt"},
    )
    assert invalid.status_code == 422
    too_big = a.post(
        "/api/knowledge/upload",
        content=b"x" * (2 * 1024 * 1024 + 1),
        headers={"x-csrf-token": token_a, "x-file-name": "large.txt"},
    )
    assert too_big.status_code == 413
    assert (
        a.delete(f"/api/knowledge/{source_id}", headers={"x-csrf-token": token_a}).status_code
        == 200
    )
    assert (
        a.delete(f"/api/knowledge/{source_id}", headers={"x-csrf-token": token_a}).status_code
        == 404
    )


async def test_calls_api_complete_bounded_transcript_and_foreign_denial(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    context = TenantContext(harness.tenants[0].id, harness.users[0].id)
    async with harness.database.session() as session, session.begin():
        repo = CallRepository(session, context)
        record = await repo.create(
            harness.instances[0].id, "product-fixture", caller="synthetic-caller"
        )
        assert record is not None
        call_id = record.id
        for i in range(100):
            await repo.append_message(call_id, "customer", f"synthetic-{i}")
    a, b = harness.client(), harness.client()
    harness.login(a, 0)
    harness.login(b, 1)
    assert b.get(f"/api/calls/{call_id}").status_code == 404
    assert b.get("/api/calls").json() == {"calls": []}
    listing = a.get("/api/calls").json()["calls"]
    assert UUID(listing[0]["id"]) == call_id
    detail = a.get(f"/api/calls/{call_id}")
    assert detail.headers["cache-control"] == "no-store"
    assert len(detail.json()["messages"]) == 100
    assert detail.json()["next_sequence"] is None
    assert detail.json()["next_tool_offset"] is None
    assert a.get("/api/calls?limit=101").status_code == 422
    assert a.get(f"/api/calls/{call_id}?after_sequence=-1").status_code == 422

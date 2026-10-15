from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tests.control.fixtures import ControlHarness
from vasa.control.models import WhatsAppInstance
from vasa.evolution.models import EvolutionError

pytestmark = pytest.mark.integration


async def test_list_and_create_use_authenticated_tenant_in_real_sql(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    csrf = harness.login(client)
    assert client.get("/api/whatsapp/instances").json() == [
        {"id": str(harness.instances[0].id), "name": harness.instances[0].name}
    ]
    assert client.post("/api/whatsapp/instances", json={"name": "New assistant"}).status_code == 403
    injected_tenant = client.post(
        "/api/whatsapp/instances",
        json={"name": "Tenant injection", "tenant_id": str(harness.tenants[1].id)},
        headers={"x-csrf-token": csrf},
    )
    assert injected_tenant.status_code == 422
    assert harness.evolution.calls == []
    response = client.post(
        "/api/whatsapp/instances",
        json={"name": "New assistant"},
        headers={"x-csrf-token": csrf, "x-tenant-id": str(harness.tenants[1].id)},
    )
    assert response.status_code == 201
    assert set(response.json()) == {"id", "name"}
    assert response.json()["name"] == "New assistant"
    async with harness.database.session() as session:
        instance = await session.get(WhatsAppInstance, UUID(response.json()["id"]))
        assert instance is not None
        assert instance.tenant_id == harness.tenants[0].id
        assert harness.evolution.calls == [
            ("create_instance", instance.external_id, "New assistant")
        ]
    listing = client.get("/api/whatsapp/instances").json()
    assert {item["id"] for item in listing} == {str(harness.instances[0].id), response.json()["id"]}
    assert all(set(item) == {"id", "name"} for item in listing)


async def test_owned_instance_status_qr_connect_and_disconnect(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    csrf = harness.login(client)
    instance = harness.instances[0]
    path = f"/api/whatsapp/instances/{instance.id}"
    status = client.get(f"{path}/status")
    assert status.status_code == 200
    assert status.json() == {"connected": True, "logged_in": True, "name": "Paired test instance"}
    qr = client.get(f"{path}/qr")
    assert qr.status_code == 200
    assert qr.json() == {"qrcode": "data:image/png;base64,dGVzdA==", "passkey_stage": "qr"}
    for action in ("connect", "disconnect"):
        assert client.post(f"{path}/{action}").status_code == 403
        assert client.post(f"{path}/{action}", headers={"x-csrf-token": "wrong"}).status_code == 403
        response = client.post(f"{path}/{action}", headers={"x-csrf-token": csrf})
        assert response.status_code == 200
        assert set(response.json()) == {"status"}
    assert harness.evolution.calls == [
        ("status", instance.external_id),
        ("qr", instance.external_id),
        ("connect", instance.external_id),
        ("disconnect", instance.external_id),
    ]


async def test_unauthenticated_and_unknown_instances_never_reach_upstream(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    path = f"/api/whatsapp/instances/{harness.instances[0].id}"
    for suffix in ("status", "qr"):
        assert client.get(f"{path}/{suffix}").status_code == 401
    for suffix in ("connect", "disconnect"):
        assert client.post(f"{path}/{suffix}").status_code == 401
    assert client.get("/api/whatsapp/instances").status_code == 401
    assert client.post("/api/whatsapp/instances", json={"name": "Forbidden"}).status_code == 401
    csrf = harness.login(client)
    unknown = f"/api/whatsapp/instances/{uuid4()}"
    for suffix in ("status", "qr"):
        assert client.get(f"{unknown}/{suffix}").status_code == 404
    for suffix in ("connect", "disconnect"):
        assert client.post(f"{unknown}/{suffix}", headers={"x-csrf-token": csrf}).status_code == 404
    assert harness.evolution.calls == []


@pytest.mark.parametrize("code", ["license_required", "unavailable", "invalid_response"])
async def test_upstream_failure_is_sanitized_and_failed_create_rolls_back(
    control_harness: ControlHarness, code: str
) -> None:
    harness = control_harness
    client = harness.client()
    csrf = harness.login(client)
    assert (
        client.get(f"/api/whatsapp/instances/{harness.instances[0].id}/status").status_code == 200
    )
    harness.evolution.error = EvolutionError(code)
    response = client.get(f"/api/whatsapp/instances/{harness.instances[0].id}/qr")
    expected = "license_required" if code == "license_required" else "unavailable"
    assert response.status_code == 503
    assert response.json() == {"detail": expected}
    failed_create = client.post(
        "/api/whatsapp/instances", json={"name": "Failed assistant"}, headers={"x-csrf-token": csrf}
    )
    assert failed_create.status_code == 503
    assert failed_create.json() == {"detail": expected}
    async with harness.database.session() as session:
        rows = (
            (
                await session.execute(
                    select(WhatsAppInstance).where(
                        WhatsAppInstance.tenant_id == harness.tenants[0].id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [row.id for row in rows] == [harness.instances[0].id]


async def test_database_commit_failure_compensates_created_upstream_instance(
    control_harness: ControlHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = control_harness
    client = harness.client()
    csrf = harness.login(client)
    original_session = client.app.state.database.session

    def fail_commit(session: Session) -> None:
        raise SQLAlchemyError("commit-failure-private-detail")

    def failing_session() -> AsyncSession:
        session = original_session()
        event.listen(session.sync_session, "before_commit", fail_commit)
        return session

    monkeypatch.setattr(client.app.state.database, "session", failing_session)
    response = client.post(
        "/api/whatsapp/instances",
        json={"name": "Compensate failed commit"},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "unavailable"}
    assert "commit-failure-private-detail" not in response.text
    assert len(harness.evolution.calls) == 2
    create, compensate = harness.evolution.calls
    assert create[0] == "create_instance" and create[2] == "Compensate failed commit"
    assert compensate == ("delete_instance", create[1])
    async with harness.database.session() as session:
        instances = (
            (
                await session.execute(
                    select(WhatsAppInstance).where(
                        WhatsAppInstance.tenant_id == harness.tenants[0].id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [instance.id for instance in instances] == [harness.instances[0].id]

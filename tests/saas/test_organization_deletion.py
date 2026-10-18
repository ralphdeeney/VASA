"""Disposable SQL/Redis erasure tests; never delete live customer records."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.control.fixtures import PASSWORD
from tests.saas.test_admin import client_for, make_platform, prepare
from vasa.control.models import User, WhatsAppInstance
from vasa.evolution.models import EvolutionError
from vasa.saas.models import AuditEvent, Membership, OrganizationProfile
from vasa.storage.calls import CallRecord
from vasa.storage.models import Tenant


async def setup(h):
    await prepare(h)
    await make_platform(h)
    c = client_for(h)
    csrf = h.login(c)
    target = h.tenants[1]
    present = {i.external_id for i in h.instances}
    removed = []

    async def owned():
        return set(present)

    async def offline(identifier):
        return SimpleNamespace(connected=False, logged_in=False)

    async def erase(identifier):
        removed.append(identifier)
        present.remove(identifier)

    h.evolution.owned_instance_ids = owned
    h.evolution.status = offline
    h.evolution.delete_instance = erase
    path = f"/api/saas/admin/organizations/{target.id}/delete"
    data = {"confirm": True, "confirm_name": target.name, "current_password": PASSWORD}
    return c, csrf, path, data, present, removed


async def suspend(h):
    async with h.database.session() as s, s.begin():
        (await s.get(OrganizationProfile, h.tenants[1].id)).status = "suspended"


@pytest.mark.integration
async def test_delete_requires_auth_csrf_password_confirmation_and_suspension(saas_harness):
    h = saas_harness
    c, csrf, path, data, present, removed = await setup(h)
    assert c.post(path, json=data).status_code == 403
    headers = {"x-csrf-token": csrf}
    assert c.post(path, json={**data, "confirm": False}, headers=headers).status_code == 422
    assert (
        c.post(
            path, json={**data, "current_password": "wrong-password"}, headers=headers
        ).status_code
        == 403
    )
    assert c.post(path, json=data, headers=headers).json()["detail"] == "suspend_organization_first"
    await suspend(h)
    assert (
        c.post(path, json={**data, "confirm_name": "wrong"}, headers=headers).json()["detail"]
        == "organization_name_mismatch"
    )
    assert not removed
    assert len(present) == 2


@pytest.mark.integration
async def test_delete_erases_only_selected_tenant_and_upstream_preserves_shared_identity(
    saas_harness,
):
    h = saas_harness
    c, csrf, path, data, present, removed = await setup(h)
    async with h.database.session() as s, s.begin():
        s.add(
            Membership(
                user_id=h.users[1].id, tenant_id=h.tenants[0].id, role="member", status="active"
            )
        )
    await suspend(h)
    r = c.post(path, json=data, headers={"x-csrf-token": csrf})
    assert r.status_code == 200
    assert removed == [h.instances[1].external_id]
    assert present == {h.instances[0].external_id}
    async with h.database.session() as s:
        assert await s.get(Tenant, h.tenants[1].id) is None
        assert await s.get(WhatsAppInstance, h.instances[1].id) is None
        assert await s.get(WhatsAppInstance, h.instances[0].id) is not None
        user = await s.get(User, h.users[1].id)
        assert user is not None and user.tenant_id == h.tenants[0].id
        assert await s.get(Membership, (user.id, h.tenants[0].id)) is not None
        audit = await s.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "platform.organization.deleted",
                AuditEvent.target == str(h.tenants[1].id),
            )
        )
        assert audit is not None and audit.tenant_id is None
    assert c.post(path, json=data, headers={"x-csrf-token": csrf}).status_code == 404
    assert len(removed) == 1


@pytest.mark.integration
async def test_delete_solo_login_is_removed(saas_harness):
    h = saas_harness
    c, csrf, path, data, _, _ = await setup(h)
    await suspend(h)
    assert c.post(path, json=data, headers={"x-csrf-token": csrf}).status_code == 200
    async with h.database.session() as s:
        assert await s.get(User, h.users[1].id) is None
        assert await s.get(User, h.users[0].id) is not None


@pytest.mark.integration
@pytest.mark.parametrize("gate", ["durable", "redis", "upstream"])
async def test_delete_fails_closed_before_any_connection_removal(saas_harness, gate):
    h = saas_harness
    c, csrf, path, data, _, removed = await setup(h)
    await suspend(h)
    if gate == "upstream":

        async def owned():
            raise EvolutionError("unavailable")

        h.evolution.owned_instance_ids = owned
    elif gate == "durable":
        async with h.database.session() as s, s.begin():
            s.add(
                CallRecord(
                    id=uuid4(),
                    tenant_id=h.tenants[1].id,
                    instance_id=h.instances[1].id,
                    external_call_id="fixture",
                    state="CONNECTED",
                    started_at=datetime.now(UTC),
                )
            )
    else:
        key = f"vasa:tenant:{h.tenants[1].id}:call:{uuid4()}"
        await h.redis.set(key, "unknown-state", ex=60)
        h.cleanup_keys.add(key)
    r = c.post(path, json=data, headers={"x-csrf-token": csrf})
    assert r.status_code in {409, 503}
    assert not removed
    async with h.database.session() as s:
        assert await s.get(Tenant, h.tenants[1].id) is not None


@pytest.mark.integration
async def test_partial_upstream_unknown_outcome_can_be_reconciled_without_redeleting(saas_harness):
    h = saas_harness
    c, csrf, path, data, present, removed = await setup(h)
    await suspend(h)

    async def lost_response(identifier):
        present.remove(identifier)
        removed.append(identifier)
        raise EvolutionError("unavailable")

    h.evolution.delete_instance = lost_response
    r = c.post(path, json=data, headers={"x-csrf-token": csrf})
    assert r.status_code == 503
    assert r.json() == {"detail": "deletion_dependency_unavailable"}
    async with h.database.session() as s:
        assert await s.get(WhatsAppInstance, h.instances[1].id) is not None
    assert c.post(path, json=data, headers={"x-csrf-token": csrf}).status_code == 200
    assert removed == [h.instances[1].external_id]


@pytest.mark.integration
async def test_delete_blocks_own_workspace_and_platform_identity(saas_harness):
    h = saas_harness
    c, csrf, path, data, _, removed = await setup(h)
    headers = {"x-csrf-token": csrf}
    own = f"/api/saas/admin/organizations/{h.tenants[0].id}/delete"
    assert (
        c.post(own, json=data, headers=headers).json()["detail"]
        == "self_organization_deletion_denied"
    )
    from vasa.saas.models import PlatformRole

    async with h.database.session() as s, s.begin():
        s.add(PlatformRole(user_id=h.users[1].id, role="super_admin"))
    await suspend(h)
    assert c.post(path, json=data, headers=headers).json()["detail"] == "platform_admin_protected"
    assert not removed


@pytest.mark.integration
async def test_suspended_workspace_cannot_admit_new_durable_call(saas_harness):
    from vasa.contracts.models import TenantContext
    from vasa.runtime_finalization import DurableCall

    h = saas_harness
    await suspend(h)
    with pytest.raises(ValueError, match="workspace inactive"):
        await DurableCall.create(
            h.database,
            TenantContext(h.tenants[1].id, h.users[1].id),
            h.instances[1].id,
            "never-answered",
            "fixture-caller",
        )
    async with h.database.session() as s:
        assert (
            await s.scalar(select(CallRecord.id).where(CallRecord.tenant_id == h.tenants[1].id))
            is None
        )


@pytest.mark.integration
async def test_confirmed_erase_uses_owned_delete_without_async_predisconnect(saas_harness):
    h = saas_harness
    c, csrf, path, data, _, removed = await setup(h)
    await suspend(h)

    async def status(identifier):
        assert identifier == h.instances[1].external_id
        return SimpleNamespace(connected=True, logged_in=True)

    async def disconnect(identifier):
        pytest.fail("Do not use asynchronous predisconnect as a logout receipt")

    h.evolution.status = status
    h.evolution.disconnect = disconnect
    assert c.post(path, json=data, headers={"x-csrf-token": csrf}).status_code == 200
    assert removed == [h.instances[1].external_id]

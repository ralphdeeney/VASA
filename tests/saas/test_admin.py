"""Real SQL/Redis authorization and administration evidence, not live acceptance."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from vasa.saas.models import (
    AuditEvent,
    Invitation,
    Membership,
    OrganizationProfile,
    PlatformRole,
    UserProfile,
)
from vasa.saas.permissions import require_enabled


async def prepare(harness):
    async with harness.database.session() as session, session.begin():
        for tenant, user in zip(harness.tenants, harness.users, strict=True):
            if await session.get(OrganizationProfile, tenant.id) is None:
                session.add(
                    OrganizationProfile(tenant_id=tenant.id, slug=uuid4().hex, status="active")
                )
            current_profile = await session.get(UserProfile, user.id)
            if current_profile is not None:
                current_profile.email_verified_at = datetime.now(UTC)
            if current_profile is None:
                session.add(
                    UserProfile(
                        user_id=user.id,
                        name="Owner",
                        status="active",
                        email_verified_at=datetime.now(UTC),
                        legacy_access=True,
                    )
                )
            if await session.get(Membership, (user.id, tenant.id)) is None:
                session.add(
                    Membership(user_id=user.id, tenant_id=tenant.id, role="owner", status="active")
                )


def client_for(harness, *, enabled=True):
    client = harness.client(
        settings=harness.settings.model_copy(
            update={
                "saas_enabled": enabled,
                "public_origin": "http://testserver",
            }
        )
    )
    return client


async def make_platform(harness):
    async with harness.database.session() as session, session.begin():
        session.add(PlatformRole(user_id=harness.users[0].id, role="super_admin"))


def test_disabled_permissions_hide_feature():
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(saas_enabled=False)))
    )
    with pytest.raises(HTTPException) as error:
        require_enabled(request)
    assert error.value.status_code == 404


@pytest.mark.integration
async def test_owner_is_not_platform_admin_and_feature_disabled(saas_harness):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    h.login(client)
    for path in ("overview", "users", "organizations", "registrations", "audit", "health"):
        assert client.get("/api/saas/admin/" + path).status_code == 403
    assert (
        client.get(
            "/api/saas/admin/connections", params={"tenant_id": str(h.tenants[1].id)}
        ).status_code
        == 403
    )
    disabled = client_for(h, enabled=False)
    h.login(disabled)
    assert disabled.get("/api/saas/team").status_code == 404


@pytest.mark.integration
async def test_directory_pagination_sort_and_no_credentials(saas_harness):
    h = saas_harness
    await prepare(h)
    await make_platform(h)
    client = client_for(h)
    h.login(client)
    response = client.get(
        "/api/saas/admin/users",
        params={"search": h.users[1].email, "page_size": 1, "sort": "email"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1 and len(result["items"]) == 1
    assert result["items"][0]["id"] == str(h.users[1].id)
    assert "password" not in response.text and "scrypt" not in response.text
    assert client.get("/api/saas/admin/users?page_size=101").status_code == 422
    assert client.get("/api/saas/admin/users?sort=password_hash").status_code == 422
    assert client.get("/api/saas/admin/users?search=%25").json()["total"] == 0


@pytest.mark.integration
async def test_team_scope_csrf_and_last_owner_protected(saas_harness):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    csrf = h.login(client)
    response = client.get("/api/saas/team")
    assert len(response.json()["items"]) == 1
    assert h.users[1].email not in response.text
    own = "/api/saas/team/" + str(h.users[0].id)
    mutation = {"role": "member", "status": "revoked", "confirm": True}
    assert client.patch(own, json=mutation).status_code == 403
    assert client.patch(own, json=mutation, headers={"x-csrf-token": csrf}).status_code == 409
    foreign = "/api/saas/team/" + str(h.users[1].id)
    assert client.patch(foreign, json=mutation, headers={"x-csrf-token": csrf}).status_code == 404
    assert not h.evolution.calls


@pytest.mark.integration
async def test_explicit_workspace_selection_preserves_session(saas_harness):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    csrf = h.login(client)
    headers = {"x-csrf-token": csrf}
    payload = {"tenant_id": str(h.tenants[1].id)}
    assert client.post("/api/saas/workspace", json=payload, headers=headers).status_code == 403
    async with h.database.session() as session, session.begin():
        session.add(
            Membership(
                user_id=h.users[0].id, tenant_id=h.tenants[1].id, role="member", status="active"
            )
        )
    key = h.session_key(client.cookies.get("vasa_session"))
    before = json.loads(await h.redis.get(key))
    ttl = await h.redis.ttl(key)
    response = client.post("/api/saas/workspace", json=payload, headers=headers)
    assert response.status_code == 200
    after = json.loads(await h.redis.get(key))
    assert after == {**before, "tenant_id": str(h.tenants[1].id)}
    assert 0 < await h.redis.ttl(key) <= ttl
    assert client.get("/api/saas/organization").json()["id"] == str(h.tenants[1].id)
    assert (
        client.patch(
            "/api/saas/organization", json={"name": "Forbidden"}, headers=headers
        ).status_code
        == 403
    )


@pytest.mark.integration
async def test_invitation_hash_recipient_binding_and_single_use(saas_harness):
    h = saas_harness
    await prepare(h)
    messages = []

    async def send(recipient, subject, body):
        messages.append((recipient, subject, body))

    client = client_for(h)
    client.app.state.mailer = SimpleNamespace(configured=lambda: True, send=send)
    csrf = h.login(client)
    response = client.post(
        "/api/saas/invitations",
        json={"email": h.users[1].email, "role": "member"},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 201
    token = messages[0][2].split("#token=")[1]
    assert token not in response.text
    async with h.database.session() as session:
        row = await session.scalar(
            select(Invitation).where(Invitation.tenant_id == h.tenants[0].id)
        )
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert (
        client.post(
            "/api/saas/accept-invitation", json={"token": token}, headers={"x-csrf-token": csrf}
        ).status_code
        == 400
    )
    other = client_for(h)
    other_csrf = h.login(other, 1)
    headers = {"x-csrf-token": other_csrf}
    assert (
        other.post(
            "/api/saas/accept-invitation", json={"token": token}, headers=headers
        ).status_code
        == 200
    )
    assert (
        other.post(
            "/api/saas/accept-invitation", json={"token": token}, headers=headers
        ).status_code
        == 400
    )
    assert not h.evolution.calls


@pytest.mark.integration
async def test_admin_connections_explicit_scope_audit_and_no_upstream(saas_harness):
    h = saas_harness
    await prepare(h)
    await make_platform(h)
    client = client_for(h)
    h.login(client)
    assert client.get("/api/saas/admin/connections").status_code == 422
    assert (
        client.get("/api/saas/admin/connections", params={"tenant_id": str(uuid4())}).status_code
        == 404
    )
    result = client.get("/api/saas/admin/connections", params={"tenant_id": str(h.tenants[1].id)})
    assert result.status_code == 200
    assert len(result.json()["items"]) == 1
    assert "external_id" not in result.text and h.instances[1].external_id not in result.text
    async with h.database.session() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.actor_id == h.users[0].id,
                AuditEvent.action == "platform.connections.view",
            )
        )
        assert event is not None and event.tenant_id == h.tenants[1].id
    assert not h.evolution.calls


@pytest.mark.integration
async def test_admin_suspend_requires_confirm_csrf_and_preserves_last_owner(saas_harness):
    h = saas_harness
    await prepare(h)
    await make_platform(h)
    client = client_for(h)
    csrf = h.login(client)
    path = f"/api/saas/admin/users/{h.users[1].id}/status"
    assert client.post(path, json={"status": "suspended", "confirm": True}).status_code == 403
    assert (
        client.post(path, json={"status": "suspended"}, headers={"x-csrf-token": csrf}).status_code
        == 422
    )
    assert (
        client.post(
            path, json={"status": "suspended", "confirm": True}, headers={"x-csrf-token": csrf}
        ).status_code
        == 409
    )
    async with h.database.session() as session, session.begin():
        session.add(
            Membership(
                user_id=h.users[0].id, tenant_id=h.tenants[1].id, role="owner", status="active"
            )
        )
    response = client.post(
        path, json={"status": "suspended", "confirm": True}, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 200
    other = client_for(h)
    assert (
        other.post(
            "/api/auth/login",
            json={"email": h.users[1].email, "password": "test-only-vasa-password"},
        ).status_code
        == 403
    )


@pytest.mark.integration
async def test_profile_changes_cannot_assign_platform_roles(saas_harness):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    csrf = h.login(client)
    assert (
        client.patch(
            "/api/saas/profile",
            json={"name": "Updated", "role": "super_admin"},
            headers={"x-csrf-token": csrf},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/saas/profile", json={"name": "Updated"}, headers={"x-csrf-token": csrf}
        ).status_code
        == 200
    )
    assert client.get("/api/saas/profile").json()["name"] == "Updated"
    async with h.database.session() as session:
        assert await session.get(PlatformRole, h.users[0].id) is None


@pytest.mark.integration
@pytest.mark.parametrize("verification_first", [True, False])
async def test_registration_approval_requires_both_email_and_review(
    saas_harness, verification_first
):
    from tests.saas.test_identity import FakeMailer, cleanup, signup_payload
    from vasa.saas.models import RegistrationRequest

    h = saas_harness
    await prepare(h)
    await make_platform(h)
    client = client_for(h)
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"registration_approval_required": True}
    )
    mailer = FakeMailer()
    client.app.state.mailer = mailer
    csrf = h.login(client)
    payload = signup_payload()
    try:
        assert client.post("/api/saas/signup", json=payload).status_code == 202
        token = mailer.messages[-1][2].split("#token=")[1]
        async with h.database.session() as session:
            from vasa.control.models import User

            user = await session.scalar(select(User).where(User.email == payload["email"]))
            registration = await session.scalar(
                select(RegistrationRequest).where(RegistrationRequest.user_id == user.id)
            )
            registration_id, user_id = registration.id, user.id
        if verification_first:
            assert client.post("/api/saas/verify-email", json={"token": token}).status_code == 200
        result = client.post(
            f"/api/saas/admin/registrations/{registration_id}/review",
            json={"status": "approved", "confirm": True},
            headers={"x-csrf-token": csrf},
        )
        assert result.status_code == 200
        if not verification_first:
            async with h.database.session() as session:
                assert (await session.get(UserProfile, user_id)).status == "pending"
            assert client.post("/api/saas/verify-email", json={"token": token}).status_code == 200
        async with h.database.session() as session:
            profile = await session.get(UserProfile, user_id)
            assert profile.status == "active" and profile.email_verified_at is not None
        assert not h.evolution.calls
    finally:
        await cleanup(h, payload["email"])


@pytest.mark.integration
async def test_server_grant_confirmation_existing_user_and_audit(saas_harness, monkeypatch):
    from vasa.saas import bootstrap_admin

    h = saas_harness
    await prepare(h)
    monkeypatch.setattr(bootstrap_admin, "Settings", lambda: h.settings)
    with pytest.raises(ValueError, match="confirmation_required"):
        await bootstrap_admin.grant(h.users[0].email, False)
    with pytest.raises(ValueError, match="existing_active_user_required"):
        await bootstrap_admin.grant("missing@example.invalid", True)
    try:
        await bootstrap_admin.grant(h.users[0].email, True)
        with pytest.raises(ValueError, match="already_granted"):
            await bootstrap_admin.grant(h.users[0].email, True)
        async with h.database.session() as session:
            platform = await session.get(PlatformRole, h.users[0].id)
            assert platform.role == "super_admin" and platform.granted_by is None
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "platform.bootstrap_grant",
                    AuditEvent.target == str(h.users[0].id),
                )
            )
            assert event.actor_id is None and event.safe_metadata == {"source": "server_cli"}
    finally:
        async with h.database.session() as session, session.begin():
            await session.execute(delete(AuditEvent).where(AuditEvent.target == str(h.users[0].id)))


@pytest.mark.integration
async def test_invitation_mail_unavailable_creates_no_invite(saas_harness):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    csrf = h.login(client)
    client.app.state.mailer = SimpleNamespace(configured=lambda: False)
    result = client.post(
        "/api/saas/invitations",
        json={"email": h.users[1].email, "role": "member"},
        headers={"x-csrf-token": csrf},
    )
    assert result.status_code == 503
    async with h.database.session() as session:
        assert (
            await session.scalar(
                select(Invitation.id).where(Invitation.tenant_id == h.tenants[0].id)
            )
            is None
        )


@pytest.mark.integration
async def test_integrations_metadata_tenant_scope_and_client_cleanup(
    saas_harness, tmp_path, monkeypatch
):
    from tests.tools.test_webhooks_config import configuration
    from vasa.contracts.models import TenantContext
    from vasa.tools.concrete import CustomWebhook

    h = saas_harness
    await prepare(h)
    path = tmp_path / "workflows.json"
    configuration(path, TenantContext(tenant_id=h.tenants[0].id, user_id=h.users[0].id))
    monkeypatch.setenv("VASA_WEBHOOK_TEST", "synthetic-private-token")
    closed = []
    original_close = CustomWebhook.aclose

    async def track_close(tool):
        await original_close(tool)
        closed.append(True)

    monkeypatch.setattr(CustomWebhook, "aclose", track_close)
    client = client_for(h)
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"webhook_config_path": path}
    )
    h.login(client)
    result = client.get("/api/saas/integrations")
    assert result.status_code == 200
    assert result.json() == {
        "items": [{"name": "notify", "kind": "tool_gateway", "status": "configured"}]
    }
    assert closed == [True]
    for forbidden in (
        "synthetic-private-token",
        "https://",
        "token_env",
        "payload",
        "schema",
        "VASA_WEBHOOK_TEST",
    ):
        assert forbidden not in result.text
    other = client_for(h)
    other.app.state.settings = client.app.state.settings
    h.login(other, 1)
    assert other.get("/api/saas/integrations").json() == {"items": []}
    assert closed == [True]
    assert not h.evolution.calls


@pytest.mark.integration
async def test_integrations_missing_invalid_configuration_and_denied_roles(saas_harness, tmp_path):
    h = saas_harness
    await prepare(h)
    client = client_for(h)
    assert client.get("/api/saas/integrations").status_code == 401
    h.login(client)
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"webhook_config_path": None}
    )
    assert client.get("/api/saas/integrations").json() == {"items": []}
    path = tmp_path / "invalid.json"
    path.write_text("secret-private-malformed-body")
    path.chmod(0o600)
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"webhook_config_path": path}
    )
    result = client.get("/api/saas/integrations")
    assert result.status_code == 503 and result.json() == {"detail": "unavailable"}
    assert "secret-private" not in result.text
    async with h.database.session() as session, session.begin():
        row = await session.get(Membership, (h.users[0].id, h.tenants[0].id))
        row.role = "member"
    assert client.get("/api/saas/integrations").status_code == 403

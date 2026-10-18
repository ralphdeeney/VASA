"""Real session/SQL tests of platform-only alias and password rotation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.control.fixtures import PASSWORD
from tests.saas.test_admin import client_for, make_platform
from vasa.saas.models import AuditEvent, AuthToken, PlatformRole

pytestmark = pytest.mark.integration
NEW_PASSWORD = "changed-owner-password-example"


async def test_admin_alias_never_promotes_workspace_owner(saas_harness):
    h = saas_harness
    client = client_for(h)
    response = client.post(
        "/api/auth/admin/login", json={"username": "admin", "password": PASSWORD}
    )
    assert response.status_code == 401
    assert "vasa_session" not in client.cookies
    h.login(client)
    assert client.get("/api/saas/profile").json()["platform_admin"] is False
    assert client.get("/api/saas/admin/account").status_code == 403
    assert (
        client.post(
            "/api/saas/admin/password",
            json={
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        ).status_code
        == 403
    )


async def test_admin_login_real_role_and_ambiguous_alias_refused(saas_harness):
    h = saas_harness
    await make_platform(h)
    client = client_for(h)
    response = client.post(
        "/api/auth/admin/login", json={"username": "admin", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert client.get("/admin").status_code == 200
    assert client.get("/api/saas/profile").json()["platform_admin"] is True
    account = client.get("/api/saas/admin/account")
    assert account.json() == {"username": "admin", "email": h.users[0].email, "role": "super_admin"}
    assert account.headers["cache-control"] == "no-store"
    assert (
        client.post(
            "/api/auth/admin/login", json={"username": "other", "password": PASSWORD}
        ).status_code
        == 401
    )
    async with h.database.session() as session, session.begin():
        session.add(PlatformRole(user_id=h.users[1].id, role="super_admin"))
    ambiguous = client_for(h)
    assert (
        ambiguous.post(
            "/api/auth/admin/login", json={"username": "admin", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert "vasa_session" not in ambiguous.cookies
    assert (
        client_for(h, enabled=False)
        .post("/api/auth/admin/login", json={"username": "admin", "password": PASSWORD})
        .status_code
        == 404
    )


async def test_admin_password_change_revokes_every_session_and_reset_token(saas_harness):
    h = saas_harness
    await make_platform(h)
    first, second = client_for(h), client_for(h)
    csrf = h.login(first)
    h.login(second)
    token_id = uuid4()
    async with h.database.session() as session, session.begin():
        session.add(
            AuthToken(
                id=token_id,
                user_id=h.users[0].id,
                purpose="password_reset",
                token_hash=uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    data = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert first.post("/api/saas/admin/password", json=data).status_code == 403
    bad = first.post(
        "/api/saas/admin/password",
        json={**data, "current_password": "incorrect-password"},
        headers={"x-csrf-token": csrf},
    )
    assert bad.status_code == 403
    assert PASSWORD not in bad.text and NEW_PASSWORD not in bad.text
    response = first.post("/api/saas/admin/password", json=data, headers={"x-csrf-token": csrf})
    assert response.status_code == 200
    assert "vasa_session" not in first.cookies
    assert second.get("/api/saas/admin/overview").status_code == 401
    assert first.get("/admin").status_code == 401
    assert (
        client_for(h)
        .post("/api/auth/admin/login", json={"username": "admin", "password": PASSWORD})
        .status_code
        == 401
    )
    fresh = client_for(h)
    assert (
        fresh.post(
            "/api/auth/admin/login", json={"username": "admin", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )
    async with h.database.session() as session:
        token = await session.get(AuthToken, token_id)
        assert token.consumed_at is not None
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "platform.password_changed",
                AuditEvent.actor_id == h.users[0].id,
            )
        )
        assert event is not None and event.safe_metadata == {}


async def test_admin_login_origin_and_rate_controls_and_secret_free_validation(saas_harness):
    h = saas_harness
    await make_platform(h)
    client = client_for(h)
    assert (
        client.post(
            "/api/auth/admin/login",
            json={"username": "admin", "password": PASSWORD},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    for _ in range(5):
        response = client.post(
            "/api/auth/admin/login",
            json={"username": "admin", "password": "wrong-password-example"},
        )
    assert response.status_code in {401, 429}
    for _ in range(10):
        response = client.post(
            "/api/auth/admin/login",
            json={"username": "admin", "password": "wrong-password-example"},
        )
    assert response.status_code == 429

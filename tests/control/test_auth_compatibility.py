"""Legacy auth remains isolated from additive, opt-in SaaS authorization."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from tests.control.fixtures import ControlHarness
from vasa.control.auth import check_origin, require_context, validate_saas_identity


def origin_request(host: str, origin: str, **headers: str) -> Request:
    values = {"host": host, "origin": origin, **headers}
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/api/auth/login",
            "server": (host, 80),
            "headers": [(key.encode(), value.encode()) for key, value in values.items()],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(public_origin="https://vasa.example.invalid")
                )
            ),
        }
    )


def test_configured_origin_supports_tls_termination_only_for_exact_host() -> None:
    check_origin(origin_request("vasa.example.invalid", "https://vasa.example.invalid"))
    with pytest.raises(HTTPException) as error:
        check_origin(origin_request("attacker.invalid", "https://vasa.example.invalid"))
    assert error.value.detail == "invalid_origin"


@pytest.mark.parametrize(
    "origin,headers",
    [
        ("https://vasa.example.invalid", {"sec-fetch-site": "cross-site"}),
        ("https://vasa.example.invalid?key=never-print", {}),
        ("https://vasa.example.invalid/path", {}),
        ("https://attacker.invalid", {"x-forwarded-host": "vasa.example.invalid"}),
        ("http://vasa.example.invalid", {"x-forwarded-proto": "https"}),
    ],
)
def test_canonical_origin_does_not_weaken_origin_checks(
    origin: str, headers: dict[str, str]
) -> None:
    with pytest.raises(HTTPException) as error:
        check_origin(origin_request("vasa.example.invalid", origin, **headers))
    assert error.value.status_code == 403
    assert "never-print" not in error.value.detail


async def test_legacy_four_key_session_and_invalid_auth_versions(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token
    key = harness.session_key(token)
    raw = await harness.redis.get(key)
    assert raw
    payload = json.loads(raw)
    payload["auth_version"] = 0
    await harness.redis.set(key, json.dumps(payload), ex=30)
    assert client.get("/api/auth/me").status_code == 200
    for version in (True, -1, "0", None):
        payload["auth_version"] = version
        await harness.redis.set(key, json.dumps(payload), ex=30)
        assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "profile,expected",
    [
        (None, "account_inactive"),
        (SimpleNamespace(status="suspended"), "account_inactive"),
        (
            SimpleNamespace(status="active", email_verified_at=None, legacy_access=False),
            "email_verification_required",
        ),
    ],
)
async def test_saas_identity_rejects_inactive_or_unverified(
    profile: SimpleNamespace | None, expected: str
) -> None:
    database = AsyncMock()
    database.get.return_value = profile
    with pytest.raises(HTTPException) as error:
        await validate_saas_identity(database, uuid4())
    assert error.value.detail == expected


@pytest.mark.parametrize("legacy", [True, False])
async def test_saas_identity_accepts_legacy_or_verified(legacy: bool) -> None:
    database = AsyncMock()
    database.get.return_value = SimpleNamespace(
        status="active",
        email_verified_at=None if legacy else object(),
        legacy_access=legacy,
        auth_version=3,
    )
    assert await validate_saas_identity(database, uuid4()) == 3


async def test_disabled_saas_never_queries_new_profile_tables() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    session = AsyncMock()
    session.scalar.return_value = None
    session.execute.return_value = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(email="legacy@example.invalid")
    )
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    cache = AsyncMock()
    cache.get.return_value = json.dumps(
        {"user_id": str(user_id), "tenant_id": str(tenant_id), "csrf_token": "c" * 43}
    )
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/api/auth/me",
            "headers": [(b"cookie", b"vasa_session=" + b"a" * 43)],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(saas_enabled=False),
                    redis=cache,
                    database=SimpleNamespace(session=lambda: manager),
                )
            ),
        }
    )
    context = await require_context(request)
    assert context.user_id == user_id
    session.get.assert_not_called()


@pytest.mark.parametrize(
    "path,role,allowed",
    [
        ("/api/agent", "member", False),
        ("/api/knowledge", "member", False),
        ("/api/whatsapp/instances", "member", False),
        ("/api/agent", "admin", True),
        ("/api/agent", "owner", True),
        ("/api/auth/logout", "member", True),
        ("/api/saas/profile", "member", True),
        ("/api/saas/workspace", "member", True),
        ("/api/saas/accept-invitation", "member", True),
        ("/api/saas/admin/users/any/status", "member", True),
    ],
)
async def test_member_mutation_permissions_preserve_personal_actions(
    monkeypatch: pytest.MonkeyPatch, path: str, role: str, allowed: bool
) -> None:
    from vasa.contracts.models import TenantContext
    from vasa.control import auth

    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    request = origin_request("vasa.example.invalid", "https://vasa.example.invalid")
    request.scope["path"] = path
    request.scope["headers"].append((b"x-csrf-token", b"c" * 43))
    request.app.state.settings.saas_enabled = True
    request.state.auth_session = SimpleNamespace(csrf_token="c" * 43)
    request.state.membership_role = role
    monkeypatch.setattr(auth, "require_context", AsyncMock(return_value=context))
    if allowed:
        assert await auth.require_csrf(request) == context
    else:
        with pytest.raises(HTTPException) as error:
            await auth.require_csrf(request)
        assert error.value.detail == "permission_denied"


@pytest.mark.parametrize("operation", ["login", "logout"])
@pytest.mark.parametrize("database_failure", [False, True])
async def test_saas_auth_audit_is_fixed_and_database_failures_are_safe(
    monkeypatch: pytest.MonkeyPatch, operation: str, database_failure: bool
) -> None:
    from fastapi import Response
    from sqlalchemy.exc import SQLAlchemyError

    from vasa.contracts.models import TenantContext
    from vasa.control import routes
    from vasa.control.auth import AuthSession
    from vasa.saas.models import Membership, OrganizationProfile, UserProfile

    user_id, tenant_id = uuid4(), uuid4()
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        email="private@example.invalid",
        password_hash="private-hash-not-for-audit",
    )
    session = AsyncMock()
    session.scalar.return_value = None
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: user)
    session.add = lambda event: events.append(event)
    objects = {
        UserProfile: SimpleNamespace(
            status="active", legacy_access=True, email_verified_at=None, auth_version=4
        ),
        Membership: SimpleNamespace(status="active"),
        OrganizationProfile: SimpleNamespace(status="active"),
    }
    session.get.side_effect = lambda model, key: objects[model]
    if database_failure:
        session.commit.side_effect = SQLAlchemyError("SECRET database body")
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    request = origin_request("vasa.example.invalid", "https://vasa.example.invalid")
    request.app.state.settings.saas_enabled = True
    request.app.state.settings.environment = "test"
    request.app.state.database = SimpleNamespace(session=lambda: manager)
    request.app.state.redis = AsyncMock()
    request.state.auth_session = AuthSession(
        user_id, tenant_id, user.email, "c" * 43, "PRIVATE_SESSION_KEY", 4
    )
    monkeypatch.setattr(routes, "check_login_limit", AsyncMock())
    monkeypatch.setattr(routes, "authenticate_password", AsyncMock(return_value=True))
    events: list = []
    response = Response()
    if operation == "login":
        call = routes.login(
            routes.LoginInput(email=user.email, password="PRIVATE-password"), request, response
        )
    else:
        call = routes.logout(request, response, TenantContext(user_id=user_id, tenant_id=tenant_id))
    if database_failure:
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value.status_code == 503
        assert error.value.detail == "unavailable"
        assert not response.headers.get("set-cookie")
    else:
        result = await call
        assert set(result) == ({"csrf_token"} if operation == "login" else {"status"})
        if operation == "login":
            payload = json.loads(request.app.state.redis.set.call_args.args[1])
            assert payload["auth_version"] == 4
    assert len(events) == 1
    event = events[0]
    assert event.action == f"auth.{operation}"
    assert event.actor_id == user_id and event.tenant_id == tenant_id
    assert event.target == str(user_id)
    assert event.safe_metadata == {}
    assert "private" not in str(event.safe_metadata)


@pytest.mark.parametrize(
    "profile,expected",
    [
        (None, 0),
        (SimpleNamespace(status="suspended"), "account_inactive"),
        (SimpleNamespace(status="pending"), "account_inactive"),
        (
            SimpleNamespace(status="active", email_verified_at=None, legacy_access=False),
            "email_verification_required",
        ),
        (
            SimpleNamespace(status="active", email_verified_at=object(), legacy_access=False),
            "account_inactive",
        ),
        (
            SimpleNamespace(
                status="active", email_verified_at=None, legacy_access=True, auth_version=7
            ),
            7,
        ),
    ],
)
async def test_feature_rollback_cannot_reactivate_saas_accounts(
    profile: SimpleNamespace | None, expected: int | str
) -> None:
    database = AsyncMock()
    database.get.return_value = profile
    if isinstance(expected, int):
        assert await validate_saas_identity(database, uuid4(), enabled=False) == expected
    else:
        with pytest.raises(HTTPException) as error:
            await validate_saas_identity(database, uuid4(), enabled=False)
        assert error.value.detail == expected


async def test_schema_catalog_probe_preserves_unmigrated_legacy_database() -> None:
    from vasa.control.auth import identity_schema_present

    database = AsyncMock()
    database.scalar.return_value = None
    assert not await identity_schema_present(database, False)
    database.get.assert_not_called()
    assert "to_regclass" in str(database.scalar.call_args.args[0])
    database.scalar.return_value = "user_profiles"
    assert await identity_schema_present(database, False)


async def test_feature_rollback_still_rejects_revoked_session_version() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    session = AsyncMock()
    session.scalar.return_value = "user_profiles"
    session.execute.return_value = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(email="legacy@example.invalid")
    )
    session.get.return_value = SimpleNamespace(
        status="active", email_verified_at=None, legacy_access=True, auth_version=1
    )
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    cache = AsyncMock()
    cache.get.return_value = json.dumps(
        {"user_id": str(user_id), "tenant_id": str(tenant_id), "csrf_token": "c" * 43}
    )
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/api/auth/me",
            "headers": [(b"cookie", b"vasa_session=" + b"a" * 43)],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(saas_enabled=False),
                    redis=cache,
                    database=SimpleNamespace(session=lambda: manager),
                )
            ),
        }
    )
    with pytest.raises(HTTPException) as error:
        await require_context(request)
    assert error.value.status_code == 401
    assert error.value.detail == "authentication_required"


@pytest.mark.parametrize("home_failure", ["revoked", "suspended"])
@pytest.mark.parametrize("secondary_role", ["member", "owner"])
async def test_saas_login_selects_active_secondary_workspace_when_home_is_unavailable(
    control_harness: ControlHarness, home_failure: str, secondary_role: str
) -> None:
    from sqlalchemy import select

    from vasa.saas.models import AuditEvent, Membership, OrganizationProfile, UserProfile

    harness = control_harness
    user = harness.users[0]
    home, secondary = harness.tenants
    async with harness.database.session() as session:
        session.add(UserProfile(user_id=user.id, name="Owner", status="active", legacy_access=True))
        session.add_all(
            [
                OrganizationProfile(
                    tenant_id=home.id,
                    slug=f"home-{home.id}",
                    status="suspended" if home_failure == "suspended" else "active",
                ),
                OrganizationProfile(
                    tenant_id=secondary.id, slug=f"secondary-{secondary.id}", status="active"
                ),
                Membership(
                    user_id=user.id,
                    tenant_id=home.id,
                    role="owner",
                    status="revoked" if home_failure == "revoked" else "active",
                ),
                Membership(
                    user_id=user.id, tenant_id=secondary.id, role=secondary_role, status="active"
                ),
            ]
        )
        await session.commit()
    client = harness.client(settings=harness.settings.model_copy(update={"saas_enabled": True}))
    harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token
    state = json.loads(await harness.redis.get(harness.session_key(token)))
    assert state["tenant_id"] == str(secondary.id)
    assert client.get("/api/auth/me").status_code == 200
    response = client.get("/api/whatsapp/instances")
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()] == [str(harness.instances[1].id)]
    async with harness.database.session() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.actor_id == user.id, AuditEvent.action == "auth.login"
            )
        )
        assert event is not None and event.tenant_id == secondary.id
        assert event.safe_metadata == {}

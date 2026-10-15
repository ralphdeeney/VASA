import json

import pytest

from tests.control.fixtures import PASSWORD, ControlHarness
from vasa.control.auth import hash_password, verify_password

pytestmark = pytest.mark.integration


def test_password_hashes_have_unique_salts_and_verify_only_correct_password() -> None:
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)
    assert not verify_password("wrong-test-password", first)


async def test_login_me_csrf_logout_and_server_side_session(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    assert client.get("/api/auth/me").status_code == 401
    csrf = harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token is not None
    key = harness.session_key(token)
    raw = await harness.redis.get(key)
    assert raw is not None
    assert token.encode() not in raw
    assert PASSWORD.encode() not in raw
    state = json.loads(raw)
    assert str(harness.tenants[0].id) in state.values()
    assert str(harness.users[0].id) in state.values()
    assert csrf in state.values()
    assert 0 < await harness.redis.ttl(key) <= 28800
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"email": harness.users[0].email, "csrf_token": csrf}
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"x-csrf-token": b"\xff"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"x-csrf-token": csrf}).status_code == 200
    assert await harness.redis.get(key) is None
    assert client.get("/api/auth/me").status_code == 401


async def test_expired_session_is_unauthorized(control_harness: ControlHarness) -> None:
    harness = control_harness
    client = harness.client()
    harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token is not None
    assert await harness.redis.expire(harness.session_key(token), 0)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/whatsapp/instances").status_code == 401
    assert harness.evolution.calls == []


async def test_wrong_password_missing_user_and_login_rate_limit(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    for index in range(10):
        email = harness.users[0].email if index % 2 else "missing@example.invalid"
        response = client.post(
            "/api/auth/login", json={"email": email, "password": "wrong-test-password"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_credentials"}
    response = client.post(
        "/api/auth/login", json={"email": harness.users[0].email, "password": PASSWORD}
    )
    assert response.status_code == 429
    limit_keys = [key for key in harness.cleanup_keys if key.startswith("vasa:auth:login:")]
    assert len(limit_keys) == 1
    assert 0 < await harness.redis.ttl(limit_keys[0]) <= 60
    assert client.cookies.get("vasa_session") is None


async def test_cross_origin_login_and_oversized_password_rejected(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    credentials = {"email": harness.users[0].email, "password": PASSWORD}
    assert (
        client.post(
            "/api/auth/login", json=credentials, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    rejected_password = "test-password-never-echo" * 200
    invalid_response = client.post(
        "/api/auth/login", json={"email": harness.users[0].email, "password": rejected_password}
    )
    assert invalid_response.status_code == 422
    assert "test-password-never-echo" not in invalid_response.text
    assert all(
        "input" not in error and "ctx" not in error for error in invalid_response.json()["detail"]
    )
    assert client.cookies.get("vasa_session") is None
    assert harness.evolution.calls == []


async def test_production_cookie_has_secure_browser_policy(control_harness: ControlHarness) -> None:
    harness = control_harness
    client = harness.client(
        settings=harness.settings.model_copy(update={"environment": "production"})
    )
    response = client.post(
        "/api/auth/login", json={"email": harness.users[0].email, "password": PASSWORD}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" in cookie
    assert client.get("/api/auth/me").status_code == 200


async def test_server_side_user_tenant_mismatch_invalidates_session(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token is not None
    key = harness.session_key(token)
    raw = await harness.redis.get(key)
    assert raw is not None
    state = json.loads(raw)
    state["tenant_id"] = str(harness.tenants[1].id)
    await harness.redis.set(key, json.dumps(state), ex=30)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/whatsapp/instances").status_code == 401
    assert harness.evolution.calls == []


async def test_successful_relogin_rotates_session_and_revokes_previous_token(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    first_csrf = harness.login(client)
    first_token = client.cookies.get("vasa_session")
    assert first_token is not None
    assert await harness.redis.get(harness.session_key(first_token)) is not None
    second_csrf = harness.login(client)
    second_token = client.cookies.get("vasa_session")
    assert second_token is not None and second_token != first_token
    assert second_csrf != first_csrf
    assert await harness.redis.get(harness.session_key(first_token)) is None
    assert await harness.redis.get(harness.session_key(second_token)) is not None
    assert client.get("/api/auth/me").json()["csrf_token"] == second_csrf


async def test_malformed_server_side_sessions_fail_closed_with_valid_positive_controls(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    harness.login(client)
    token = client.cookies.get("vasa_session")
    assert token is not None
    key = harness.session_key(token)
    raw = await harness.redis.get(key)
    assert raw is not None
    original = json.loads(raw)
    malformed_payloads = [
        b"not-json",
        b"[]",
        b"x" * 4097,
        json.dumps({**original, "tenant_id": []}).encode(),
        json.dumps({**original, "user_id": "invalid-uuid"}).encode(),
        json.dumps({**original, "csrf_token": None}).encode(),
    ]
    for payload in malformed_payloads:
        await harness.redis.set(key, payload, ex=30)
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/whatsapp/instances").status_code == 401
        await harness.redis.set(key, raw, ex=30)
        assert client.get("/api/auth/me").status_code == 200
    assert harness.evolution.calls == []

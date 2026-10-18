"""HTTP acceptance remains private, authenticated, bounded and cleans its session."""

import json

import httpx
import pytest

from scripts.verify_platform_owner import verify

KEY = "fixture-private-password"


@pytest.mark.parametrize("failed", [None, "login", "account", "page", "logout"])
async def test_login_check_and_logout_are_scoped_and_secret_free(failed):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "vasa.litatech.xyz" and request.url.scheme == "https"
        p = request.url.path
        if p == "/api/auth/admin/login":
            assert json.loads(request.content) == {"username": "admin", "password": KEY}
            return httpx.Response(
                401 if failed == "login" else 200,
                json={"csrf_token": "x" * 43},
                headers={"set-cookie": "vasa_session=fixture; Secure; HttpOnly; Path=/"},
            )
        assert request.headers["cookie"] == "vasa_session=fixture"
        if p == "/api/saas/admin/account":
            return httpx.Response(
                403 if failed == "account" else 200,
                json={
                    "email": "fixture@example.invalid",
                    "username": "admin",
                    "role": "super_admin",
                },
            )
        if p == "/admin":
            return httpx.Response(500 if failed == "page" else 200, text="private-page")
        assert p == "/api/auth/logout" and request.headers["x-csrf-token"] == "x" * 43
        return httpx.Response(503 if failed == "logout" else 200, json={"status": "logged_out"})

    async with httpx.AsyncClient(
        base_url="https://vasa.litatech.xyz", transport=httpx.MockTransport(handle)
    ) as client:
        if failed:
            with pytest.raises(ValueError):
                await verify("fixture@example.invalid", KEY, client)
        else:
            await verify("fixture@example.invalid", KEY, client)
    assert requests[-1].url.path == (
        "/api/auth/admin/login" if failed == "login" else "/api/auth/logout"
    )

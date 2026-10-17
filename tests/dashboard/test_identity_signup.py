"""Signup-specific navigation must be correct before JavaScript executes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasa.dashboard.router import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_signup_offers_sign_in_without_a_redundant_signup_link(client: TestClient) -> None:
    response = client.get("/signup")
    assert response.status_code == 200
    assert 'href="/signup"' not in response.text
    assert 'Already have an account? <a href="/login">Sign in</a>' in response.text
    assert "identity-account-help" not in response.text
    assert "identity-signup-navigation" not in response.text
    assert '<img src="/dashboard/assets/vasa-logo.png" alt="VASA" class="identity-logo">' in (
        response.text
    )
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "img-src 'self' data:;" in response.headers["content-security-policy"]
    assert "https:" not in response.headers["content-security-policy"]
    assert client.get("/dashboard/assets/not-a-logo.png").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/verify-email",
        "/resend-verification",
        "/forgot-password",
        "/reset-password",
        "/accept-invitation",
        "/logout",
    ],
)
def test_other_identity_routes_keep_existing_account_links(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert '<a class="button" href="/signup">Get started</a>' in response.text
    assert '<a href="/login">Sign in</a> · <a href="/signup">Create account</a>' in response.text
    assert 'id="identity-form"' in response.text
    assert "Already have an account?" not in response.text
    assert "<img" not in response.text


def test_route_context_cannot_interpolate_query_text(client: TestClient) -> None:
    response = client.get("/signup?next=%3Cscript%3Ealert(1)%3C/script%3E")
    assert "alert(1)" not in response.text
    assert 'href="/signup"' not in response.text


def test_logo_is_a_fixed_first_party_png_with_security_headers(client: TestClient) -> None:
    response = client.get("/dashboard/assets/vasa-logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "img-src 'self' data:;" in response.headers["content-security-policy"]
    assert client.get("/dashboard/assets/not-a-logo.png").status_code == 404
    assert client.get("/dashboard/assets/vasa-logo.jpg").status_code == 404
    assert client.get("/dashboard/assets/%2e%2e/templates/identity.html").status_code == 404

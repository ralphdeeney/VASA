"""Feature rollout boundaries, safe diagnostics and cache behavior."""

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.control.diagnostics import safe_reason


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.example",
        "https://name:secret@example.com",
        "https://example.com/?key=private",
        "https://example.com/#private",
        "https://example.com/path",
        "//example.com",
    ],
)
def test_canonical_origin_rejects_unsafe_forms(origin):
    with pytest.raises(ValidationError):
        Settings(public_origin=origin)


def test_canonical_origin_and_secure_defaults():
    settings = Settings(public_origin="https://vasa.example.com/")
    assert settings.public_origin == "https://vasa.example.com"
    assert settings.saas_enabled is False
    assert settings.smtp_starttls is True
    assert settings.smtp_password.get_secret_value() == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"detail": "private-password-or-provider-body"},
        {"detail": ["secret"]},
        ["secret"],
        {"detail": {"key": "secret"}},
        {"secret": "secret"},
    ],
)
def test_auth_diagnostic_discards_unapproved_response_material(payload):
    assert safe_reason(httpx.Response(503, json=payload)) == "unclassified"


def test_auth_diagnostic_reports_fixed_reason_only():
    assert (
        safe_reason(httpx.Response(403, json={"detail": "invalid_origin", "secret": "private"}))
        == "invalid_origin"
    )
    assert safe_reason(httpx.Response(403, text="private raw body")) == "unclassified"


async def test_capabilities_do_not_claim_registration_or_expose_configuration(saas_harness):
    harness = saas_harness
    client = harness.client()
    result = client.get("/api/site/capabilities")
    assert result.json() == {
        "saas_enabled": True,
        "signup_available": False,
        "email_delivery_available": False,
        "contact_available": False,
    }
    assert "smtp" not in result.text and "password" not in result.text


async def test_sensitive_api_no_store_and_sql_failures_are_sanitized(
    saas_harness, monkeypatch, caplog
):
    harness = saas_harness
    client = harness.client()
    harness.login(client)
    profile = client.get("/api/saas/profile")
    assert profile.status_code == 200
    assert profile.headers["cache-control"] == "no-store"

    original = client.app.state.database.session
    calls = 0

    def fail():
        nonlocal calls
        calls += 1
        if calls == 1:
            return original()
        raise SQLAlchemyError("private-email-token-password-SQL-parameters")

    monkeypatch.setattr(client.app.state.database, "session", fail)
    response = client.get("/api/saas/profile")
    assert response.status_code == 503
    assert response.json() == {"detail": "unavailable"}
    assert "private-email" not in response.text + caplog.text


async def test_operator_diagnostic_failures_never_return_exception_or_body(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from vasa.control import diagnostics

    database = MagicMock()
    database.session.side_effect = RuntimeError("private database URL and password")
    database.aclose = AsyncMock()
    monkeypatch.setattr(diagnostics, "Database", lambda *args, **kwargs: database)
    client = AsyncMock()
    client.get.return_value = httpx.Response(200, text="private page body")
    client.post.return_value = httpx.Response(503, json={"detail": "private response secret"})
    manager = AsyncMock()
    manager.__aenter__.return_value = client
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", lambda **kwargs: manager)
    markers = await diagnostics.diagnose(Settings(), "https://vasa.example.com")
    assert "AUTH_DATABASE=unavailable" in markers
    assert "AUTH_LOGIN_PAGE_STATUS=200" in markers
    assert "AUTH_LOGIN_PROBE_REASON=unclassified" in markers
    assert "private" not in "\n".join(markers)
    assert "vasa.example" not in "\n".join(markers)
    database.aclose.assert_awaited_once()
    client.post.side_effect = RuntimeError("private request exception")
    markers = await diagnostics.diagnose(Settings(), "https://vasa.example.com")
    assert "AUTH_HTTP=unavailable" in markers
    assert "private" not in "\n".join(markers)

"""SMTP setup must not expose API-key usernames or enable unverified signup."""

import pytest
from pydantic import ValidationError

from vasa.app import create_app
from vasa.config import Settings


@pytest.mark.parametrize(
    "host",
    [
        "https://smtp.reloop.sh",
        "key@smtp.reloop.sh",
        "smtp.reloop.sh:587",
        "bad\nhost",
        "-bad.example",
    ],
)
def test_smtp_host_is_a_plain_hostname(host):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, smtp_host=host)


@pytest.mark.parametrize(
    "sender",
    [
        "not-an-email",
        "one@example.com,two@example.com",
        "VASA <noreply@example.com>\r\nBcc:private@example.com",
        "<>",
        "group: one@example.com;",
    ],
)
def test_sender_is_one_safe_mailbox(sender):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, smtp_sender=sender)


def test_display_sender_and_secret_validation_redaction():
    settings = Settings(_env_file=None, smtp_sender="VASA <noreply@example.com>")
    assert settings.smtp_sender == "VASA <noreply@example.com>"
    secret = "private-key-DO-NOT-PRINT\n"
    for field in ("smtp_username", "smtp_password"):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None, **{field: secret})
        assert "private-key" not in str(error.value)


@pytest.mark.parametrize("verified", [False, True])
async def test_capabilities_require_complete_configuration_and_mailbox_attestation(verified):
    import httpx

    settings = Settings(
        _env_file=None,
        saas_enabled=True,
        public_origin="https://vasa.example.com",
        smtp_host="smtp.reloop.sh",
        smtp_port=587,
        smtp_username="fake-local-key",
        smtp_password="fake-local-key",
        smtp_sender="VASA <noreply@example.com>",
        smtp_delivery_verified=verified,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="https://vasa.example.com"
    ) as client:
        response = await client.get("/api/site/capabilities")
    assert response.json()["signup_available"] is verified
    assert response.json()["email_delivery_available"] is verified
    assert response.json()["contact_available"] is False
    assert "fake-local-key" not in response.text and "smtp.reloop.sh" not in response.text

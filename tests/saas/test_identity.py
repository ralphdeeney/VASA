import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from tests.control.fixtures import ControlHarness
from vasa.control.auth import verify_password
from vasa.control.models import User
from vasa.saas.mailer import MailUnavailable
from vasa.saas.models import AuthToken, Membership, RegistrationRequest, UserProfile
from vasa.storage.models import Tenant


@dataclass
class FakeMailer:
    available: bool = True
    fail: bool = False
    messages: list[tuple[str, str, str]] = field(default_factory=list)

    def configured(self) -> bool:
        return self.available

    async def send(self, recipient: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailUnavailable()
        self.messages.append((recipient, subject, body))


def identity_client(harness: ControlHarness, mailer: FakeMailer):
    settings = harness.settings.model_copy(
        update={"saas_enabled": True, "public_origin": "http://testserver"}
    )
    client = harness.client(settings=settings)
    client.app.state.mailer = mailer
    return client


def signup_payload() -> dict[str, str]:
    return {
        "email": f"signup-{uuid4().hex}@example.invalid",
        "name": "Test Owner",
        "business_name": "New Business",
        "password": "test-only-identity-password",
    }


async def cleanup(harness: ControlHarness, email: str) -> None:
    async with harness.database.session() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None:
            await session.execute(delete(Tenant).where(Tenant.id == user.tenant_id))
            await session.commit()


@pytest.mark.integration
async def test_signup_verification_single_use_and_no_external_resources(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    payload = signup_payload()
    try:
        response = client.post("/api/saas/signup", json=payload)
        assert response.status_code == 202
        assert len(mailer.messages) == 1
        raw = mailer.messages[0][2].split("#token=")[1]
        assert raw not in response.text and payload["password"] not in response.text
        async with harness.database.session() as session:
            user = await session.scalar(select(User).where(User.email == payload["email"]))
            profile = await session.get(UserProfile, user.id)
            assert profile.status == "pending" and profile.email_verified_at is None
            token = await session.scalar(select(AuthToken).where(AuthToken.user_id == user.id))
            assert token.token_hash == hashlib.sha256(raw.encode()).hexdigest()
            assert token.token_hash != raw
        assert client.post("/api/saas/verify-email", json={"token": raw}).status_code == 200
        assert client.post("/api/saas/verify-email", json={"token": raw}).status_code == 400
        async with harness.database.session() as session:
            profile = await session.get(UserProfile, user.id)
            membership = await session.scalar(
                select(Membership).where(Membership.user_id == user.id)
            )
            assert profile.status == "active" and profile.email_verified_at is not None
            assert membership.role == "owner" and membership.status == "active"
        assert not harness.evolution.calls
    finally:
        await cleanup(harness, payload["email"])


@pytest.mark.integration
@pytest.mark.parametrize("unavailable", ["configuration", "delivery"])
async def test_signup_mail_failure_leaves_no_records(saas_harness, unavailable):
    mailer = FakeMailer(available=unavailable != "configuration", fail=unavailable == "delivery")
    client = identity_client(saas_harness, mailer)
    payload = signup_payload()
    response = client.post("/api/saas/signup", json=payload)
    assert response.status_code == 503
    async with saas_harness.database.session() as session:
        assert await session.scalar(select(User.id).where(User.email == payload["email"])) is None
    assert not saas_harness.evolution.calls


@pytest.mark.integration
async def test_recovery_is_enumeration_resistant_and_reset_revokes_sessions(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    user = harness.users[0]
    harness.login(client)
    assert client.get("/api/auth/me").status_code == 200
    missing = client.post("/api/saas/forgot-password", json={"email": "absent@example.invalid"})
    existing = client.post("/api/saas/forgot-password", json={"email": user.email})
    assert missing.status_code == existing.status_code == 202
    assert missing.json() == existing.json() == {"status": "request_received"}
    raw = mailer.messages[-1][2].split("#token=")[1]
    async with harness.database.session() as session:
        profile = await session.get(UserProfile, user.id)
        version = profile.auth_version
    password = "changed-test-only-password"
    response = client.post("/api/saas/reset-password", json={"token": raw, "password": password})
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/saas/reset-password", json={"token": raw, "password": password}
        ).status_code
        == 400
    )
    async with harness.database.session() as session:
        updated = await session.get(User, user.id)
        profile = await session.get(UserProfile, user.id)
        assert verify_password(password, updated.password_hash)
        assert profile.auth_version == version + 1


@pytest.mark.integration
async def test_expired_and_wrong_purpose_tokens_rejected(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    client.post("/api/saas/forgot-password", json={"email": harness.users[0].email})
    raw = mailer.messages[-1][2].split("#token=")[1]
    assert client.post("/api/saas/verify-email", json={"token": raw}).status_code == 400
    async with harness.database.session() as session:
        await session.execute(
            update(AuthToken)
            .where(AuthToken.token_hash == hashlib.sha256(raw.encode()).hexdigest())
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (
        client.post(
            "/api/saas/reset-password", json={"token": raw, "password": "new-test-only-password"}
        ).status_code
        == 400
    )


@pytest.mark.integration
async def test_public_identity_rejects_role_injection_cross_origin_and_disabled(saas_harness):
    mailer = FakeMailer()
    client = identity_client(saas_harness, mailer)
    payload = signup_payload()
    assert (
        client.post("/api/saas/signup", json={**payload, "role": "super_admin"}).status_code == 422
    )
    assert (
        client.post(
            "/api/saas/signup", json=payload, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    disabled = saas_harness.client(
        settings=saas_harness.settings.model_copy(update={"saas_enabled": False})
    )
    assert disabled.post("/api/saas/signup", json=payload).status_code == 404
    assert not mailer.messages


@pytest.mark.integration
async def test_resend_rotates_verification_and_approval_stays_pending(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    client.app.state.settings.registration_approval_required = True
    payload = signup_payload()
    try:
        assert client.post("/api/saas/signup", json=payload).status_code == 202
        first = mailer.messages[-1][2].split("#token=")[1]
        assert (
            client.post(
                "/api/saas/resend-verification", json={"email": payload["email"]}
            ).status_code
            == 202
        )
        second = mailer.messages[-1][2].split("#token=")[1]
        assert first != second
        assert client.post("/api/saas/verify-email", json={"token": first}).status_code == 400
        assert client.post("/api/saas/verify-email", json={"token": second}).status_code == 200
        async with harness.database.session() as session:
            user = await session.scalar(select(User).where(User.email == payload["email"]))
            profile = await session.get(UserProfile, user.id)
            assert profile.email_verified_at is not None and profile.status == "pending"
    finally:
        await cleanup(harness, payload["email"])


@pytest.mark.integration
async def test_recovery_public_requests_are_rate_limited(saas_harness):
    client = identity_client(saas_harness, FakeMailer())
    for _ in range(10):
        assert (
            client.post(
                "/api/saas/forgot-password", json={"email": "absent@example.invalid"}
            ).status_code
            == 202
        )
    assert (
        client.post(
            "/api/saas/forgot-password", json={"email": "absent@example.invalid"}
        ).status_code
        == 429
    )


async def test_smtp_failure_replaces_exception_and_message_material(monkeypatch):
    from vasa.config import Settings
    from vasa.saas.mailer import SMTPMailer

    settings = Settings(
        smtp_host="mail.example.invalid",
        smtp_sender="vasa@example.invalid",
        smtp_username="test-only-user",
        smtp_password="test-only-password",
        smtp_delivery_verified=True,
    )
    mailer = SMTPMailer(settings)

    def fail(*arguments):
        raise RuntimeError("private-key-and-raw-email-body")

    monkeypatch.setattr(mailer, "_send", fail)
    with pytest.raises(MailUnavailable) as failure:
        await mailer.send("recipient@example.invalid", "Private subject", "private token")
    assert str(failure.value) == ""
    assert failure.value.__suppress_context__


@pytest.mark.integration
async def test_approval_before_verification_activates_only_after_proof(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    client.app.state.settings.registration_approval_required = True
    payload = signup_payload()
    try:
        assert client.post("/api/saas/signup", json=payload).status_code == 202
        token = mailer.messages[-1][2].split("#token=")[1]
        async with harness.database.session() as session:
            user = await session.scalar(select(User).where(User.email == payload["email"]))
            await session.execute(
                update(RegistrationRequest)
                .where(RegistrationRequest.user_id == user.id)
                .values(status="approved")
            )
            await session.commit()
            profile = await session.get(UserProfile, user.id)
            assert profile.status == "pending"
        assert client.post("/api/saas/verify-email", json={"token": token}).status_code == 200
        async with harness.database.session() as session:
            profile = await session.get(UserProfile, user.id)
            assert profile.status == "active" and profile.email_verified_at is not None
    finally:
        await cleanup(harness, payload["email"])


@pytest.mark.integration
async def test_legacy_active_user_can_verify_without_membership_changes(saas_harness):
    harness = saas_harness
    mailer = FakeMailer()
    client = identity_client(harness, mailer)
    user = harness.users[0]
    assert (
        client.post("/api/saas/resend-verification", json={"email": user.email}).status_code == 202
    )
    token = mailer.messages[-1][2].split("#token=")[1]
    assert client.post("/api/saas/verify-email", json={"token": token}).status_code == 200
    async with harness.database.session() as session:
        profile = await session.get(UserProfile, user.id)
        member = await session.get(Membership, (user.id, user.tenant_id))
        assert profile.status == "active" and profile.email_verified_at is not None
        assert member.status == "active" and member.role == "owner"


def contact_payload() -> dict[str, str]:
    return {
        "name": "Contact Person",
        "email": "sender@example.invalid",
        "message": "Private inquiry",
    }


@pytest.mark.integration
async def test_public_contact_sends_only_to_trusted_destination(saas_harness):
    mailer = FakeMailer()
    client = identity_client(saas_harness, mailer)
    client.app.state.settings.saas_enabled = False
    client.app.state.settings.contact_recipient = "operator@example.invalid"
    response = client.post("/api/site/contact", json=contact_payload())
    assert response.status_code == 202 and response.json() == {"status": "request_received"}
    assert mailer.messages == [
        (
            "operator@example.invalid",
            "VASA website contact request",
            "Name: Contact Person\nEmail: sender@example.invalid\n\nPrivate inquiry",
        )
    ]
    for secret in ("operator@example.invalid", "sender@example.invalid", "Private inquiry"):
        assert secret not in response.text
    assert not saas_harness.evolution.calls


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["recipient", "configuration", "delivery"])
async def test_public_contact_unavailable_has_fixed_private_failure(saas_harness, failure):
    mailer = FakeMailer(available=failure != "configuration", fail=failure == "delivery")
    client = identity_client(saas_harness, mailer)
    client.app.state.settings.contact_recipient = (
        "operator@example.invalid" if failure != "recipient" else ""
    )
    response = client.post("/api/site/contact", json=contact_payload())
    assert response.status_code == 503 and response.json() == {"detail": "email_unavailable"}
    assert not mailer.messages


@pytest.mark.integration
async def test_public_contact_origin_validation_and_rate_limit(saas_harness):
    mailer = FakeMailer()
    client = identity_client(saas_harness, mailer)
    client.app.state.settings.contact_recipient = "operator@example.invalid"
    assert (
        client.post(
            "/api/site/contact", json=contact_payload(), headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    for changes in (
        {"recipient": "attacker@example.invalid"},
        {"name": " "},
        {"message": "x" * 4001},
        {"email": "sender@example.invalid\r\nBcc:attacker@example.invalid"},
    ):
        assert (
            client.post("/api/site/contact", json={**contact_payload(), **changes}).status_code
            == 422
        )
    for _ in range(10):
        assert client.post("/api/site/contact", json=contact_payload()).status_code == 202
    assert client.post("/api/site/contact", json=contact_payload()).status_code == 429
    assert len(mailer.messages) == 10

"""SQL-backed token rejection boundaries; no real email is sent."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from tests.saas.test_admin import client_for, prepare
from tests.saas.test_identity import FakeMailer, cleanup, identity_client, signup_payload
from vasa.control.models import User
from vasa.saas.models import AuthToken, Invitation, Membership, UserProfile

pytestmark = pytest.mark.integration


async def test_expired_verification_keeps_signup_pending(saas_harness):
    h = saas_harness
    mailer = FakeMailer()
    client = identity_client(h, mailer)
    payload = signup_payload()
    try:
        assert client.post("/api/saas/signup", json=payload).status_code == 202
        raw = mailer.messages[-1][2].split("#token=")[1]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        async with h.database.session() as session:
            user = await session.scalar(select(User).where(User.email == payload["email"]))
            user_id = user.id
            membership = await session.get(Membership, (user.id, user.tenant_id))
            original_membership = (membership.role, membership.status)
            await session.execute(
                update(AuthToken)
                .where(AuthToken.token_hash == digest)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
        response = client.post("/api/saas/verify-email", json={"token": raw})
        assert response.status_code == 400 and response.json() == {"detail": "invalid_token"}
        assert raw not in response.text
        async with h.database.session() as session:
            profile = await session.get(UserProfile, user_id)
            membership = await session.get(Membership, (user_id, user.tenant_id))
            token = await session.scalar(select(AuthToken).where(AuthToken.token_hash == digest))
            assert profile.status == "pending" and profile.email_verified_at is None
            assert (membership.role, membership.status) == original_membership
            assert token.consumed_at is None
        assert len(mailer.messages) == 1 and not h.evolution.calls
    finally:
        await cleanup(h, payload["email"])


async def test_expired_invitation_leaves_memberships_and_acceptance_untouched(saas_harness):
    h = saas_harness
    await prepare(h)
    mailer = FakeMailer()
    owner = client_for(h)
    owner.app.state.mailer = mailer
    owner_csrf = h.login(owner)
    response = owner.post(
        "/api/saas/invitations",
        json={"email": h.users[1].email, "role": "member"},
        headers={"x-csrf-token": owner_csrf},
    )
    assert response.status_code == 201
    raw = mailer.messages[-1][2].split("#token=")[1]
    digest = hashlib.sha256(raw.encode()).hexdigest()
    async with h.database.session() as session:
        original = list(
            (
                await session.execute(
                    select(
                        Membership.user_id, Membership.tenant_id, Membership.role, Membership.status
                    ).order_by(Membership.user_id, Membership.tenant_id)
                )
            ).all()
        )
        await session.execute(
            update(Invitation)
            .where(Invitation.token_hash == digest)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    recipient = client_for(h)
    csrf = h.login(recipient, 1)
    rejected = recipient.post(
        "/api/saas/accept-invitation", json={"token": raw}, headers={"x-csrf-token": csrf}
    )
    assert rejected.status_code == 400 and rejected.json() == {"detail": "invalid_token"}
    assert raw not in rejected.text
    async with h.database.session() as session:
        current = list(
            (
                await session.execute(
                    select(
                        Membership.user_id, Membership.tenant_id, Membership.role, Membership.status
                    ).order_by(Membership.user_id, Membership.tenant_id)
                )
            ).all()
        )
        invitation = await session.scalar(select(Invitation).where(Invitation.token_hash == digest))
        assert current == original and invitation.accepted_at is None
    assert len(mailer.messages) == 1 and not h.evolution.calls


@pytest.mark.parametrize("endpoint", ["verify-email", "reset-password", "accept-invitation"])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("private-malformed-token", 422),
        ("!" * 43, 422),
        ("X" * 43, 400),
    ],
)
async def test_invalid_tokens_never_reflect_or_mutate_identity(
    saas_harness, endpoint, raw, expected
):
    h = saas_harness
    await prepare(h)
    mailer = FakeMailer()
    client = identity_client(h, mailer)
    csrf = h.login(client)

    async def snapshot():
        async with h.database.session() as session:
            return (
                list(
                    (
                        await session.execute(select(User.id, User.password_hash).order_by(User.id))
                    ).all()
                ),
                list(
                    (
                        await session.execute(
                            select(
                                UserProfile.user_id,
                                UserProfile.status,
                                UserProfile.email_verified_at,
                                UserProfile.auth_version,
                            ).order_by(UserProfile.user_id)
                        )
                    ).all()
                ),
                list(
                    (
                        await session.execute(
                            select(
                                Membership.user_id,
                                Membership.tenant_id,
                                Membership.role,
                                Membership.status,
                            ).order_by(Membership.user_id, Membership.tenant_id)
                        )
                    ).all()
                ),
                list((await session.execute(select(AuthToken.id, AuthToken.consumed_at))).all()),
                list((await session.execute(select(Invitation.id, Invitation.accepted_at))).all()),
            )

    before = await snapshot()
    data = {"token": raw}
    if endpoint == "reset-password":
        data["password"] = "private-replacement-password"
    response = client.post("/api/saas/" + endpoint, json=data, headers={"x-csrf-token": csrf})
    # Invitation syntax accepts any fixed-length opaque token; an unknown digest
    # is rejected by the database lookup rather than the identity slug validator.
    if endpoint == "accept-invitation" and raw == "!" * 43:
        expected = 400
    assert response.status_code == expected
    assert raw not in response.text and "private-replacement-password" not in response.text
    assert await snapshot() == before
    assert not mailer.messages and not h.evolution.calls

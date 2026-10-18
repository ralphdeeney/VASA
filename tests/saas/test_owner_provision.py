"""Real PostgreSQL owner grant and retry safety contracts."""

import asyncio
import io
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from tests.control.fixtures import PASSWORD, ControlHarness
from vasa.config import Settings
from vasa.control.auth import hash_password, verify_password
from vasa.control.models import User, WhatsAppInstance
from vasa.saas.models import AuditEvent, PlatformRole, UserProfile
from vasa.saas.provision_owner import (
    ALREADY_PROVISIONED,
    PROVISIONED,
    ProvisionError,
    main,
    provision_owner,
)
from vasa.storage.models import Tenant


def staging(harness: ControlHarness) -> Settings:
    return harness.settings.model_copy(
        update={"environment": "production", "public_origin": "https://vasa.litatech.xyz"}
    )


async def test_existing_owner_grant_and_replay_preserves_changed_password(
    saas_harness: ControlHarness,
) -> None:
    harness = saas_harness
    settings = staging(harness)
    user = harness.users[0]
    assert await provision_owner(settings, user.email, PASSWORD) == PROVISIONED
    async with harness.database.session() as session:
        stored = await session.get(User, user.id)
        profile = await session.get(UserProfile, user.id)
        assert stored is not None and profile is not None
        assert profile.auth_version == 1
        stored.password_hash = hash_password("changed-after-first-provision")
        await session.commit()
    assert await provision_owner(settings, user.email, PASSWORD) == ALREADY_PROVISIONED
    async with harness.database.session() as session:
        stored = await session.get(User, user.id)
        assert stored is not None
        assert verify_password("changed-after-first-provision", stored.password_hash)
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.target == str(user.id),
                        AuditEvent.action == "platform.owner_provision",
                    )
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].safe_metadata == {"scope": "staging", "method": "protected_stdin"}
        assert PASSWORD not in repr(events[0].safe_metadata)


async def test_new_owner_has_no_external_resources(saas_harness: ControlHarness) -> None:
    harness = saas_harness
    email = f"owner-{uuid4().hex}@example.invalid"
    tenant_id = None
    try:
        assert await provision_owner(staging(harness), email, PASSWORD) == PROVISIONED
        async with harness.database.session() as session:
            user = await session.scalar(select(User).where(User.email == email))
            assert user is not None
            tenant_id = user.tenant_id
            assert user.password_hash != PASSWORD
            assert verify_password(PASSWORD, user.password_hash)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WhatsAppInstance)
                    .where(WhatsAppInstance.tenant_id == tenant_id)
                )
                == 0
            )
            profile = await session.get(UserProfile, user.id)
            assert profile is not None and profile.legacy_access and profile.status == "active"
    finally:
        if tenant_id is not None:
            async with harness.database.session() as session:
                await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
                await session.commit()


async def test_other_admin_refused(saas_harness: ControlHarness) -> None:
    harness = saas_harness
    async with harness.database.session() as session:
        session.add(PlatformRole(user_id=harness.users[1].id))
        await session.commit()
    with pytest.raises(ProvisionError, match="owner_conflict"):
        await provision_owner(staging(harness), harness.users[0].email, PASSWORD)


@pytest.mark.parametrize("status", ["pending", "suspended"])
async def test_inactive_identity_refused(saas_harness: ControlHarness, status: str) -> None:
    harness = saas_harness
    async with harness.database.session() as session:
        profile = await session.get(UserProfile, harness.users[0].id)
        assert profile is not None
        profile.status = status
        await session.commit()
    with pytest.raises(ProvisionError, match="identity_refused"):
        await provision_owner(staging(harness), harness.users[0].email, PASSWORD)


async def test_other_environment_refused(saas_harness: ControlHarness) -> None:
    with pytest.raises(ProvisionError, match="environment_refused"):
        await provision_owner(saas_harness.settings, saas_harness.users[0].email, PASSWORD)


async def test_concurrent_owner_grants_are_serialized(saas_harness: ControlHarness) -> None:
    harness = saas_harness
    results = await asyncio.gather(
        provision_owner(staging(harness), harness.users[0].email, PASSWORD),
        provision_owner(staging(harness), harness.users[0].email, PASSWORD),
    )
    assert sorted(results) == sorted([PROVISIONED, ALREADY_PROVISIONED])


@pytest.mark.parametrize(
    "payload",
    [
        '{"email":"private@example.invalid","password":"secret-value","extra":"secret-value"}',
        "secret-value-not-json",
        "x" * 4097,
    ],
)
def test_invalid_stdin_never_exposes_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], payload: str
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out in {
        "PLATFORM_OWNER_PROVISION_FAILED=invalid_input\n",
        "PLATFORM_OWNER_PROVISION_FAILED=internal_error\n",
    }
    assert not output.err
    assert "secret-value" not in output.out

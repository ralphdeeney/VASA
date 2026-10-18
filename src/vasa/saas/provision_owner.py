"""Staging-only, audited initial platform-owner provisioning through private stdin."""

import asyncio
import json
import sys

from sqlalchemy import select, text

from vasa.config import Settings
from vasa.control.auth import hash_password
from vasa.control.models import User
from vasa.control.routes import LoginInput
from vasa.saas.models import AuditEvent, Membership, OrganizationProfile, PlatformRole, UserProfile
from vasa.storage.database import Database
from vasa.storage.models import Tenant

PROVISIONED = "PLATFORM_OWNER_PROVISIONED"
ALREADY_PROVISIONED = "PLATFORM_OWNER_ALREADY_PROVISIONED"


class ProvisionError(Exception):
    """Carries only a fixed safe failure category."""


async def provision_owner(settings: Settings, email: str, password: str) -> str:
    """Grant initial ownership once; retries never reset a subsequently changed password."""
    if (
        settings.environment != "production"
        or settings.public_origin != "https://vasa.litatech.xyz"
    ):
        raise ProvisionError("environment_refused")
    try:
        data = LoginInput(email=email, password=password)
        password_hash = await asyncio.to_thread(hash_password, data.password)
    except ValueError:
        raise ProvisionError("invalid_input") from None
    database = Database(
        settings.database_url.get_secret_value(),
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    try:
        async with database.session() as session, session.begin():
            # Fixed process-independent key serializes initial owner creation and replay.
            await session.execute(text("SELECT pg_advisory_xact_lock(7137402169021)"))
            user = await session.scalar(select(User).where(User.email == data.email))
            roles = list((await session.scalars(select(PlatformRole))).all())
            if any(user is None or role.user_id != user.id for role in roles):
                raise ProvisionError("owner_conflict")
            profile: UserProfile | None
            membership: Membership | None
            organization: OrganizationProfile | None
            if user is None:
                tenant = Tenant(name="VASA platform owner")
                session.add(tenant)
                await session.flush()
                user = User(tenant_id=tenant.id, email=data.email, password_hash=password_hash)
                session.add(user)
                await session.flush()
                profile = UserProfile(
                    user_id=user.id, name="Platform owner", status="active", legacy_access=True
                )
                membership = Membership(
                    user_id=user.id, tenant_id=tenant.id, role="owner", status="active"
                )
                organization = OrganizationProfile(
                    tenant_id=tenant.id, slug=f"workspace-{tenant.id}", status="active"
                )
                session.add_all([profile, membership, organization])
            else:
                profile = await session.get(UserProfile, user.id)
                membership = await session.get(Membership, (user.id, user.tenant_id))
                organization = await session.get(OrganizationProfile, user.tenant_id)
                if (
                    profile is None
                    or profile.status != "active"
                    or not (profile.legacy_access or profile.email_verified_at is not None)
                    or membership is None
                    or membership.status != "active"
                    or membership.role != "owner"
                    or organization is None
                    or organization.status != "active"
                ):
                    raise ProvisionError("identity_refused")
                receipt = await session.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.action == "platform.owner_provision",
                        AuditEvent.target == str(user.id),
                    )
                )
                if receipt is not None:
                    if len(roles) != 1 or roles[0].role != "super_admin":
                        raise ProvisionError("identity_refused")
                    return ALREADY_PROVISIONED
                user.password_hash = password_hash
                profile.auth_version += 1
            if not roles:
                session.add(PlatformRole(user_id=user.id, role="super_admin", granted_by=None))
            session.add(
                AuditEvent(
                    actor_id=None,
                    tenant_id=user.tenant_id,
                    action="platform.owner_provision",
                    target=str(user.id),
                    safe_metadata={"scope": "staging", "method": "protected_stdin"},
                )
            )
        return PROVISIONED
    finally:
        await database.aclose()


def main() -> None:
    try:
        content = sys.stdin.read(4097)
        if len(content) > 4096:
            raise ProvisionError("invalid_input")
        payload = json.loads(content)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"email", "password"}
            or not all(isinstance(value, str) for value in payload.values())
        ):
            raise ProvisionError("invalid_input")
        result = asyncio.run(provision_owner(Settings(), payload["email"], payload["password"]))
    except ProvisionError as exc:
        code = str(exc)
        if code not in {
            "environment_refused",
            "invalid_input",
            "owner_conflict",
            "identity_refused",
        }:
            code = "internal_error"
        print(f"PLATFORM_OWNER_PROVISION_FAILED={code}")
        raise SystemExit(1) from None
    except Exception:
        print("PLATFORM_OWNER_PROVISION_FAILED=internal_error")
        raise SystemExit(1) from None
    print(result)


if __name__ == "__main__":
    main()

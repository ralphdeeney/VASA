"""Audited, explicit server-only platform grant for an existing active user."""

import argparse
import asyncio
import getpass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.control.models import User
from vasa.saas.models import AuditEvent, PlatformRole, UserProfile
from vasa.storage.database import Database


async def grant(email: str, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("confirmation_required")
    settings = Settings()
    if not settings.saas_enabled:
        raise ValueError("saas_disabled")
    database = Database(
        settings.database_url.get_secret_value(),
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    try:
        async with database.session() as session, session.begin():
            user = await session.scalar(
                select(User).where(User.email == email.strip().lower()).with_for_update()
            )
            if user is None:
                raise ValueError("existing_active_user_required")
            profile = await session.get(UserProfile, user.id)
            if (
                profile is None
                or profile.status != "active"
                or (profile.email_verified_at is None and not profile.legacy_access)
            ):
                raise ValueError("existing_active_user_required")
            existing = await session.get(PlatformRole, user.id)
            if existing is not None:
                raise ValueError("already_granted")
            session.add(PlatformRole(user_id=user.id, role="super_admin", granted_by=None))
            session.add(
                AuditEvent(
                    actor_id=None,
                    tenant_id=None,
                    action="platform.bootstrap_grant",
                    target=str(user.id),
                    safe_metadata={"source": "server_cli"},
                )
            )
    finally:
        await database.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    options = parser.parse_args()
    confirmation = getpass.getpass("Type GRANT PLATFORM ADMIN to confirm: ")
    try:
        asyncio.run(grant(options.email, confirmation == "GRANT PLATFORM ADMIN"))
    except (ValueError, SQLAlchemyError):
        parser.exit(1, "PLATFORM_ADMIN_GRANT_FAILED\n")
    print("PLATFORM_ADMIN_GRANTED")


if __name__ == "__main__":
    main()

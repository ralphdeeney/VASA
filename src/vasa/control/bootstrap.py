"""Create an initial tenant/user locally; never accepts a password on the command line."""

import argparse
import asyncio
import getpass
import os

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.control.auth import hash_password
from vasa.control.models import User
from vasa.control.routes import LoginInput
from vasa.storage.database import Database
from vasa.storage.models import Tenant


async def bootstrap(email: str, tenant_name: str, password: str) -> None:
    data = LoginInput(email=email, password=password)
    if not tenant_name.strip() or len(tenant_name.strip()) > 200:
        raise ValueError("tenant name must contain between 1 and 200 characters")
    password_hash = await asyncio.to_thread(hash_password, password)
    settings = Settings()
    database = Database(
        settings.database_url.get_secret_value(),
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    try:
        async with database.session() as session, session.begin():
            existing = await session.execute(select(User.id).where(User.email == data.email))
            if existing.scalar_one_or_none() is not None:
                raise ValueError("user already exists; bootstrap does not overwrite accounts")
            tenant = Tenant(name=tenant_name.strip())
            session.add(tenant)
            await session.flush()
            user = User(tenant_id=tenant.id, email=data.email, password_hash=password_hash)
            session.add(user)
            await session.flush()
            if settings.saas_enabled:
                from vasa.saas.models import (
                    AuditEvent,
                    Membership,
                    OrganizationProfile,
                    UserProfile,
                )

                session.add_all(
                    [
                        UserProfile(user_id=user.id, status="active", legacy_access=True),
                        OrganizationProfile(
                            tenant_id=tenant.id, slug=f"workspace-{tenant.id}", status="active"
                        ),
                        Membership(
                            user_id=user.id, tenant_id=tenant.id, role="owner", status="active"
                        ),
                        AuditEvent(
                            actor_id=None,
                            tenant_id=tenant.id,
                            action="identity.server_provision",
                            target=str(user.id),
                        ),
                    ]
                )
    finally:
        await database.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant", required=True)
    options = parser.parse_args()
    password = os.environ.get("VASA_BOOTSTRAP_PASSWORD") or getpass.getpass("Initial password: ")
    try:
        asyncio.run(bootstrap(options.email, options.tenant, password))
    except (ValueError, SQLAlchemyError):
        parser.exit(
            1, "Bootstrap failed: check inputs, existing account, and database migrations.\n"
        )
    print("Initial tenant and user created.")


if __name__ == "__main__":
    main()

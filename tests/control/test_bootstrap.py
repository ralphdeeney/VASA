import asyncio
import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from tests.control.fixtures import PASSWORD, ControlHarness
from vasa.control.auth import verify_password
from vasa.control.models import User
from vasa.storage.models import Tenant

pytestmark = pytest.mark.integration


async def test_bootstrap_creates_hashed_account_without_printing_password_and_refuses_overwrite(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    email = f"bootstrap-{uuid4().hex}@example.invalid"
    tenant_name = f"Bootstrap test {uuid4().hex}"
    environment = {
        **os.environ,
        "VASA_DATABASE_URL": harness.settings.database_url.get_secret_value(),
        "VASA_BOOTSTRAP_PASSWORD": PASSWORD,
    }
    try:
        stored_hash = None
        for expected_code in (0, 1):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "vasa.control.bootstrap",
                "--email",
                email.upper(),
                "--tenant",
                tenant_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
            assert process.returncode == expected_code
            assert PASSWORD.encode() not in stdout + stderr
            assert b"Traceback" not in stderr
            async with harness.database.session() as session:
                user = (await session.execute(select(User).where(User.email == email))).scalar_one()
                assert verify_password(PASSWORD, user.password_hash)
                tenant = await session.get(Tenant, user.tenant_id)
                assert tenant is not None and tenant.name == tenant_name
                if stored_hash is None:
                    stored_hash = user.password_hash
                else:
                    assert user.password_hash == stored_hash
    finally:
        async with harness.database.session() as session:
            tenant_id = await session.scalar(select(User.tenant_id).where(User.email == email))
            if tenant_id is not None:
                await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
                await session.commit()

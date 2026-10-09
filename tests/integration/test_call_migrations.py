import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from vasa.config import Settings

pytestmark = pytest.mark.integration


async def test_fresh_migrations_upgrade_downgrade_and_schema_agreement(
    dependency_settings: Settings,
    tmp_path: Path,
) -> None:
    """Only a UUID-named database on the dedicated VASA test PostgreSQL is touched."""
    original = make_url(dependency_settings.database_url.get_secret_value())
    database_name = f"vasa_migration_test_{uuid4().hex}"
    connection = await asyncpg.connect(
        original.set(drivername="postgresql").render_as_string(hide_password=False), timeout=3
    )
    created = False
    try:
        await connection.execute(f"CREATE DATABASE {database_name}")
        created = True
        settings = dict(os.environ)
        settings["VASA_DATABASE_URL"] = original.set(database=database_name).render_as_string(
            hide_password=False
        )
        settings["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
        settings["UV_NO_SYNC"] = "1"

        async def migrate(*arguments: str) -> None:
            process = await asyncio.create_subprocess_exec(
                "uv",
                "run",
                "--frozen",
                "alembic",
                *arguments,
                env=settings,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(20):
                    await process.communicate()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()
            assert process.returncode == 0, (
                "isolated migration failed; no secret-bearing output shown"
            )

        await migrate("upgrade", "head")
        await migrate("check")
        # Empty isolated DB only: no existing project history is downgraded.
        await migrate("downgrade", "0003")
        await migrate("upgrade", "head")
        await migrate("check")
    finally:
        try:
            if created:
                await connection.execute(f"DROP DATABASE {database_name}")
        finally:
            await connection.close()

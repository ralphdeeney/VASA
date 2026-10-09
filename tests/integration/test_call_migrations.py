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
        # Exercise existing legacy rows through the provider migration, not
        # just fresh column creation. Preserve identifiers and other voices.
        await migrate("downgrade", "0005")
        isolated_url = original.set(drivername="postgresql", database=database_name)
        isolated = await asyncpg.connect(
            isolated_url.render_as_string(hide_password=False), timeout=3
        )
        tenant, legacy, custom = uuid4(), uuid4(), uuid4()
        try:
            await isolated.execute("INSERT INTO tenants(id, name) VALUES($1, 'Fixture')", tenant)
            await isolated.execute(
                "INSERT INTO agents(id, tenant_id, name, voice) VALUES"
                "($1, $3, 'Legacy', 'ljspeech_en'), ($2, $3, 'Custom', 'custom_voice')",
                legacy,
                custom,
                tenant,
            )
            await migrate("upgrade", "head")
            rows = await isolated.fetch("SELECT id, tenant_id, voice FROM agents ORDER BY name")
            assert {(row["id"], row["tenant_id"], row["voice"]) for row in rows} == {
                (legacy, tenant, "kokoro_af_maple"),
                (custom, tenant, "custom_voice"),
            }
            default = await isolated.fetchval(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'agents' AND column_name = 'voice'"
            )
            assert "kokoro_af_maple" in default
        finally:
            await isolated.close()
        # Temporary UUID-named DB only: no existing project history is downgraded.
        await migrate("downgrade", "0003")
        await migrate("upgrade", "head")
        await migrate("check")
    finally:
        try:
            if created:
                await connection.execute(f"DROP DATABASE {database_name}")
        finally:
            await connection.close()

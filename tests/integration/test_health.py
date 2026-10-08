from time import monotonic
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.app import create_app
from vasa.config import Settings
from vasa.storage.database import Database

pytestmark = pytest.mark.integration


async def test_live_and_ready_with_real_dependencies(
    dependency_settings: Settings,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    # Fixture probes deliberately fail if real services or migrations are absent.
    assert db_session.in_transaction()
    assert await redis_client.ping()
    with TestClient(create_app(dependency_settings)) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "components": {"database": "ok", "redis": "ok"},
        }


@pytest.mark.parametrize("failed_components", [("database",), ("redis",), ("database", "redis")])
async def test_readiness_failures_are_bounded_and_do_not_disclose_configuration(
    failed_components: tuple[str, ...],
    dependency_settings: Settings,
    db_session: AsyncSession,
    redis_client: Redis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert db_session.in_transaction()
    assert await redis_client.ping()
    secret = "health-secret-never-disclose"
    configuration = Settings(
        environment="test",
        database_url=(
            f"postgresql+asyncpg://private-user:{secret}@127.0.0.1:1/private-db"
            if "database" in failed_components
            else dependency_settings.database_url
        ),
        redis_url=(
            f"redis://:{secret}@127.0.0.1:1/0"
            if "redis" in failed_components
            else dependency_settings.redis_url
        ),
        dependency_timeout_seconds=0.2,
    )
    start = monotonic()
    with TestClient(create_app(configuration)) as client:
        live_response = client.get("/health/live")
        assert live_response.status_code == 200
        assert live_response.json() == {"status": "alive"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "components": {
                component: "unavailable" if component in failed_components else "ok"
                for component in ("database", "redis")
            },
        }
        output = response.text + live_response.text + caplog.text
        for forbidden in (secret, "private-user", "private-db", "redis://", "postgresql+"):
            assert forbidden not in output
    assert monotonic() - start < 3, "readiness must return bounded failure and clean up"


async def test_reachable_database_without_migrations_is_not_ready(
    dependency_settings: Settings,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    assert db_session.in_transaction()
    assert await redis_client.ping()
    # Only a unique VASA test database is created/dropped; the migrated database is untouched.
    database_name = f"vasa_test_unmigrated_{uuid4().hex}"
    administrative_database = Database(dependency_settings.database_url.get_secret_value())
    try:
        async with administrative_database.engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            try:
                empty_database_url = make_url(
                    dependency_settings.database_url.get_secret_value()
                ).set(database=database_name)
                configuration = Settings(
                    environment="test",
                    database_url=empty_database_url.render_as_string(hide_password=False),
                    redis_url=dependency_settings.redis_url,
                    dependency_timeout_seconds=0.5,
                )
                with TestClient(create_app(configuration)) as client:
                    assert client.get("/health/live").status_code == 200
                    response = client.get("/health/ready")
                    assert response.status_code == 503
                    assert response.json() == {
                        "status": "unavailable",
                        "components": {"database": "unavailable", "redis": "ok"},
                    }
                # Readiness/lifespan must not apply migrations or create tables implicitly.
                empty_database = Database(configuration.database_url.get_secret_value())
                try:
                    async with empty_database.session() as session:
                        table_count = await session.scalar(
                            text(
                                "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema = 'public'"
                            )
                        )
                        assert table_count == 0
                finally:
                    await empty_database.aclose()
            finally:
                await connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
    finally:
        await administrative_database.aclose()

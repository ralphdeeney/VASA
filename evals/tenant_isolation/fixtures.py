"""Real, project-scoped dependencies with rollback and exact-key cleanup."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.config import Settings
from vasa.contracts.models import CallSession, TenantContext
from vasa.storage.cache import CallRegistry
from vasa.storage.database import Database
from vasa.storage.models import Tenant
from vasa.storage.repositories import TenantRepository


@pytest.fixture
def dependency_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=getenv(
            "VASA_TEST_DATABASE_URL",
            "postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa",
        ),
        redis_url=getenv("VASA_TEST_REDIS_URL", "redis://127.0.0.1:6389/0"),
        dependency_timeout_seconds=0.5,
    )


@pytest.fixture
async def db_session(dependency_settings: Settings) -> AsyncIterator[AsyncSession]:
    database = Database(dependency_settings.database_url.get_secret_value())
    try:
        async with database.session() as session:
            await session.begin()
            try:
                await session.execute(text("SELECT 1"))
                await session.execute(select(Tenant.id).limit(1))
            except Exception as exc:
                pytest.fail(
                    "Real PostgreSQL is unavailable or migrations are missing "
                    f"({type(exc).__name__}). Run docker compose up -d and "
                    "uv run --frozen alembic upgrade head; configure "
                    "VASA_TEST_DATABASE_URL only for dedicated test services.",
                    pytrace=False,
                )
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await database.aclose()


@pytest.fixture
async def tenant_contexts(db_session: AsyncSession) -> tuple[TenantContext, TenantContext]:
    repository = TenantRepository(db_session)
    first = await repository.create(f"fixture-a-{uuid4()}")
    second = await repository.create(f"fixture-b-{uuid4()}")
    return (
        TenantContext(tenant_id=first.id, user_id=uuid4()),
        TenantContext(tenant_id=second.id, user_id=uuid4()),
    )


@pytest.fixture
async def redis_client(dependency_settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(
        dependency_settings.redis_url.get_secret_value(),
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    try:
        try:
            assert await client.ping()
        except Exception as exc:
            pytest.fail(
                f"Real Redis is unavailable ({type(exc).__name__}). Run "
                "docker compose up -d; configure VASA_TEST_REDIS_URL only "
                "for dedicated test services.",
                pytrace=False,
            )
        yield client
    finally:
        await client.aclose()


@dataclass
class RegistryFixture:
    registry: CallRegistry
    client: Redis
    calls: list[CallSession]

    @staticmethod
    def key(call: CallSession) -> str:
        return f"vasa:tenant:{call.tenant_id}:call:{call.id}"

    def call(self, context: TenantContext, call_id: UUID | None = None) -> CallSession:
        call = CallSession(
            id=call_id or uuid4(),
            tenant_id=context.tenant_id,
            instance_id=f"test-instance-{uuid4()}",
            external_call_id=f"test-call-{uuid4()}",
            metadata={"fixture": "tenant-isolation"},
        )
        self.calls.append(call)
        return call


@pytest.fixture
async def registry_fixture(redis_client: Redis) -> AsyncIterator[RegistryFixture]:
    fixture = RegistryFixture(CallRegistry(redis_client, ttl_seconds=30), redis_client, [])
    try:
        yield fixture
    finally:
        # Delete only UUID-qualified keys registered by this fixture, even after failures.
        # No FLUSHDB, blanket namespace deletion or unrelated-key mutation is permitted.
        keys = {fixture.key(call) for call in fixture.calls}
        if keys:
            await redis_client.delete(*keys)

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from evals.tenant_isolation.fixtures import RegistryFixture
from vasa.config import Settings
from vasa.contracts.models import CallState, TenantContext
from vasa.storage.cache import CallRegistry
from vasa.storage.database import Database
from vasa.storage.models import Agent, Tenant
from vasa.storage.repositories import AgentRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def migration_head() -> str | None:
    configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    return ScriptDirectory.from_config(configuration).get_current_head()


async def test_migrated_schema_and_real_pgvector_distance(
    db_session: AsyncSession, migration_head: str | None
) -> None:
    revision = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert migration_head is not None
    assert revision == migration_head, "apply the committed Alembic migration head"
    columns = (
        await db_session.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'agents'"
            )
        )
    ).all()
    assert set(columns) == {
        ("id", "uuid", "NO"),
        ("tenant_id", "uuid", "NO"),
        ("name", "character varying", "NO"),
        ("business_name", "character varying", "NO"),
        ("greeting", "character varying", "NO"),
        ("business_description", "character varying", "NO"),
        ("instructions", "character varying", "NO"),
        ("language", "character varying", "NO"),
        ("voice", "character varying", "NO"),
    }
    distance = await db_session.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,5]'::vector"))
    assert distance == pytest.approx(2.0), "pgvector must execute an actual distance operation"


async def test_agent_create_get_and_list_are_tenant_scoped(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    context_a, context_b = tenant_contexts
    repository_a = AgentRepository(db_session, context_a)
    repository_b = AgentRepository(db_session, context_b)
    first = await repository_a.create("A assistant")
    second = await repository_a.create("A receptionist")
    other = await repository_b.create("B assistant")

    assert first.tenant_id == context_a.tenant_id
    assert await repository_a.get(first.id) is first
    assert {agent.id for agent in await repository_a.list()} == {first.id, second.id}
    assert {agent.id for agent in await repository_b.list()} == {other.id}
    assert await repository_a.get(other.id) is None
    assert await repository_b.get(first.id) is None
    assert await repository_a.get(uuid4()) is None
    assert db_session.in_transaction(), "repositories must not commit caller transactions"


async def test_database_rejects_agent_with_nonexistent_tenant(db_session: AsyncSession) -> None:
    async with db_session.begin_nested():
        db_session.add(Agent(id=uuid4(), tenant_id=uuid4(), name="Orphan agent"))
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_repositories_leave_writes_uncommitted_and_caller_can_rollback(
    db_session: AsyncSession,
    dependency_settings: Settings,
    tenant_contexts: tuple[TenantContext, TenantContext],
) -> None:
    context = tenant_contexts[0]
    agent = await AgentRepository(db_session, context).create("Uncommitted agent")
    assert await db_session.get(Agent, agent.id) is agent
    observer_database = Database(dependency_settings.database_url.get_secret_value())
    try:
        async with observer_database.session() as observer:
            assert await observer.get(Tenant, context.tenant_id) is None
            assert await observer.get(Agent, agent.id) is None
            await db_session.rollback()
            assert await observer.get(Tenant, context.tenant_id) is None
            assert await observer.get(Agent, agent.id) is None
    finally:
        await observer_database.aclose()


async def test_call_registry_roundtrip_state_update_delete_and_expiry(
    registry_fixture: RegistryFixture,
) -> None:
    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call = registry_fixture.call(context)
    registry = registry_fixture.registry
    assert await registry.get(context, call.id) is None
    await registry.put(call)
    assert await registry.get(context, call.id) == call

    key = registry_fixture.key(call)
    ttl = await registry_fixture.client.ttl(key)
    assert 0 < ttl <= 30, "call state must have a bounded expiration"

    updated = type(call)(
        id=call.id,
        tenant_id=call.tenant_id,
        instance_id=call.instance_id,
        external_call_id=call.external_call_id,
        state=CallState.CONNECTED,
        metadata={"progress": "connected"},
    )
    await registry.put(updated)
    assert await registry.get(context, call.id) == updated
    # Force expiry server-side instead of waiting or relying on wall-clock sleeps.
    assert await registry_fixture.client.pexpire(key, 0)
    assert await registry.get(context, call.id) is None
    await registry.put(call)
    await registry.delete(context, call.id)
    assert await registry.get(context, call.id) is None
    await registry.delete(context, call.id)  # Deleting an absent call is safe.


async def test_same_call_id_isolated_between_tenants(registry_fixture: RegistryFixture) -> None:
    context_a = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    context_b = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call_a = registry_fixture.call(context_a)
    call_b = registry_fixture.call(context_b, call_a.id)
    registry = registry_fixture.registry
    await registry.put(call_a)
    await registry.put(call_b)
    assert await registry.get(context_a, call_a.id) == call_a
    assert await registry.get(context_b, call_b.id) == call_b
    await registry.delete(context_b, call_b.id)
    assert await registry.get(context_b, call_b.id) is None
    assert await registry.get(context_a, call_a.id) == call_a


@pytest.mark.parametrize("field", ["tenant_id", "id"])
async def test_corrupted_foreign_payload_is_not_returned_or_overwritten(
    registry_fixture: RegistryFixture, field: str
) -> None:
    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call = registry_fixture.call(context)
    registry = registry_fixture.registry
    await registry.put(call)
    assert await registry.get(context, call.id) == call
    key = registry_fixture.key(call)
    raw = await registry_fixture.client.get(key)
    assert raw is not None
    corrupted = json.loads(raw)
    corrupted[field] = str(uuid4())
    foreign_payload = json.dumps(corrupted)
    await registry_fixture.client.set(key, foreign_payload, ex=30)

    with pytest.raises(ValueError, match="namespace mismatch"):
        await registry.get(context, call.id)
    with pytest.raises(ValueError, match="namespace mismatch"):
        await registry.put(call)
    assert await registry_fixture.client.get(key) == foreign_payload.encode()


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b"[]", b"x" * 65537])
async def test_invalid_persisted_call_state_is_never_accepted(
    registry_fixture: RegistryFixture, payload: bytes
) -> None:
    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call = registry_fixture.call(context)
    await registry_fixture.registry.put(call)
    assert await registry_fixture.registry.get(context, call.id) == call
    await registry_fixture.client.set(registry_fixture.key(call), payload, ex=30)
    with pytest.raises(ValueError):
        await registry_fixture.registry.get(context, call.id)
    with pytest.raises(ValueError):
        await registry_fixture.registry.put(call)
    assert await registry_fixture.client.get(registry_fixture.key(call)) == payload


async def test_oversized_call_state_cannot_replace_valid_state(
    registry_fixture: RegistryFixture,
) -> None:
    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call = registry_fixture.call(context)
    await registry_fixture.registry.put(call)
    oversized = replace(call, metadata={"oversized": "x" * 65536})
    with pytest.raises(ValueError, match="size limit"):
        await registry_fixture.registry.put(oversized)
    assert await registry_fixture.registry.get(context, call.id) == call


@pytest.mark.parametrize("operation", ["put", "get", "delete"])
async def test_registry_propagates_real_connection_failure(
    registry_fixture: RegistryFixture, operation: str
) -> None:
    context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    call = registry_fixture.call(context)
    await registry_fixture.registry.put(call)
    assert await registry_fixture.registry.get(context, call.id) == call
    unavailable_client = Redis(
        host="127.0.0.1",
        port=1,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        retry=Retry(NoBackoff(), 0),
    )
    try:
        unavailable_registry = CallRegistry(unavailable_client)
        with pytest.raises(RedisError):
            if operation == "put":
                await unavailable_registry.put(call)
            elif operation == "get":
                await unavailable_registry.get(context, call.id)
            else:
                await unavailable_registry.delete(context, call.id)
        assert await registry_fixture.registry.get(context, call.id) == call
    finally:
        await unavailable_client.aclose()

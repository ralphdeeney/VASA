from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from evals.tenant_isolation.fixtures import RegistryFixture
from vasa.contracts.models import TenantContext
from vasa.storage.repositories import AgentRepository

pytestmark = [pytest.mark.integration, pytest.mark.eval]


async def test_guessed_foreign_agent_id_and_list_do_not_disclose_another_tenant(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    victim_context, attacker_context = tenant_contexts
    victim_repository = AgentRepository(db_session, victim_context)
    attacker_repository = AgentRepository(db_session, attacker_context)
    victim = await victim_repository.create("Victim confidential business")
    attacker = await attacker_repository.create("Attacker own business")

    # Positive controls prevent an implementation that always returns nothing passing.
    assert await victim_repository.get(victim.id) is victim
    assert await attacker_repository.get(attacker.id) is attacker
    assert [item.id for item in await victim_repository.list()] == [victim.id]

    assert await attacker_repository.get(victim.id) is None
    visible_agents = await attacker_repository.list()
    assert [item.id for item in visible_agents] == [attacker.id]
    assert victim.name not in [item.name for item in visible_agents]


async def test_guessed_foreign_call_id_cannot_read_or_delete_victim_state(
    registry_fixture: RegistryFixture,
) -> None:
    victim_context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    attacker_context = TenantContext(tenant_id=uuid4(), user_id=uuid4())
    victim = registry_fixture.call(victim_context)
    attacker = registry_fixture.call(attacker_context)
    registry = registry_fixture.registry
    await registry.put(victim)
    await registry.put(attacker)
    assert await registry.get(victim_context, victim.id) == victim
    assert await registry.get(attacker_context, attacker.id) == attacker

    assert await registry.get(attacker_context, victim.id) is None
    await registry.delete(attacker_context, victim.id)
    assert await registry.get(victim_context, victim.id) == victim
    assert await registry.get(attacker_context, attacker.id) == attacker

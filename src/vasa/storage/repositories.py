from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.contracts.models import TenantContext
from vasa.storage.models import Agent, Tenant


def _name(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("name must contain between 1 and 200 characters")
    return normalized


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str) -> Tenant:
        tenant = Tenant(name=_name(name))
        self.session.add(tenant)
        await self.session.flush()
        return tenant


class AgentRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context

    async def create(self, name: str) -> Agent:
        agent = Agent(tenant_id=self.context.tenant_id, name=_name(name))
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def get(self, id: UUID) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.id == id, Agent.tenant_id == self.context.tenant_id)
        )
        return result.scalar_one_or_none()

    async def list(self) -> list[Agent]:
        result = await self.session.execute(
            select(Agent).where(Agent.tenant_id == self.context.tenant_id).order_by(Agent.id)
        )
        return list(result.scalars())

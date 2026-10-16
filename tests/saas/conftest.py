"""Real PostgreSQL/Redis fixtures for additive SaaS contracts."""

from collections.abc import AsyncIterator

import pytest

from evals.tenant_isolation.fixtures import dependency_settings, redis_client  # noqa: F401
from tests.control.fixtures import ControlHarness, control_harness  # noqa: F401
from vasa.saas.models import Membership, OrganizationProfile, UserProfile


@pytest.fixture
async def saas_harness(control_harness: ControlHarness) -> AsyncIterator[ControlHarness]:  # noqa: F811
    control_harness.settings = control_harness.settings.model_copy(
        update={"saas_enabled": True, "public_origin": "http://testserver"}
    )
    async with control_harness.database.session() as session:
        for user in control_harness.users:
            session.add(
                UserProfile(
                    user_id=user.id, name="Fixture owner", status="active", legacy_access=True
                )
            )
            session.add(
                OrganizationProfile(
                    tenant_id=user.tenant_id, slug=f"workspace-{user.tenant_id}", status="active"
                )
            )
            session.add(
                Membership(user_id=user.id, tenant_id=user.tenant_id, role="owner", status="active")
            )
        await session.commit()
    yield control_harness

"""Explicit organization erasure; upstream removals are resumable, never faked."""

import asyncio
from uuid import UUID

from fastapi import HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from vasa.control.models import User, WhatsAppInstance
from vasa.evolution.models import EvolutionError
from vasa.saas.models import AuditEvent, Membership, OrganizationProfile, PlatformRole, UserProfile
from vasa.storage.calls import CallRecord
from vasa.storage.models import Tenant


async def erase_organization(request: Request, tenant_id: UUID, name: str, actor: User) -> None:
    """Only an already suspended, call-free workspace can be irreversibly erased.

    Holding the profile lock also excludes concurrent activation/create/connect.
    A partial upstream failure keeps local mappings for an ownership-verified retry.
    Missing upstream mappings are accepted only from the authenticated full list.
    """
    try:
        async with asyncio.timeout(12):
            async with request.app.state.database.session() as session, session.begin():
                org = await session.get(OrganizationProfile, tenant_id, with_for_update=True)
                tenant = await session.get(Tenant, tenant_id, with_for_update=True)
                if org is None or tenant is None:
                    raise HTTPException(404, "not_found")
                if tenant_id == request.state.auth_session.tenant_id:
                    raise HTTPException(409, "self_organization_deletion_denied")
                if org.status != "suspended":
                    raise HTTPException(409, "suspend_organization_first")
                if tenant.name != name:
                    raise HTTPException(409, "organization_name_mismatch")
                users = list(
                    (
                        await session.scalars(
                            select(User).where(User.tenant_id == tenant_id).with_for_update()
                        )
                    ).all()
                )
                for user in users:
                    if await session.get(PlatformRole, user.id) is not None:
                        raise HTTPException(409, "platform_admin_protected")
                if await session.scalar(
                    select(CallRecord.id)
                    .where(CallRecord.tenant_id == tenant_id, CallRecord.ended_at.is_(None))
                    .limit(1)
                ):
                    raise HTTPException(409, "active_calls_block_deletion")
                async for _ in request.app.state.redis.scan_iter(
                    match=f"vasa:tenant:{tenant_id}:call:*", count=20
                ):
                    raise HTTPException(409, "active_calls_block_deletion")
                instances = list(
                    (
                        await session.scalars(
                            select(WhatsAppInstance)
                            .where(WhatsAppInstance.tenant_id == tenant_id)
                            .order_by(WhatsAppInstance.id)
                            .limit(33)
                        )
                    ).all()
                )
                if len(instances) > 32:
                    raise HTTPException(409, "deletion_capacity_exceeded")
                client = request.app.state.evolution
                if instances and client is None:
                    raise HTTPException(503, "deletion_dependency_unavailable")
                present = await client.owned_instance_ids() if instances else set()
                connected = []
                for instance in instances:
                    if instance.external_id in present:
                        state = await client.status(instance.external_id)
                        if state.connected or state.logged_in:
                            connected.append(instance)
                for instance in connected:
                    await client.disconnect(instance.external_id)
                    state = await client.status(instance.external_id)
                    if state.connected or state.logged_in:
                        raise HTTPException(409, "disconnect_whatsapp_first")
                for instance in instances:
                    if instance.external_id in present:
                        await client.delete_instance(instance.external_id)
                if instances:
                    remaining = await client.owned_instance_ids()
                    if any(i.external_id in remaining for i in instances):
                        raise HTTPException(503, "deletion_dependency_unavailable")
                for user in users:
                    other = await session.scalar(
                        select(Membership.tenant_id)
                        .where(Membership.user_id == user.id, Membership.tenant_id != tenant_id)
                        .order_by(Membership.tenant_id)
                        .limit(1)
                    )
                    if other is not None:
                        user.tenant_id = other
                        profile = await session.get(UserProfile, user.id, with_for_update=True)
                        if profile is not None:
                            profile.auth_version += 1
                await session.flush()
                session.add(
                    AuditEvent(
                        actor_id=actor.id,
                        tenant_id=None,
                        action="platform.organization.deleted",
                        target=str(tenant_id),
                        safe_metadata={"connections_removed": len(instances)},
                    )
                )
                # Existing FK cascades erase workspace data and its solo logins;
                # shared identities were rehomed above, preserving memberships.
                await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    except (EvolutionError, RedisError, SQLAlchemyError, TimeoutError):
        raise HTTPException(503, "deletion_dependency_unavailable") from None

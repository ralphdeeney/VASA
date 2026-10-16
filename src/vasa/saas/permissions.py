"""Explicit organization and platform permissions; ownership is not platform authority."""

from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy import select

from vasa.contracts.models import TenantContext
from vasa.control.auth import require_context
from vasa.control.models import User
from vasa.saas.models import Membership, OrganizationProfile, PlatformRole, UserProfile


def require_enabled(request: Request) -> None:
    if not request.app.state.settings.saas_enabled:
        raise HTTPException(404, "not_found")


async def require_member(
    request: Request, context: TenantContext, roles: set[str] | None = None
) -> Membership:
    require_enabled(request)
    async with request.app.state.database.session() as session:
        member = await session.scalar(
            select(Membership)
            .join(UserProfile, UserProfile.user_id == Membership.user_id)
            .join(OrganizationProfile, OrganizationProfile.tenant_id == Membership.tenant_id)
            .where(
                Membership.user_id == context.user_id,
                Membership.tenant_id == context.tenant_id,
                Membership.status == "active",
                UserProfile.status == "active",
                OrganizationProfile.status == "active",
            )
        )
    if member is None or (roles is not None and member.role not in roles):
        raise HTTPException(403, "permission_denied")
    return cast(Membership, member)


async def require_platform_admin(request: Request) -> User:
    require_enabled(request)
    context = await require_context(request)
    async with request.app.state.database.session() as session:
        user = await session.scalar(
            select(User)
            .join(PlatformRole, PlatformRole.user_id == User.id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                User.id == context.user_id,
                PlatformRole.role == "super_admin",
                UserProfile.status == "active",
            )
        )
    if user is None:
        raise HTTPException(403, "permission_denied")
    return cast(User, user)

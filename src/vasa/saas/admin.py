"""Platform administration: metadata directories and explicitly confirmed actions."""

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from vasa.control.auth import (
    SESSION_COOKIE,
    authenticate_password,
    check_login_limit,
    hash_password,
    require_csrf,
)
from vasa.control.models import User, WhatsAppInstance
from vasa.saas.models import (
    AuditEvent,
    AuthToken,
    Membership,
    OrganizationProfile,
    PlatformRole,
    RegistrationRequest,
    UserProfile,
)
from vasa.saas.permissions import require_enabled, require_platform_admin
from vasa.storage.models import Tenant

_ADMIN = Depends(require_platform_admin)

router = APIRouter(prefix="/api/saas/admin", dependencies=[Depends(require_enabled)])


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["active", "suspended"]
    confirm: Literal[True]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["approved", "rejected"]
    confirm: Literal[True]


def pagination(
    page: int, page_size: int, total: int, items: list[dict[str, object]]
) -> dict[str, object]:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/overview")
async def overview(request: Request, actor: User = _ADMIN) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        result = {}
        for name, model in (
            ("users", User),
            ("organizations", Tenant),
            ("connections", WhatsAppInstance),
            ("registrations", RegistrationRequest),
        ):
            query = select(func.count()).select_from(model)
            if model is RegistrationRequest:
                query = query.where(RegistrationRequest.status == "pending")
            result[name] = await session.scalar(query) or 0
    return result


@router.get("/users")
async def users(
    request: Request,
    actor: User = _ADMIN,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    search: str = Query("", max_length=100),
    status: Literal["active", "pending", "suspended"] | None = None,
    sort: Literal["email", "name", "created_at"] = "created_at",
) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        query = select(User, UserProfile).join(UserProfile, UserProfile.user_id == User.id)
        if search:
            query = query.where(
                or_(
                    User.email.contains(search, autoescape=True),
                    UserProfile.name.contains(search, autoescape=True),
                )
            )
        if status:
            query = query.where(UserProfile.status == status)
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        column = {
            "email": User.email,
            "name": UserProfile.name,
            "created_at": UserProfile.created_at,
        }[sort]
        rows = (
            await session.execute(
                query.order_by(column, User.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        ids = [u.id for u, _ in rows]
        memberships = (
            (
                await session.scalars(
                    select(Membership)
                    .where(Membership.user_id.in_(ids))
                    .order_by(Membership.tenant_id)
                )
            ).all()
            if ids
            else []
        )
        platforms = (
            set(
                (
                    await session.scalars(
                        select(PlatformRole.user_id).where(PlatformRole.user_id.in_(ids))
                    )
                ).all()
            )
            if ids
            else set()
        )
    return pagination(
        page,
        page_size,
        total,
        [
            {
                "id": str(u.id),
                "email": u.email,
                "name": p.name,
                "status": p.status,
                "email_verified": p.email_verified_at is not None,
                "platform_admin": u.id in platforms,
                "created_at": p.created_at.isoformat(),
                "memberships": [
                    {"tenant_id": str(m.tenant_id), "role": m.role, "status": m.status}
                    for m in memberships
                    if m.user_id == u.id
                ],
            }
            for u, p in rows
        ],
    )


@router.get("/organizations")
async def organizations(
    request: Request,
    actor: User = _ADMIN,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    search: str = Query("", max_length=100),
    status: Literal["active", "pending", "suspended"] | None = None,
    sort: Literal["name", "created_at"] = "created_at",
) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        query = select(Tenant, OrganizationProfile).join(
            OrganizationProfile, OrganizationProfile.tenant_id == Tenant.id
        )
        if search:
            query = query.where(Tenant.name.contains(search, autoescape=True))
        if status:
            query = query.where(OrganizationProfile.status == status)
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        column = Tenant.name if sort == "name" else OrganizationProfile.created_at
        rows = (
            await session.execute(
                query.order_by(column, Tenant.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    return pagination(
        page,
        page_size,
        total,
        [
            {
                "id": str(t.id),
                "name": t.name,
                "slug": p.slug,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for t, p in rows
        ],
    )


@router.get("/registrations")
async def registrations(
    request: Request,
    actor: User = _ADMIN,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    status: Literal["pending", "approved", "rejected"] | None = None,
) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        query = select(RegistrationRequest, User.email).join(
            User, User.id == RegistrationRequest.user_id
        )
        if status:
            query = query.where(RegistrationRequest.status == status)
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = (
            await session.execute(
                query.order_by(RegistrationRequest.created_at, RegistrationRequest.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    return pagination(
        page,
        page_size,
        total,
        [
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "tenant_id": str(r.tenant_id),
                "email": email,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r, email in rows
        ],
    )


@router.get("/audit")
async def audit(
    request: Request,
    actor: User = _ADMIN,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        total = await session.scalar(select(func.count()).select_from(AuditEvent)) or 0
        rows = (
            await session.scalars(
                select(AuditEvent)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    # No raw metadata rendering: audit producers may evolve independently.
    return pagination(
        page,
        page_size,
        total,
        [
            {
                "id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "tenant_id": str(r.tenant_id) if r.tenant_id else None,
                "action": r.action,
                "target": r.target,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    )


@router.get("/connections")
async def connections(
    request: Request,
    tenant_id: UUID,
    actor: User = _ADMIN,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, object]:
    # Platform tenant access is explicit and audited, and excludes provider IDs/tokens/QR.
    async with request.app.state.database.session() as session, session.begin():
        if await session.get(Tenant, tenant_id) is None:
            raise HTTPException(404, "not_found")
        query = select(WhatsAppInstance).where(WhatsAppInstance.tenant_id == tenant_id)
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = (
            await session.scalars(
                query.order_by(WhatsAppInstance.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        session.add(
            AuditEvent(
                actor_id=actor.id,
                tenant_id=tenant_id,
                action="platform.connections.view",
                target=str(tenant_id),
                safe_metadata={},
            )
        )
    return pagination(
        page,
        page_size,
        total,
        [{"id": str(r.id), "name": r.name, "tenant_id": str(r.tenant_id)} for r in rows],
    )


@router.get("/health")
async def health(request: Request, actor: User = _ADMIN) -> dict[str, object]:
    components = {"database": False, "redis": False}
    try:
        async with request.app.state.database.session() as session:
            await session.execute(select(1))
        components["database"] = True
    except Exception:
        pass
    try:
        components["redis"] = bool(await request.app.state.redis.ping())
    except Exception:
        pass
    return {
        "status": "ready" if all(components.values()) else "unavailable",
        "components": components,
    }


@router.post("/users/{user_id}/status", dependencies=[Depends(require_csrf)])
async def user_status(
    user_id: UUID,
    data: StatusInput,
    request: Request,
    actor: User = _ADMIN,
) -> dict[str, object]:
    if user_id == actor.id and data.status == "suspended":
        raise HTTPException(409, "self_suspension_denied")
    async with request.app.state.database.session() as session, session.begin():
        profile = await session.get(UserProfile, user_id, with_for_update=True)
        if profile is None:
            raise HTTPException(404, "not_found")
        if data.status == "suspended":
            platform = await session.get(PlatformRole, user_id)
            if platform is not None:
                raise HTTPException(409, "platform_admin_protected")
            owned = (
                await session.scalars(
                    select(Membership).where(
                        Membership.user_id == user_id,
                        Membership.status == "active",
                        Membership.role.in_(["owner", "admin"]),
                    )
                )
            ).all()
            for member in owned:
                await session.scalar(
                    select(Tenant).where(Tenant.id == member.tenant_id).with_for_update()
                )
                other = await session.scalar(
                    select(Membership.user_id)
                    .join(UserProfile, UserProfile.user_id == Membership.user_id)
                    .where(
                        Membership.tenant_id == member.tenant_id,
                        Membership.user_id != user_id,
                        Membership.role == member.role,
                        Membership.status == "active",
                        UserProfile.status == "active",
                    )
                    .limit(1)
                )
                if other is None:
                    raise HTTPException(409, "last_role_required")
        profile.status = data.status
        profile.auth_version += 1
        session.add(
            AuditEvent(
                actor_id=actor.id,
                action="platform.user.status",
                target=str(user_id),
                safe_metadata={"status": data.status},
            )
        )
    return {"status": "updated"}


class DeleteOrganizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: Literal[True]
    confirm_name: str = Field(min_length=1, max_length=200)
    current_password: str = Field(min_length=8, max_length=256, repr=False)


@router.post("/organizations/{tenant_id}/delete", dependencies=[Depends(require_csrf)])
async def delete_organization(
    tenant_id: UUID, data: DeleteOrganizationInput, request: Request, actor: User = _ADMIN
) -> dict[str, str]:
    from vasa.saas.deletion import erase_organization

    await check_login_limit(request)
    if not await authenticate_password(data.current_password, actor.password_hash):
        raise HTTPException(403, "invalid_current_password")
    await erase_organization(request, tenant_id, data.confirm_name, actor)
    return {"status": "deleted"}


@router.post("/organizations/{tenant_id}/status", dependencies=[Depends(require_csrf)])
async def organization_status(
    tenant_id: UUID,
    data: StatusInput,
    request: Request,
    actor: User = _ADMIN,
) -> dict[str, object]:
    if tenant_id == request.state.auth_session.tenant_id and data.status == "suspended":
        raise HTTPException(409, "self_organization_suspension_denied")
    async with request.app.state.database.session() as session, session.begin():
        org = await session.get(OrganizationProfile, tenant_id, with_for_update=True)
        if org is None:
            raise HTTPException(404, "not_found")
        org.status = data.status
        session.add(
            AuditEvent(
                actor_id=actor.id,
                tenant_id=tenant_id,
                action="platform.organization.status",
                target=str(tenant_id),
                safe_metadata={"status": data.status},
            )
        )
    return {"status": "updated"}


@router.post("/registrations/{registration_id}/review", dependencies=[Depends(require_csrf)])
async def review(
    registration_id: UUID,
    data: ReviewInput,
    request: Request,
    actor: User = _ADMIN,
) -> dict[str, object]:
    async with request.app.state.database.session() as session, session.begin():
        # Match identity verification's identity-first lock order.
        candidate = await session.get(RegistrationRequest, registration_id)
        if candidate is None:
            raise HTTPException(404, "not_found")
        await session.get(User, candidate.user_id, with_for_update=True)
        profile = await session.get(UserProfile, candidate.user_id, with_for_update=True)
        registration = await session.get(
            RegistrationRequest, registration_id, with_for_update=True, populate_existing=True
        )
        if registration is None:
            raise HTTPException(404, "not_found")
        if registration.status != "pending":
            raise HTTPException(409, "already_reviewed")
        org = await session.get(OrganizationProfile, registration.tenant_id)
        membership = await session.get(Membership, (registration.user_id, registration.tenant_id))
        if profile is None or org is None or membership is None:
            raise HTTPException(409, "invalid_registration")
        registration.status = data.status
        registration.reviewed_by, registration.reviewed_at = actor.id, datetime.now(UTC)
        if data.status == "approved" and profile.email_verified_at is not None:
            profile.status = org.status = membership.status = "active"
        elif data.status == "rejected":
            profile.status = org.status = "suspended"
            membership.status = "revoked"
            profile.auth_version += 1
        session.add(
            AuditEvent(
                actor_id=actor.id,
                tenant_id=registration.tenant_id,
                action="platform.registration.review",
                target=str(registration_id),
                safe_metadata={"status": data.status},
            )
        )
    return {"status": "reviewed"}


class PasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=8, max_length=256, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)


@router.get("/account")
async def account(request: Request, response: Response, actor: User = _ADMIN) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"email": actor.email, "username": "admin", "role": "super_admin"}


@router.post("/password", dependencies=[Depends(require_csrf)])
async def change_password(
    payload: PasswordChangeInput, request: Request, response: Response, actor: User = _ADMIN
) -> dict[str, str]:
    await check_login_limit(request)
    if payload.current_password == payload.new_password:
        raise HTTPException(422, "different_password_required")
    try:
        async with request.app.state.database.session() as session, session.begin():
            user = await session.scalar(select(User).where(User.id == actor.id).with_for_update())
            profile = await session.get(UserProfile, actor.id, with_for_update=True)
            if user is None or profile is None or profile.status != "active":
                raise HTTPException(403, "permission_denied")
            if not await authenticate_password(payload.current_password, user.password_hash):
                raise HTTPException(403, "invalid_current_password")
            try:
                user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
            except ValueError:
                raise HTTPException(422, "invalid_password") from None
            profile.auth_version += 1
            await session.execute(
                update(AuthToken)
                .where(
                    AuthToken.user_id == actor.id,
                    AuthToken.purpose == "password_reset",
                    AuthToken.consumed_at.is_(None),
                )
                .values(consumed_at=datetime.now(UTC))
            )
            session.add(
                AuditEvent(
                    actor_id=actor.id,
                    tenant_id=None,
                    action="platform.password_changed",
                    target=str(actor.id),
                    safe_metadata={},
                )
            )
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "password_changed"}

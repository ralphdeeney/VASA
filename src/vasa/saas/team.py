"""Tenant-scoped team, profile and workspace operations."""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from vasa.contracts.models import TenantContext
from vasa.control.auth import require_context, require_csrf
from vasa.control.models import User
from vasa.saas.models import (
    AuditEvent,
    Invitation,
    Membership,
    OrganizationProfile,
    PlatformRole,
    UserProfile,
)
from vasa.saas.permissions import require_enabled, require_member
from vasa.storage.models import Tenant
from vasa.tools.webhooks_config import load_webhooks

router = APIRouter(prefix="/api/saas", dependencies=[Depends(require_enabled)])
_CONTEXT = Depends(require_context)
_CSRF = Depends(require_csrf)
MANAGERS = {"owner", "admin"}


@router.get("/integrations")
async def integrations(request: Request, context: TenantContext = _CONTEXT) -> dict[str, object]:
    await require_member(request, context, MANAGERS)
    tool = None
    try:
        tool, specs = await asyncio.to_thread(
            load_webhooks, request.app.state.settings.webhook_config_path, context
        )
        # The existing loader validates the private file, tenant, action names,
        # destination policy, schemas and credential bindings. Return no specs.
        return {
            "items": [
                {"name": name, "kind": "tool_gateway", "status": "configured"}
                for spec in specs
                for name in spec["parameters"]["properties"]["action"]["enum"]
            ]
        }
    except Exception:
        raise HTTPException(503, "unavailable") from None
    finally:
        if tool is not None:
            await tool.aclose()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkspaceInput(Input):
    tenant_id: UUID = Field(strict=False)


class InvitationInput(Input):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["admin", "member"] = "member"

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("invalid_email")
        return value


class TokenInput(Input):
    token: str = Field(min_length=32, max_length=128)


class MemberInput(Input):
    role: Literal["owner", "admin", "member"]
    status: Literal["active", "revoked"]
    confirm: Literal[True]


class NameInput(Input):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("invalid_name")
        return value.strip()


@router.get("/workspaces")
async def workspaces(request: Request, context: TenantContext = _CONTEXT) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        rows = (
            await session.execute(
                select(Membership, Tenant, OrganizationProfile)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .join(OrganizationProfile, OrganizationProfile.tenant_id == Tenant.id)
                .where(Membership.user_id == context.user_id, Membership.status == "active")
                .order_by(Tenant.name, Tenant.id)
                .limit(100)
            )
        ).all()
    return {
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "role": m.role,
                "status": p.status,
                "selected": t.id == context.tenant_id,
            }
            for m, t, p in rows
        ]
    }


@router.post("/workspace")
async def select_workspace(
    data: WorkspaceInput, request: Request, context: TenantContext = _CSRF
) -> dict[str, object]:
    await require_member(request, TenantContext(tenant_id=data.tenant_id, user_id=context.user_id))
    auth = request.state.auth_session
    # Atomic Redis update retains CSRF, auth_version, and the existing expiry.
    changed = await request.app.state.redis.eval(
        "local p=redis.call('GET',KEYS[1]); if not p then return 0 end; "
        "local d=cjson.decode(p); if d.user_id~=ARGV[1] or d.csrf_token~=ARGV[2] "
        "then return 0 end; d.tenant_id=ARGV[3]; "
        "redis.call('SET',KEYS[1],cjson.encode(d),'KEEPTTL'); return 1",
        1,
        auth.key,
        str(context.user_id),
        auth.csrf_token,
        str(data.tenant_id),
    )
    if changed != 1:
        raise HTTPException(401, "authentication_required")
    return {"status": "selected", "tenant_id": str(data.tenant_id)}


@router.get("/team")
async def team(request: Request, context: TenantContext = _CONTEXT) -> dict[str, object]:
    await require_member(request, context, MANAGERS)
    async with request.app.state.database.session() as session:
        rows = (
            await session.execute(
                select(Membership, User, UserProfile)
                .join(User, User.id == Membership.user_id)
                .join(UserProfile, UserProfile.user_id == User.id)
                .where(Membership.tenant_id == context.tenant_id)
                .order_by(User.email)
                .limit(100)
            )
        ).all()
    return {
        "items": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "name": p.name,
                "role": m.role,
                "status": m.status,
            }
            for m, u, p in rows
        ]
    }


@router.post("/invitations", status_code=201)
async def invite(
    data: InvitationInput, request: Request, context: TenantContext = _CSRF
) -> dict[str, object]:
    member = await require_member(request, context, MANAGERS)
    if data.role == "admin" and member.role != "owner":
        raise HTTPException(403, "permission_denied")
    mailer = request.app.state.mailer
    origin = request.app.state.settings.public_origin
    if not mailer.configured() or not origin:
        raise HTTPException(503, "email_unavailable")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    async with request.app.state.database.session() as session, session.begin():
        # Per-tenant bounded invite creation; no external resources are created.
        await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id).with_for_update())
        pending = await session.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.tenant_id == context.tenant_id,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
        if pending is not None and pending >= 100:
            raise HTTPException(429, "invitation_limit")
        existing = await session.scalar(
            select(Invitation.id).where(
                Invitation.tenant_id == context.tenant_id,
                Invitation.email == data.email,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
        if existing is not None:
            raise HTTPException(409, "invitation_pending")
        invitation = Invitation(
            tenant_id=context.tenant_id,
            email=data.email,
            role=data.role,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=now + timedelta(days=2),
        )
        session.add(invitation)
        await session.flush()
        session.add(
            AuditEvent(
                actor_id=context.user_id,
                tenant_id=context.tenant_id,
                action="team.invite",
                target=str(invitation.id),
                safe_metadata={"role": data.role},
            )
        )
        # No invitation or token is exposed through the API. Only the intended inbox
        # receives the opaque single-use token; the database stores its hash.
        try:
            await mailer.send(
                data.email,
                "VASA workspace invitation",
                "Accept your VASA invitation: "
                + origin.rstrip("/")
                + "/accept-invitation#token="
                + token,
            )
        except Exception:
            raise HTTPException(503, "email_unavailable") from None
    return {"status": "invited"}


@router.post("/accept-invitation")
async def accept_invitation(
    data: TokenInput, request: Request, context: TenantContext = _CSRF
) -> dict[str, object]:
    now = datetime.now(UTC)
    async with request.app.state.database.session() as session, session.begin():
        invitation = await session.scalar(
            select(Invitation)
            .where(
                Invitation.token_hash == hashlib.sha256(data.token.encode()).hexdigest(),
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
            .with_for_update()
        )
        user = await session.get(User, context.user_id)
        profile = await session.get(UserProfile, context.user_id)
        if (
            invitation is None
            or user is None
            or profile is None
            or user.email != invitation.email
            or profile.email_verified_at is None
            or profile.status != "active"
        ):
            raise HTTPException(400, "invalid_token")
        org = await session.get(OrganizationProfile, invitation.tenant_id)
        if org is None or org.status != "active":
            raise HTTPException(400, "invalid_token")
        member = await session.get(Membership, (user.id, invitation.tenant_id))
        if member is not None:
            raise HTTPException(409, "membership_exists")
        session.add(
            Membership(
                user_id=user.id,
                tenant_id=invitation.tenant_id,
                role=invitation.role,
                status="active",
            )
        )
        invitation.accepted_at = now
        session.add(
            AuditEvent(
                actor_id=user.id,
                tenant_id=invitation.tenant_id,
                action="team.accept_invitation",
                target=str(invitation.id),
                safe_metadata={"role": invitation.role},
            )
        )
    return {"status": "accepted"}


@router.patch("/team/{user_id}")
async def update_member(
    user_id: UUID,
    data: MemberInput,
    request: Request,
    context: TenantContext = _CSRF,
) -> dict[str, object]:
    await require_member(request, context, MANAGERS)
    async with request.app.state.database.session() as session, session.begin():
        # Serialize role changes for the organization to preserve its last owner.
        await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id).with_for_update())
        actor = await session.get(Membership, (context.user_id, context.tenant_id))
        if actor is None or actor.status != "active" or actor.role not in MANAGERS:
            raise HTTPException(403, "permission_denied")
        member = await session.get(Membership, (user_id, context.tenant_id))
        if member is None:
            raise HTTPException(404, "not_found")
        if actor.role != "owner" and (member.role in MANAGERS or data.role in MANAGERS):
            raise HTTPException(403, "permission_denied")
        members = (
            await session.scalars(
                select(Membership)
                .join(UserProfile, UserProfile.user_id == Membership.user_id)
                .where(
                    Membership.tenant_id == context.tenant_id,
                    Membership.status == "active",
                    UserProfile.status == "active",
                )
            )
        ).all()
        for role in ("owner", "admin"):
            if (
                member.role == role
                and member.status == "active"
                and (data.role != role or data.status != "active")
                and not any(m.user_id != user_id and m.role == role for m in members)
            ):
                raise HTTPException(409, "last_role_required")
        member.role, member.status = data.role, data.status
        session.add(
            AuditEvent(
                actor_id=context.user_id,
                tenant_id=context.tenant_id,
                action="team.update",
                target=str(user_id),
                safe_metadata={"role": data.role, "status": data.status},
            )
        )
    return {"status": "updated"}


@router.get("/profile")
async def profile(request: Request, context: TenantContext = _CONTEXT) -> dict[str, object]:
    async with request.app.state.database.session() as session:
        user = await session.get(User, context.user_id)
        data = await session.get(UserProfile, context.user_id)
        platform_role = await session.get(PlatformRole, context.user_id)
    if data is None or user is None:
        raise HTTPException(404, "not_found")
    return {
        "name": data.name,
        "email": user.email,
        "status": data.status,
        "email_verified": data.email_verified_at is not None,
        "platform_admin": platform_role is not None and platform_role.role == "super_admin",
    }


@router.patch("/profile")
async def update_profile(
    data: NameInput, request: Request, context: TenantContext = _CSRF
) -> dict[str, object]:
    async with request.app.state.database.session() as session, session.begin():
        row = await session.get(UserProfile, context.user_id)
        if row is None:
            raise HTTPException(404, "not_found")
        row.name = data.name
        session.add(
            AuditEvent(
                actor_id=context.user_id,
                tenant_id=context.tenant_id,
                action="profile.update",
                target=str(context.user_id),
                safe_metadata={},
            )
        )
    return {"status": "updated"}


@router.get("/organization")
async def organization(request: Request, context: TenantContext = _CONTEXT) -> dict[str, object]:
    await require_member(request, context)
    async with request.app.state.database.session() as session:
        org = await session.get(OrganizationProfile, context.tenant_id)
        tenant = await session.get(Tenant, context.tenant_id)
    if org is None or tenant is None:
        raise HTTPException(404, "not_found")
    return {"id": str(tenant.id), "name": tenant.name, "slug": org.slug, "status": org.status}


@router.patch("/organization")
async def update_organization(
    data: NameInput, request: Request, context: TenantContext = _CSRF
) -> dict[str, object]:
    await require_member(request, context, MANAGERS)
    async with request.app.state.database.session() as session, session.begin():
        tenant = await session.get(Tenant, context.tenant_id)
        if tenant is None:
            raise HTTPException(404, "not_found")
        tenant.name = data.name
        session.add(
            AuditEvent(
                actor_id=context.user_id,
                tenant_id=context.tenant_id,
                action="organization.update",
                target=str(context.tenant_id),
                safe_metadata={},
            )
        )
    return {"status": "updated"}

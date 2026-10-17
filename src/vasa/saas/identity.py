"""Explicit opt-in public identity workflows; no provider resource creation."""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.config import Settings
from vasa.control.auth import check_login_limit, check_origin, hash_password
from vasa.control.models import User
from vasa.saas.mailer import Mailer, MailUnavailable, SMTPMailer
from vasa.saas.models import (
    AuditEvent,
    AuthToken,
    Membership,
    OrganizationProfile,
    RegistrationRequest,
    UserProfile,
)
from vasa.storage.database import Database
from vasa.storage.models import Tenant


async def identity_guard(request: Request) -> None:
    if not request.app.state.settings.saas_enabled:
        raise HTTPException(404, "not_found")
    check_origin(request)
    await check_login_limit(request)


router = APIRouter(prefix="/api/saas", dependencies=[Depends(identity_guard)])
site_router = APIRouter(prefix="/api/site")


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def email_value(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or not all(value.split("@")):
            raise ValueError("invalid email")
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("invalid email")
        return value


class SignupInput(EmailInput):
    name: str = Field(min_length=1, max_length=200)
    business_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=256, repr=False)

    @field_validator("name", "business_name")
    @classmethod
    def name_value(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("invalid name")
        return value


class ContactInput(EmailInput):
    name: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000, repr=False)

    @field_validator("name", "message")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("invalid text")
        return value


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$", repr=False)


class ResetInput(TokenInput):
    password: str = Field(min_length=8, max_length=256, repr=False)


def _mailer(request: Request) -> Mailer:
    mailer = getattr(request.app.state, "mailer", None)
    return cast(Mailer, mailer) if mailer is not None else SMTPMailer(request.app.state.settings)


def _delivery(request: Request) -> Mailer:
    mailer = _mailer(request)
    if not mailer.configured() or not request.app.state.settings.public_origin:
        raise HTTPException(503, "email_unavailable")
    return mailer


@site_router.post("/contact", status_code=202)
async def contact(payload: ContactInput, request: Request) -> dict[str, str]:
    check_origin(request)
    await check_login_limit(request)
    mailer = _mailer(request)
    settings: Settings = request.app.state.settings
    if not mailer.configured() or not settings.contact_recipient:
        raise HTTPException(503, "email_unavailable")
    try:
        await mailer.send(
            settings.contact_recipient,
            "VASA website contact request",
            f"Name: {payload.name}\nEmail: {payload.email}\n\n{payload.message}",
        )
    except MailUnavailable:
        raise HTTPException(503, "email_unavailable") from None
    return {"status": "request_received"}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token(user_id: UUID, purpose: str) -> tuple[AuthToken, str]:
    raw = secrets.token_urlsafe(32)
    token = AuthToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=_digest(raw),
        expires_at=datetime.now(UTC) + timedelta(hours=1 if purpose == "password_reset" else 24),
    )
    return token, raw


async def _send(request: Request, mailer: Mailer, email: str, raw: str, purpose: str) -> None:
    settings: Settings = request.app.state.settings
    page = "reset-password" if purpose == "password_reset" else "verify-email"
    subject = (
        "Reset your VASA password" if purpose == "password_reset" else "Verify your VASA email"
    )
    instruction = (
        "Choose a new password using the private link below. It expires in one hour."
        if purpose == "password_reset"
        else "Verify your email using the private link below. It expires in 24 hours."
    )
    await mailer.send(
        email,
        subject,
        "VASA — Your business. Always available.\n\n"
        + instruction
        + "\nIf you did not request this, you can ignore this email.\n\n"
        + f"{settings.public_origin.rstrip('/')}/{page}#token={raw}",
    )


async def _locked_token(
    session: AsyncSession, raw: str, purpose: str
) -> tuple[AuthToken, User, UserProfile]:
    digest = _digest(raw)
    user_id = await session.scalar(
        select(AuthToken.user_id).where(
            AuthToken.token_hash == digest, AuthToken.purpose == purpose
        )
    )
    if user_id is None:
        raise HTTPException(400, "invalid_token")
    # All token issuance/consumption locks the identity first, preventing deadlocks
    # between resend, reset and concurrent single-use token consumption.
    user = await session.get(User, user_id, with_for_update=True)
    profile = await session.get(UserProfile, user_id, with_for_update=True)
    token = await session.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == digest, AuthToken.purpose == purpose)
        .with_for_update()
    )
    if (
        user is None
        or profile is None
        or token is None
        or token.consumed_at is not None
        or token.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(400, "invalid_token")
    return token, user, profile


@router.post("/signup", status_code=202)
async def signup(payload: SignupInput, request: Request) -> dict[str, str]:
    mailer = _delivery(request)
    try:
        password_hash = await asyncio.to_thread(hash_password, payload.password)
    except ValueError:
        raise HTTPException(422, "invalid_password") from None
    database: Database = request.app.state.database
    try:
        async with database.session() as session, session.begin():
            existing = await session.scalar(select(User.id).where(User.email == payload.email))
            if existing is not None:
                return {"status": "verification_pending"}
            tenant = Tenant(id=uuid4(), name=payload.business_name)
            session.add(tenant)
            await session.flush()
            user = User(
                id=uuid4(), tenant_id=tenant.id, email=payload.email, password_hash=password_hash
            )
            session.add(user)
            await session.flush()
            session.add_all(
                [
                    UserProfile(user_id=user.id, name=payload.name, status="pending"),
                    OrganizationProfile(
                        tenant_id=tenant.id, slug=f"workspace-{tenant.id.hex}", status="pending"
                    ),
                    Membership(
                        user_id=user.id, tenant_id=tenant.id, role="owner", status="pending"
                    ),
                    RegistrationRequest(user_id=user.id, tenant_id=tenant.id, status="pending"),
                    AuditEvent(actor_id=user.id, tenant_id=tenant.id, action="identity.signup"),
                ]
            )
            token, raw = _token(user.id, "verify_email")
            session.add(token)
            await session.flush()
            await _send(request, mailer, user.email, raw, "verify_email")
    except IntegrityError:
        return {"status": "verification_pending"}
    except MailUnavailable:
        raise HTTPException(503, "email_unavailable") from None
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None
    return {"status": "verification_pending"}


@router.post("/verify-email")
async def verify_email(payload: TokenInput, request: Request) -> dict[str, str]:
    database: Database = request.app.state.database
    try:
        async with database.session() as session, session.begin():
            token, user, profile = await _locked_token(session, payload.token, "verify_email")
            now = datetime.now(UTC)
            if profile.status not in {"pending", "active"} or profile.email_verified_at is not None:
                raise HTTPException(400, "invalid_token")
            registration = await session.scalar(
                select(RegistrationRequest)
                .where(RegistrationRequest.user_id == user.id)
                .with_for_update()
            )
            if registration is not None and registration.status == "rejected":
                raise HTTPException(400, "invalid_token")
            profile.email_verified_at = now
            token.consumed_at = now
            session.add(
                AuditEvent(
                    actor_id=user.id, tenant_id=user.tenant_id, action="identity.verify_email"
                )
            )
            approved = registration is not None and registration.status == "approved"
            if profile.status == "pending" and (
                approved or not request.app.state.settings.registration_approval_required
            ):
                profile.status = "active"
                await session.execute(
                    update(OrganizationProfile)
                    .where(OrganizationProfile.tenant_id == user.tenant_id)
                    .values(status="active")
                )
                await session.execute(
                    update(Membership)
                    .where(Membership.user_id == user.id, Membership.tenant_id == user.tenant_id)
                    .values(status="active")
                )
                await session.execute(
                    update(RegistrationRequest)
                    .where(RegistrationRequest.user_id == user.id)
                    .values(status="approved", reviewed_at=now)
                )
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None
    return {"status": "verified"}


async def _request_token(payload: EmailInput, request: Request, purpose: str) -> dict[str, str]:
    mailer = _delivery(request)
    database: Database = request.app.state.database
    try:
        async with database.session() as session, session.begin():
            user = await session.scalar(
                select(User).where(User.email == payload.email).with_for_update()
            )
            if user is not None:
                profile = await session.get(UserProfile, user.id, with_for_update=True)
                eligible = profile is not None and (
                    (
                        purpose == "verify_email"
                        and profile.status in {"pending", "active"}
                        and profile.email_verified_at is None
                    )
                    or (purpose == "password_reset" and profile.status == "active")
                )
                if eligible:
                    now = datetime.now(UTC)
                    await session.execute(
                        update(AuthToken)
                        .where(
                            AuthToken.user_id == user.id,
                            AuthToken.purpose == purpose,
                            AuthToken.consumed_at.is_(None),
                        )
                        .values(consumed_at=now)
                    )
                    token, raw = _token(user.id, purpose)
                    session.add(token)
                    await session.flush()
                    await _send(request, mailer, user.email, raw, purpose)
    except (SQLAlchemyError, MailUnavailable):
        # Same response for existing/missing identities and private delivery failures.
        pass
    return {"status": "request_received"}


@router.post("/resend-verification", status_code=202)
async def resend(payload: EmailInput, request: Request) -> dict[str, str]:
    return await _request_token(payload, request, "verify_email")


@router.post("/forgot-password", status_code=202)
async def forgot(payload: EmailInput, request: Request) -> dict[str, str]:
    return await _request_token(payload, request, "password_reset")


@router.post("/reset-password")
async def reset(payload: ResetInput, request: Request) -> dict[str, str]:
    try:
        password_hash = await asyncio.to_thread(hash_password, payload.password)
    except ValueError:
        raise HTTPException(422, "invalid_password") from None
    database: Database = request.app.state.database
    try:
        async with database.session() as session, session.begin():
            token, user, profile = await _locked_token(session, payload.token, "password_reset")
            now = datetime.now(UTC)
            if profile.status != "active":
                raise HTTPException(400, "invalid_token")
            user.password_hash = password_hash
            profile.auth_version += 1
            session.add(
                AuditEvent(
                    actor_id=user.id, tenant_id=user.tenant_id, action="identity.password_reset"
                )
            )
            await session.execute(
                update(AuthToken)
                .where(
                    AuthToken.user_id == user.id,
                    AuthToken.purpose == "password_reset",
                    AuthToken.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None
    return {"status": "password_reset"}

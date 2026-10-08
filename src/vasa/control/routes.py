import json
import logging
import secrets
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.contracts.models import TenantContext
from vasa.control.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    AuthSession,
    authenticate_password,
    check_login_limit,
    check_origin,
    require_context,
    require_csrf,
    session_key,
)
from vasa.control.models import User, WhatsAppInstance
from vasa.evolution.client import EvolutionCalls
from vasa.evolution.models import EvolutionError
from vasa.storage.database import Database

router = APIRouter()
logger = logging.getLogger("vasa.control")
Authenticated = Annotated[TenantContext, Depends(require_context)]
Mutation = Annotated[TenantContext, Depends(require_csrf)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256, repr=False)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if email.count("@") != 1 or any(character.isspace() for character in email):
            raise ValueError("invalid email")
        if not all(email.split("@")):
            raise ValueError("invalid email")
        return email


class InstanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("instance name is required")
        return name


def _evolution(request: Request) -> EvolutionCalls:
    client = request.app.state.evolution
    if client is None:
        raise HTTPException(503, "unavailable")
    return cast(EvolutionCalls, client)


def _upstream_error(error: EvolutionError) -> HTTPException:
    code = "license_required" if error.code == "license_required" else "unavailable"
    return HTTPException(503, code)


@router.post("/api/auth/login")
async def login(payload: LoginInput, request: Request, response: Response) -> dict[str, str]:
    check_origin(request)
    await check_login_limit(request)
    database: Database = request.app.state.database
    cache: Redis = request.app.state.redis
    try:
        async with database.session() as session:
            result = await session.execute(select(User).where(User.email == payload.email))
            user = result.scalar_one_or_none()
        if not await authenticate_password(payload.password, user.password_hash if user else None):
            raise HTTPException(401, "invalid_credentials")
        assert user is not None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        old_token = request.cookies.get(SESSION_COOKIE)
        if old_token and len(old_token) == 43:
            await cache.delete(session_key(old_token))
        await cache.set(
            session_key(token),
            json.dumps(
                {"user_id": str(user.id), "tenant_id": str(user.tenant_id), "csrf_token": csrf}
            ),
            ex=SESSION_TTL_SECONDS,
        )
    except (RedisError, SQLAlchemyError):
        raise HTTPException(503, "unavailable") from None
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.app.state.settings.environment == "production",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf}


@router.get("/api/auth/me")
async def me(request: Request, response: Response, context: Authenticated) -> dict[str, str]:
    session = cast(AuthSession, request.state.auth_session)
    response.headers["Cache-Control"] = "no-store"
    return {"email": session.email, "csrf_token": session.csrf_token}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response, context: Mutation) -> dict[str, str]:
    session = cast(AuthSession, request.state.auth_session)
    cache: Redis = request.app.state.redis
    try:
        await cache.delete(session.key)
    except RedisError:
        raise HTTPException(503, "unavailable") from None
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "logged_out"}


async def _instance(request: Request, context: TenantContext, id: UUID) -> WhatsAppInstance:
    database: Database = request.app.state.database
    try:
        async with database.session() as session:
            result = await session.execute(
                select(WhatsAppInstance).where(
                    WhatsAppInstance.id == id, WhatsAppInstance.tenant_id == context.tenant_id
                )
            )
            instance = result.scalar_one_or_none()
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None
    if instance is None:
        raise HTTPException(404, "instance_not_found")
    return instance


@router.get("/api/whatsapp/instances")
async def list_instances(request: Request, context: Authenticated) -> list[dict[str, str]]:
    database: Database = request.app.state.database
    try:
        async with database.session() as session:
            result = await session.execute(
                select(WhatsAppInstance)
                .where(WhatsAppInstance.tenant_id == context.tenant_id)
                .order_by(WhatsAppInstance.id)
            )
            return [
                {"id": str(instance.id), "name": instance.name} for instance in result.scalars()
            ]
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


@router.post("/api/whatsapp/instances", status_code=201)
async def create_instance(
    payload: InstanceInput, request: Request, context: Mutation
) -> dict[str, str]:
    client = _evolution(request)
    database: Database = request.app.state.database
    instance_id = uuid4()
    instance = WhatsAppInstance(
        id=instance_id,
        tenant_id=context.tenant_id,
        external_id=str(instance_id),
        name=payload.name,
    )
    created = False
    try:
        async with database.session() as session, session.begin():
            session.add(instance)
            await session.flush()
            await client.create_instance(instance.external_id, instance.name)
            created = True
    except EvolutionError as error:
        raise _upstream_error(error) from None
    except SQLAlchemyError:
        if created:
            try:
                await client.delete_instance(instance.external_id)
            except EvolutionError:
                logger.warning(
                    "compensation failed", extra={"event": "instance_compensation_failed"}
                )
        raise HTTPException(503, "unavailable") from None
    return {"id": str(instance.id), "name": instance.name}


@router.get("/api/whatsapp/instances/{id}/status")
async def instance_status(
    id: UUID, request: Request, context: Authenticated
) -> dict[str, bool | str]:
    instance = await _instance(request, context, id)
    try:
        status = await _evolution(request).status(instance.external_id)
    except EvolutionError as error:
        raise _upstream_error(error) from None
    return {"connected": status.connected, "logged_in": status.logged_in, "name": status.name}


@router.get("/api/whatsapp/instances/{id}/qr")
async def instance_qr(id: UUID, request: Request, context: Authenticated) -> dict[str, str]:
    instance = await _instance(request, context, id)
    try:
        qr = await _evolution(request).qr(instance.external_id)
    except EvolutionError as error:
        raise _upstream_error(error) from None
    return {"qrcode": qr.qrcode, "passkey_stage": qr.passkey_stage}


@router.post("/api/whatsapp/instances/{id}/connect")
async def connect_instance(id: UUID, request: Request, context: Mutation) -> dict[str, str]:
    instance = await _instance(request, context, id)
    try:
        await _evolution(request).connect(instance.external_id)
    except EvolutionError as error:
        raise _upstream_error(error) from None
    return {"status": "connecting"}


@router.post("/api/whatsapp/instances/{id}/disconnect")
async def disconnect_instance(id: UUID, request: Request, context: Mutation) -> dict[str, str]:
    instance = await _instance(request, context, id)
    try:
        await _evolution(request).disconnect(instance.external_id)
    except EvolutionError as error:
        raise _upstream_error(error) from None
    return {"status": "disconnected"}

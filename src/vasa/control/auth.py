import asyncio
import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.contracts.models import TenantContext
from vasa.control.models import User

SESSION_COOKIE = "vasa_session"
SESSION_TTL_SECONDS = 28800
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 60
_PASSWORD_SLOTS = threading.BoundedSemaphore(4)

_LOGIN_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def hash_password(password: str) -> str:
    if not 8 <= len(password) <= 256 or len(password.encode()) > 1024:
        raise ValueError("password must contain between 8 and 256 characters")
    salt = secrets.token_bytes(16)
    with _PASSWORD_SLOTS:
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


_DUMMY_HASH = hash_password("unusable-missing-user-password")


def verify_password(password: str, stored: str) -> bool:
    if not 8 <= len(password) <= 256 or len(password.encode()) > 1024:
        return False
    valid = True
    try:
        algorithm, n, r, p, salt_hex, digest_hex = stored.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            raise ValueError("invalid password hash")
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError("invalid password hash")
    except ValueError:
        salt = bytes.fromhex(_DUMMY_HASH.split("$")[4])
        expected = bytes.fromhex(_DUMMY_HASH.split("$")[5])
        valid = False
    with _PASSWORD_SLOTS:
        actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual, expected) and valid


def session_key(token: str) -> str:
    return f"vasa:auth:session:{hashlib.sha256(token.encode()).hexdigest()}"


def login_key(address: str) -> str:
    return f"vasa:auth:login:{hashlib.sha256(address.encode()).hexdigest()}"


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "invalid_origin")
    if origin is None:
        return
    try:
        supplied = urlsplit(origin)
        expected = urlsplit(str(request.base_url))
        canonical = getattr(request.app.state.settings, "public_origin", "")
        if canonical:
            public = urlsplit(canonical)
            # A trusted configured origin repairs TLS termination without trusting
            # client-controlled forwarding headers or accepting another Host.
            if request.headers.get("host") == public.netloc:
                expected = public
    except ValueError:
        raise HTTPException(403, "invalid_origin") from None
    if (
        supplied.scheme not in {"http", "https"}
        or supplied.scheme != expected.scheme
        or supplied.netloc != expected.netloc
        or supplied.path not in {"", "/"}
        or supplied.query
        or supplied.fragment
    ):
        raise HTTPException(403, "invalid_origin")


async def check_login_limit(request: Request) -> None:
    address = request.client.host if request.client else "unknown"
    cache: Redis = request.app.state.redis
    try:
        count = await cast(
            Awaitable[int],
            cache.eval(_LOGIN_LIMIT_SCRIPT, 1, login_key(address), str(LOGIN_WINDOW_SECONDS)),
        )
    except RedisError:
        raise HTTPException(503, "unavailable") from None
    if count > LOGIN_LIMIT:
        raise HTTPException(429, "too_many_attempts")


@dataclass(frozen=True, slots=True)
class AuthSession:
    user_id: UUID
    tenant_id: UUID
    email: str
    csrf_token: str
    key: str
    auth_version: int = 0


async def identity_schema_present(database: AsyncSession, enabled: bool) -> bool:
    if enabled:
        return True
    # A feature rollback must not revive suspended/revoked migrated identities.
    # This catalog probe works on revision 0006 without querying absent tables.
    return await database.scalar(text("SELECT to_regclass('public.user_profiles')")) is not None


async def validate_saas_identity(
    database: AsyncSession, user_id: UUID, *, enabled: bool = True
) -> int:
    from vasa.saas.models import UserProfile

    profile = await database.get(UserProfile, user_id)
    if profile is None and not enabled:
        return 0  # Existing operator-created legacy users need no SaaS profile.
    if profile is None or profile.status != "active":
        raise HTTPException(403, "account_inactive")
    if profile.email_verified_at is None and not profile.legacy_access:
        raise HTTPException(403, "email_verification_required")
    if not enabled and not profile.legacy_access:
        raise HTTPException(403, "account_inactive")
    return profile.auth_version


async def require_context(request: Request) -> TenantContext:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None or len(token) != 43:
        raise HTTPException(401, "authentication_required")
    key = session_key(token)
    try:
        cache: Redis = request.app.state.redis
        payload = await cache.get(key)
        if payload is None:
            raise HTTPException(401, "authentication_required")
        if len(payload) > 4096:
            raise ValueError("invalid session")
        data = json.loads(payload)
        if not isinstance(data, dict) or set(data) not in (
            {"user_id", "tenant_id", "csrf_token"},
            {"user_id", "tenant_id", "csrf_token", "auth_version"},
        ):
            raise ValueError("invalid session")
        auth_version = data.get("auth_version", 0)
        if type(auth_version) is not int or auth_version < 0:
            raise ValueError("invalid session")
        if not isinstance(data["user_id"], str) or not isinstance(data["tenant_id"], str):
            raise ValueError("invalid session")
        user_id, tenant_id = UUID(data["user_id"]), UUID(data["tenant_id"])
        csrf_token = data["csrf_token"]
        if not isinstance(csrf_token, str) or len(csrf_token) != 43:
            raise ValueError("invalid session")
        async with request.app.state.database.session() as database:
            saas = getattr(request.app.state.settings, "saas_enabled", False)
            query = select(User).where(User.id == user_id)
            if not saas:
                query = query.where(User.tenant_id == tenant_id)
            result = await database.execute(query)
            user = result.scalar_one_or_none()
            if user is not None and await identity_schema_present(database, saas):
                if await validate_saas_identity(database, user_id, enabled=saas) != auth_version:
                    raise HTTPException(401, "authentication_required")
            if user is not None and saas:
                from vasa.saas.models import Membership, OrganizationProfile

                membership = await database.get(Membership, (user_id, tenant_id))
                organization = await database.get(OrganizationProfile, tenant_id)
                if (
                    membership is None
                    or membership.status != "active"
                    or organization is None
                    or organization.status != "active"
                ):
                    raise HTTPException(403, "workspace_inactive")
                request.state.membership_role = membership.role
        if user is None:
            raise HTTPException(401, "authentication_required")
        request.state.auth_session = AuthSession(
            user_id, tenant_id, user.email, csrf_token, key, auth_version
        )
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "authentication_required") from None
    except (RedisError, SQLAlchemyError):
        raise HTTPException(503, "unavailable") from None
    return TenantContext(tenant_id=tenant_id, user_id=user_id)


async def require_csrf(request: Request) -> TenantContext:
    context = await require_context(request)
    check_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied.encode(), request.state.auth_session.csrf_token.encode()):
        raise HTTPException(403, "invalid_csrf")
    personal = {
        "/api/auth/logout",
        "/api/saas/workspace",
        "/api/saas/profile",
        "/api/saas/accept-invitation",
    }
    if (
        getattr(request.app.state.settings, "saas_enabled", False)
        and request.url.path not in personal
        # Every platform endpoint independently requires a platform role; an
        # organization role must neither grant nor obstruct that authority.
        and not request.url.path.startswith("/api/saas/admin/")
        and request.state.membership_role not in {"owner", "admin"}
    ):
        raise HTTPException(403, "permission_denied")
    return context


async def authenticate_password(password: str, stored: str | None) -> bool:
    # Offload the CPU-native KDF; API rate limiting bounds accepted login work.
    valid = await asyncio.to_thread(verify_password, password, stored or _DUMMY_HASH)
    return valid and stored is not None

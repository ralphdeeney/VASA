"""Loopback-only disposable browser fixture; never include in production routing."""

import os
import re
import secrets
from contextlib import asynccontextmanager
from hashlib import sha256
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from vasa.app import create_app
from vasa.config import Settings
from vasa.control.models import User
from vasa.saas.models import AuditEvent, PlatformRole
from vasa.storage.models import Tenant

database_url = os.environ.get(
    "VASA_TEST_DATABASE_URL", "postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa"
)
redis_url = os.environ.get("VASA_TEST_REDIS_URL", "redis://127.0.0.1:6389/0")
db_parts = urlsplit(database_url)
redis_parts = urlsplit(redis_url)
if (
    db_parts.scheme != "postgresql+asyncpg"
    or db_parts.hostname != "127.0.0.1"
    or db_parts.port != 54329
    or db_parts.path != "/vasa"
    or db_parts.query
    or redis_parts.scheme != "redis"
    or redis_parts.hostname != "127.0.0.1"
    or redis_parts.port != 6389
    or redis_parts.path != "/0"
    or redis_parts.query
):
    raise RuntimeError("dedicated_local_dependencies_required")
settings = Settings(
    _env_file=None,
    environment="test",
    saas_enabled=True,
    public_origin="http://127.0.0.1:18888",
    smtp_host="fixture.invalid",
    smtp_sender="fixture@example.invalid",
    database_url=database_url,
    redis_url=redis_url,
)
app = create_app(settings)
original = app.router.lifespan_context
key = os.environ["VASA_ACCEPTANCE_FIXTURE_KEY"]
run = os.environ["VASA_ACCEPTANCE_RUN"]
if len(key) < 32 or not re.fullmatch(r"[a-z0-9-]{8,60}", run):
    raise RuntimeError("private_fixture_configuration_required")
messages = []
session_keys = set()


class Mailbox:
    def configured(self):
        return True

    async def send(self, recipient, subject, body):
        if not recipient.startswith(run + "-") or not recipient.endswith("@example.invalid"):
            raise RuntimeError("fixture_recipient_required")
        messages.append((recipient, body))


@asynccontextmanager
async def lifespan(application):
    async with original(application):
        application.state.mailer = Mailbox()
        yield
        async with application.state.database.session() as session:
            rows = (
                await session.execute(
                    select(User.id, User.tenant_id).where(
                        User.email.like(run + "-%@example.invalid")
                    )
                )
            ).all()
            ids = [r.id for r in rows]
            tenants = [r.tenant_id for r in rows]
            await session.execute(delete(AuditEvent).where(AuditEvent.actor_id.in_(ids)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenants)))
            await session.commit()
        if session_keys:
            await application.state.redis.delete(*session_keys)
        await application.state.redis.delete("vasa:auth:login:" + sha256(b"127.0.0.1").hexdigest())


app.router.lifespan_context = lifespan


@app.middleware("http")
async def sessions(request, call_next):
    # Uvicorn must also bind loopback. Reject accidental public interfaces even
    # if an operator launches this fixture with the wrong CLI host argument.
    if request.scope.get("server", ("", 0))[0] not in ("127.0.0.1", "localhost"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "loopback_fixture_required"}, status_code=403)
    token = request.cookies.get("vasa_session")
    if token:
        session_keys.add("vasa:auth:session:" + sha256(token.encode()).hexdigest())
    response = await call_next(request)
    cookie = response.headers.get("set-cookie", "")
    match = re.search(r"vasa_session=([A-Za-z0-9_-]{43})", cookie)
    if match:
        session_keys.add("vasa:auth:session:" + sha256(match[1].encode()).hexdigest())
    return response


@app.get("/_acceptance/mailbox")
async def mailbox(request: Request, email: str, page: str):
    if not secrets.compare_digest(request.headers.get("x-acceptance-key", ""), key):
        raise HTTPException(403)
    await app.state.redis.delete("vasa:auth:login:" + sha256(b"127.0.0.1").hexdigest())
    for recipient, body in reversed(messages):
        if recipient == email and "/" + page + "#token=" in body:
            return {"link": body.split()[-1]}
    raise HTTPException(404)


@app.post("/_acceptance/admin")
async def admin(request: Request):
    if not secrets.compare_digest(request.headers.get("x-acceptance-key", ""), key):
        raise HTTPException(403)
    payload = await request.json()
    if not payload["email"].startswith(run + "-"):
        raise HTTPException(403)
    async with app.state.database.session() as session:
        user = await session.scalar(select(User).where(User.email == payload["email"]))
        if user is None:
            raise HTTPException(404)
        session.add(PlatformRole(user_id=user.id))
        session.add(
            AuditEvent(
                actor_id=user.id,
                tenant_id=user.tenant_id,
                action="platform.admin_bootstrap",
                target=str(user.id),
            )
        )
        await session.commit()
    return {"status": "ok"}

"""Private fixture input, safety boundaries and targeted cleanup regressions."""

import io
import json
import secrets
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from scripts import live_saas_fixture as fixture
from vasa.config import Settings
from vasa.control.models import User
from vasa.saas.models import UserProfile
from vasa.storage.database import Database
from vasa.storage.models import Tenant


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"action": "prepare", "run": "f" * 32, "password": "secret"},
        {"action": "cleanup", "run": "../bad"},
        {"action": "cleanup", "run": "f" * 32, "extra": "secret"},
        {"action": "cleanup", "run": "f" * 32, "sessions": ["not-a-session"]},
        {"action": "delete", "run": "f" * 32},
    ],
)
def test_invalid_private_input_refused(value):
    with pytest.raises(ValueError, match="invalid_input"):
        fixture.validate(value)


def test_valid_cleanup_input_and_bounded_sessions():
    assert fixture.validate({"action": "cleanup", "run": "f" * 32, "sessions": ["x" * 43]})
    with pytest.raises(ValueError):
        fixture.validate({"action": "cleanup", "run": "f" * 32, "sessions": ["x" * 43] * 11})


@pytest.mark.parametrize(
    "enabled,origin",
    [
        (False, "https://vasa.litatech.xyz"),
        (True, "https://evil.invalid"),
        (True, "http://vasa.litatech.xyz"),
    ],
)
async def test_staging_gate_before_database(monkeypatch, enabled, origin):
    def database_forbidden(*args, **kwargs):
        raise AssertionError("database_must_not_open")

    monkeypatch.setattr(fixture, "Database", database_forbidden)
    with pytest.raises(ValueError, match="approved_staging_required"):
        await fixture.execute(
            {"action": "cleanup", "run": "f" * 32},
            Settings(_env_file=None).model_copy(
                update={"saas_enabled": enabled, "public_origin": origin}
            ),
        )


def test_exception_body_never_printed(monkeypatch, capsys):
    monkeypatch.setattr(
        fixture.sys, "stdin", io.StringIO(json.dumps({"action": "cleanup", "run": "f" * 32}))
    )

    async def fail(data):
        raise RuntimeError("Authorization: Bearer private-key response-body")

    monkeypatch.setattr(fixture, "execute", fail)
    with pytest.raises(SystemExit):
        fixture.main()
    output = capsys.readouterr()
    assert output.out == "LIVE_SAAS_FIXTURE_FAILED\n"
    assert output.err == ""


@pytest.mark.integration
async def test_disposable_cleanup_ownership_and_exact_sessions():
    settings = Settings(
        _env_file=None,
        environment="test",
        saas_enabled=True,
        public_origin="https://vasa.litatech.xyz",
        database_url="postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa",
        redis_url="redis://127.0.0.1:6389/0",
    )
    run = secrets.token_hex(16)
    tenant_id = uuid5(NAMESPACE_URL, f"vasa-acceptance:{run}:tenant:0")
    user_id = uuid5(NAMESPACE_URL, f"vasa-acceptance:{run}:user:0")
    data = {"action": "prepare", "run": run, "password": secrets.token_urlsafe(32)}
    db = Database(settings.database_url.get_secret_value())
    cache = Redis.from_url(settings.redis_url.get_secret_value())
    token = secrets.token_urlsafe(32)
    session_key = "vasa:auth:session:" + sha256(token.encode()).hexdigest()
    foreign_key = "vasa:acceptance:test:" + secrets.token_hex(16)
    try:
        await fixture.execute(data, settings)
        with pytest.raises(ValueError, match="fixture_already_exists"):
            await fixture.execute(data, settings)
        async with db.session() as session:
            profile = await session.get(UserProfile, user_id)
            assert profile.legacy_access and profile.email_verified_at is None
            tenant = await session.get(Tenant, tenant_id)
            tenant.name = "User changed this workspace"
            await session.commit()
        with pytest.raises(ValueError, match="fixture_ownership_mismatch"):
            await fixture.execute({"action": "cleanup", "run": run}, settings)
        async with db.session() as session:
            assert await session.get(User, user_id) is not None
            tenant = await session.get(Tenant, tenant_id)
            tenant.name = f"Disposable acceptance {run} 0"
            await session.commit()
        await cache.set(session_key, json.dumps({"user_id": str(user_id)}), ex=60)
        await cache.set(foreign_key, "unrelated", ex=60)
        await fixture.execute({"action": "cleanup", "run": run, "sessions": [token]}, settings)
        assert await cache.get(session_key) is None
        assert await cache.get(foreign_key) == b"unrelated"
        async with db.session() as session:
            assert await session.scalar(select(User.id).where(User.id == user_id)) is None
    finally:
        await fixture.execute({"action": "cleanup", "run": run}, settings)
        await cache.delete(session_key, foreign_key)
        await cache.aclose()
        await db.aclose()


@pytest.mark.integration
async def test_cleanup_refuses_foreign_session_without_deleting_it():
    settings = Settings(
        _env_file=None,
        environment="test",
        saas_enabled=True,
        public_origin="https://vasa.litatech.xyz",
        database_url="postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa",
        redis_url="redis://127.0.0.1:6389/0",
    )
    run = secrets.token_hex(16)
    token = secrets.token_urlsafe(32)
    key = "vasa:auth:session:" + sha256(token.encode()).hexdigest()
    cache = Redis.from_url(settings.redis_url.get_secret_value())
    payload = json.dumps({"user_id": "unrelated-user"})
    try:
        await cache.set(key, payload, ex=60)
        with pytest.raises(ValueError, match="session_ownership_mismatch"):
            await fixture.execute({"action": "cleanup", "run": run, "sessions": [token]}, settings)
        assert await cache.get(key) == payload.encode()
    finally:
        await cache.delete(key)
        await cache.aclose()

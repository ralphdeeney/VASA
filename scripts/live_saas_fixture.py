"""Disposable audited live acceptance identities; private JSON stdin, fixed output."""

import asyncio
import json
import re
import sys
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from redis.asyncio import Redis
from sqlalchemy import String, cast, delete, select
from sqlalchemy.exc import DBAPIError

from vasa.config import Settings
from vasa.control.auth import hash_password
from vasa.control.models import User, WhatsAppInstance
from vasa.saas.models import AuditEvent, Membership, OrganizationProfile, PlatformRole, UserProfile
from vasa.storage.database import Database
from vasa.storage.models import Tenant

_STAGE = "input"


def stage(value: str) -> None:
    global _STAGE
    _STAGE = value


def validate(data: object) -> dict[str, object]:
    if not isinstance(data, dict) or set(data) - {"action", "run", "password", "sessions"}:
        raise ValueError("invalid_input")
    if data.get("action") not in {"prepare", "cleanup", "cleanup_pending"}:
        raise ValueError("invalid_input")
    if data["action"] == "cleanup_pending":
        if set(data) != {"action"}:
            raise ValueError("invalid_input")
        return data
    if not isinstance(data.get("run"), str) or not re.fullmatch(r"[a-f0-9]{32}", data["run"]):
        raise ValueError("invalid_input")
    if data["action"] == "prepare" and (
        not isinstance(data.get("password"), str) or not 32 <= len(data["password"]) <= 128
    ):
        raise ValueError("invalid_input")
    tokens = data.get("sessions", [])
    if (
        not isinstance(tokens, list)
        or len(tokens) > 10
        or any(
            not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
            for token in tokens
        )
    ):
        raise ValueError("invalid_input")
    return data


async def execute(data: dict[str, object], settings: Settings | None = None) -> None:
    stage("settings")
    configuration = settings or Settings()
    if not configuration.saas_enabled or configuration.public_origin != "https://vasa.litatech.xyz":
        raise ValueError("approved_staging_required")
    if data["action"] == "cleanup_pending":
        stage("discover_pending")
        pending_db = Database(configuration.database_url.get_secret_value())
        try:
            async with pending_db.session() as session:
                emails = list(
                    (
                        await session.scalars(
                            select(User.email)
                            .join(AuditEvent, AuditEvent.target == cast(User.id, String))
                            .where(
                                AuditEvent.action == "identity.server_provision",
                                AuditEvent.safe_metadata["source"].as_string()
                                == "disposable_acceptance",
                                User.email.like("acceptance-%@example.invalid"),
                            )
                            .distinct()
                            .limit(201)
                        )
                    ).all()
                )
                if len(emails) > 200:
                    raise ValueError("pending_limit")
        finally:
            await pending_db.aclose()
        runs = set()
        for email in emails:
            match = re.fullmatch(r"acceptance-([a-f0-9]{32})-[01]@example\.invalid", email)
            if match:
                runs.add(match[1])
        for pending_run in sorted(runs):
            await execute({"action": "cleanup", "run": pending_run}, configuration)
        return
    run = str(data["run"])
    tenant_ids = [uuid5(NAMESPACE_URL, f"vasa-acceptance:{run}:tenant:{i}") for i in range(2)]
    user_ids = [uuid5(NAMESPACE_URL, f"vasa-acceptance:{run}:user:{i}") for i in range(2)]
    emails = [f"acceptance-{run}-{i}@example.invalid" for i in range(2)]
    database = Database(configuration.database_url.get_secret_value())
    try:
        stage("database_open")
        async with database.session() as session, session.begin():
            existing = list(
                (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
            )
            if data["action"] == "prepare":
                stage("prepare_database")
                if existing or await session.scalar(
                    select(Tenant.id).where(Tenant.id.in_(tenant_ids))
                ):
                    raise ValueError("fixture_already_exists")
                password_hash = await asyncio.to_thread(hash_password, str(data["password"]))
                for i in range(2):
                    session.add(Tenant(id=tenant_ids[i], name=f"Disposable acceptance {run} {i}"))
                await session.flush()
                for i in range(2):
                    session.add(
                        User(
                            id=user_ids[i],
                            tenant_id=tenant_ids[i],
                            email=emails[i],
                            password_hash=password_hash,
                        )
                    )
                await session.flush()
                for i in range(2):
                    session.add_all(
                        [
                            UserProfile(
                                user_id=user_ids[i],
                                name="Disposable acceptance",
                                status="active",
                                legacy_access=True,
                            ),
                            OrganizationProfile(
                                tenant_id=tenant_ids[i],
                                slug=f"acceptance-{run}-{i}",
                                status="active",
                            ),
                            Membership(
                                user_id=user_ids[i],
                                tenant_id=tenant_ids[i],
                                role="owner",
                                status="active",
                            ),
                            AuditEvent(
                                actor_id=None,
                                tenant_id=None,
                                action="identity.server_provision",
                                target=str(user_ids[i]),
                                safe_metadata={"source": "disposable_acceptance"},
                            ),
                        ]
                    )
                session.add(PlatformRole(user_id=user_ids[0]))
                session.add(
                    AuditEvent(
                        actor_id=None,
                        tenant_id=None,
                        action="platform.bootstrap_grant",
                        target=str(user_ids[0]),
                        safe_metadata={"source": "disposable_acceptance"},
                    )
                )
            else:
                stage("cleanup_ownership")
                unrelated_user = await session.scalar(
                    select(User.id).where(User.tenant_id.in_(tenant_ids), User.id.not_in(user_ids))
                )
                paired_instance = await session.scalar(
                    select(WhatsAppInstance.id).where(WhatsAppInstance.tenant_id.in_(tenant_ids))
                )
                if unrelated_user or paired_instance:
                    raise ValueError("fixture_ownership_mismatch")
                if len(existing) not in {0, 2}:
                    raise ValueError("fixture_ownership_mismatch")
                if not existing and await session.scalar(
                    select(Tenant.id).where(Tenant.id.in_(tenant_ids))
                ):
                    raise ValueError("fixture_ownership_mismatch")
                for user in existing:
                    i = user_ids.index(user.id)
                    tenant = await session.get(Tenant, tenant_ids[i])
                    profile = await session.get(UserProfile, user.id)
                    provision = await session.scalar(
                        select(AuditEvent.id).where(
                            AuditEvent.target == str(user.id),
                            AuditEvent.action == "identity.server_provision",
                            AuditEvent.safe_metadata["source"].as_string()
                            == "disposable_acceptance",
                        )
                    )
                    if (
                        provision is None
                        or user.email != emails[i]
                        or user.tenant_id != tenant_ids[i]
                        or tenant is None
                        or tenant.name != f"Disposable acceptance {run} {i}"
                        or profile is None
                        or not profile.legacy_access
                        or profile.email_verified_at is not None
                    ):
                        raise ValueError("fixture_ownership_mismatch")
                # Retain the server-provision/grant audit trail, and record removal.
                # Audit target IDs reveal no credentials or customer content.
                if existing:
                    session.add(
                        AuditEvent(
                            actor_id=None,
                            tenant_id=None,
                            action="identity.acceptance_cleanup",
                            safe_metadata={"source": "disposable_acceptance"},
                        )
                    )
                stage("cleanup_database")
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
            stage("database_commit")
        if data["action"] == "cleanup":
            stage("cleanup_sessions")
            cache = Redis.from_url(configuration.redis_url.get_secret_value())
            try:
                # Delete only explicitly supplied browser session keys belonging to
                # the disposable identities; never scan or flush shared Redis.
                for token in data.get("sessions", []):
                    key = "vasa:auth:session:" + sha256(token.encode()).hexdigest()
                    raw = await cache.get(key)
                    if raw:
                        payload = json.loads(raw)
                        if payload.get("user_id") not in {str(value) for value in user_ids}:
                            raise ValueError("session_ownership_mismatch")
                        await cache.delete(key)
            finally:
                await cache.aclose()
    finally:
        await database.aclose()


def main() -> None:
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError("input_limit")
        data = validate(json.loads(raw))
        asyncio.run(execute(data))
    except Exception as error:
        print("LIVE_SAAS_FIXTURE_FAILED")
        print("LIVE_SAAS_FIXTURE_STAGE=" + _STAGE)
        code = "internal_error"
        if isinstance(error, (ValueError, json.JSONDecodeError)):
            code = "invalid_configuration"
        if isinstance(error, DBAPIError):
            state = getattr(error.orig, "sqlstate", None)
            approved_states = {"23503", "23505", "23514", "40001", "40P01", "57014", "08006"}
            if state in approved_states:
                print("LIVE_SAAS_FIXTURE_SQLSTATE=" + state)
            code = "database_error"
        print("LIVE_SAAS_FIXTURE_ERROR=" + code)
        raise SystemExit(1) from None
    print("LIVE_SAAS_FIXTURE_" + str(data["action"]).upper() + "_OK")


if __name__ == "__main__":
    main()

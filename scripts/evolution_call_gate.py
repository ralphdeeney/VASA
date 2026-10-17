"""Read-only, fail-closed screen for VASA-managed calls before maintenance.

This is one observation, not an admission barrier or proof about independent
Evolution API clients. The deployment controller must quiesce admission and recheck.
"""

import asyncio
import json
import re
from collections.abc import Sequence
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import text

from vasa.config import Settings
from vasa.contracts.models import CallState
from vasa.storage.cache import MAX_SESSION_BYTES, CallRegistry
from vasa.storage.database import Database

MAX_KEYS = 10_000
TIMEOUT_SECONDS = 15
KEY_PATTERN = re.compile(rb"vasa:tenant:([0-9a-f-]{36}):call:([0-9a-f-]{36})")


def unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid state")
        result[key] = value
    return result


def reject_constant(value: str) -> object:
    raise ValueError("invalid state")


def active_state(key: bytes, payload: bytes) -> bool:
    match = KEY_PATTERN.fullmatch(key)
    if match is None or not payload or len(payload) > MAX_SESSION_BYTES:
        raise ValueError("invalid state")
    # Reject duplicate JSON fields and non-JSON numeric constants before using the
    # same namespace, identifier, metadata and enum validation as the runtime.
    json.loads(payload, object_pairs_hook=unique_object, parse_constant=reject_constant)
    state = CallRegistry._decode(payload, UUID(match[1].decode()), UUID(match[2].decode()))
    return state.state not in {CallState.ENDED, CallState.ERROR}


async def inspect_calls(database: Database, cache: Redis) -> tuple[int, int]:
    async with database.session() as session:
        count = await session.scalar(text("SELECT count(*) FROM calls WHERE ended_at IS NULL"))
    if type(count) is not int or not 0 <= count <= 1_000_000_000:
        raise ValueError("invalid count")
    cursor = 0
    seen: set[bytes] = set()
    active = 0
    for _ in range(MAX_KEYS):
        cursor, keys = await cache.scan(cursor=cursor, match="vasa:tenant:*:call:*", count=100)
        if type(cursor) is not int or cursor < 0 or not isinstance(keys, list):
            raise ValueError("invalid scan")
        for key in keys:
            if not isinstance(key, bytes):
                raise ValueError("invalid key")
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > MAX_KEYS:
                raise ValueError("scan limit")
            payload = await cache.getrange(key, 0, MAX_SESSION_BYTES)
            if not isinstance(payload, bytes):
                raise ValueError("invalid state")
            active += int(active_state(key, payload))
        if cursor == 0:
            return count, active
    raise ValueError("scan limit")


async def run() -> int:
    database: Database | None = None
    cache: Redis | None = None
    result: tuple[int, int] | None = None
    try:
        settings = Settings()
        async with asyncio.timeout(TIMEOUT_SECONDS):
            database = Database(settings.database_url.get_secret_value(), timeout_seconds=3)
            cache = Redis.from_url(
                settings.redis_url.get_secret_value(),
                socket_timeout=3,
                socket_connect_timeout=3,
                decode_responses=False,
                max_connections=1,
            )
            result = await inspect_calls(database, cache)
    except Exception:
        # Connection exhaustion, malformed state and all unknowns forbid rollout.
        result = None
    finally:
        try:
            async with asyncio.timeout(5):
                if cache is not None:
                    await cache.aclose()
                if database is not None:
                    await database.aclose()
        except Exception:
            result = None
    if result is None:
        print("EVOLUTION_CALL_GATE_FAILED=inspection_failed", flush=True)
        return 1
    durable, redis_active = result
    print(f"EVOLUTION_CALL_GATE_DB_ACTIVE={durable}", flush=True)
    print(f"EVOLUTION_CALL_GATE_REDIS_ACTIVE={redis_active}", flush=True)
    if durable or redis_active:
        print("EVOLUTION_CALL_GATE_FAILED=active_calls", flush=True)
        return 1
    print("EVOLUTION_CALL_GATE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

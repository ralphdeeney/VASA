import json
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

from evals.tenant_isolation.fixtures import db_session, dependency_settings, redis_client
from scripts import evolution_call_gate as gate
from vasa.contracts.models import CallSession, CallState
from vasa.storage.cache import CallRegistry

__all__ = ["db_session", "dependency_settings", "redis_client"]


def payload(state: str = "CONNECTED") -> tuple[bytes, bytes]:
    tenant, call = uuid4(), uuid4()
    key = f"vasa:tenant:{tenant}:call:{call}".encode()
    return key, json.dumps(
        {
            "id": str(call),
            "tenant_id": str(tenant),
            "instance_id": "private-instance",
            "external_call_id": "private-call",
            "state": state,
            "metadata": {},
        }
    ).encode()


@pytest.mark.parametrize("state", list(CallState))
def test_actual_enum_classifies_terminal_states(state: CallState) -> None:
    assert gate.active_state(*payload(state)) == (state not in {CallState.ENDED, CallState.ERROR})


@pytest.mark.parametrize("invalid", [b"", b"{}", b"secret-body", b"x" * 65537])
def test_malformed_or_oversized_state_fails_closed(invalid: bytes) -> None:
    with pytest.raises((ValueError, UnicodeError)):
        gate.active_state(payload()[0], invalid)


def test_duplicate_and_invalid_state_rejected() -> None:
    key, data = payload()
    with pytest.raises(ValueError):
        gate.active_state(key, data[:-1] + b',"state":"ENDED"}')
    with pytest.raises(ValueError):
        gate.active_state(*payload("unknown"))
    with pytest.raises(ValueError):
        gate.active_state(b"vasa:tenant:wrong:call:wrong", data)


class FakeDatabase:
    def __init__(self, count: object = 0) -> None:
        self.value = count
        self.aclose = AsyncMock()

    @asynccontextmanager
    async def session(self) -> Any:
        session = AsyncMock()
        session.scalar.return_value = self.value
        yield session


async def test_scan_deduplicates_and_uses_bounded_reads() -> None:
    key, data = payload()
    cache = AsyncMock()
    cache.scan.side_effect = [(10, [key]), (0, [key])]
    cache.getrange.return_value = data
    assert await gate.inspect_calls(FakeDatabase(2), cache) == (2, 1)  # type: ignore[arg-type]
    cache.getrange.assert_awaited_once_with(key, 0, 65536)


async def test_scan_limit_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = AsyncMock()
    cache.scan.return_value = (1, [])
    monkeypatch.setattr(gate, "MAX_KEYS", 2)
    with pytest.raises(ValueError, match="scan limit"):
        await gate.inspect_calls(FakeDatabase(), cache)  # type: ignore[arg-type]
    assert cache.scan.await_count == 2


@pytest.mark.parametrize("count", [-1, True, None, "0"])
async def test_invalid_db_count_fails_closed(count: object) -> None:
    with pytest.raises(ValueError):
        await gate.inspect_calls(FakeDatabase(count), AsyncMock())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "counts,expected",
    [((0, 0), "OK"), ((1, 0), "FAILED=active_calls"), ((0, 1), "FAILED=active_calls")],
)
async def test_safe_outputs_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    counts: tuple[int, int],
    expected: str,
) -> None:
    database, cache = FakeDatabase(), AsyncMock()
    monkeypatch.setattr(gate, "Database", lambda *args, **kwargs: database)
    monkeypatch.setattr(gate.Redis, "from_url", lambda *args, **kwargs: cache)
    monkeypatch.setattr(gate, "inspect_calls", AsyncMock(return_value=counts))
    assert await gate.run() == int(bool(any(counts)))
    assert capsys.readouterr().out == (
        f"EVOLUTION_CALL_GATE_DB_ACTIVE={counts[0]}\n"
        f"EVOLUTION_CALL_GATE_REDIS_ACTIVE={counts[1]}\nEVOLUTION_CALL_GATE_{expected}\n"
    )
    database.aclose.assert_awaited_once()
    cache.aclose.assert_awaited_once()


@pytest.mark.parametrize("failure", [TimeoutError, ValueError, RuntimeError])
async def test_exception_secrets_never_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: type[Exception],
) -> None:
    monkeypatch.setattr(
        gate,
        "Settings",
        lambda: (_ for _ in ()).throw(
            failure(
                "Authorization Bearer secret-key caller-id prompt body postgres://user:pass@host"
            )
        ),
    )
    assert await gate.run() == 1
    captured = capsys.readouterr()
    assert captured.out == "EVOLUTION_CALL_GATE_FAILED=inspection_failed\n"
    assert captured.err == ""


@pytest.mark.integration
async def test_real_postgres_and_redis_empty_and_nonterminal(
    db_session: Any, redis_client: Any
) -> None:
    # A transactional temporary table shadows only this connection's calls table;
    # existing test data and all persistent rows remain untouched.
    await db_session.execute(text("CREATE TEMP TABLE calls (ended_at timestamptz) ON COMMIT DROP"))

    class TransactionDatabase:
        @asynccontextmanager
        async def session(self) -> Any:
            yield db_session

    database = TransactionDatabase()
    initial = await gate.inspect_calls(database, redis_client)  # type: ignore[arg-type]
    assert initial[0] == 0
    call = CallSession(uuid4(), uuid4(), "disposable-gate", "disposable-call", CallState.ENDED)
    registry = CallRegistry(redis_client, ttl_seconds=30)
    key = registry._key(call.tenant_id, call.id)
    try:
        await registry.put(call)
        assert await gate.inspect_calls(database, redis_client) == initial  # type: ignore[arg-type]
        await registry.put(replace(call, state=CallState.CONNECTED))
        await db_session.execute(text("INSERT INTO calls (ended_at) VALUES (NULL)"))
        assert await gate.inspect_calls(database, redis_client) == (0 + 1, initial[1] + 1)  # type: ignore[arg-type]
    finally:
        await redis_client.delete(key)

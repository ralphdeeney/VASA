"""Real SQL isolation/atomicity and native worker admission lifecycle contracts."""

import asyncio
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from os import getenv
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from vasa.contracts.models import TenantContext
from vasa.knowledge.embedding import CPUEmbedder
from vasa.knowledge.models import KnowledgeChunk, KnowledgeSource
from vasa.knowledge.service import KnowledgeService
from vasa.storage.database import Database
from vasa.storage.models import Tenant


class FixtureEmbedder:
    identity = "fixture-vector-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 383 for _ in texts]


@pytest.fixture
async def service_fixture() -> AsyncIterator[tuple[KnowledgeService, TenantContext, TenantContext]]:
    database = Database(
        getenv(
            "VASA_TEST_DATABASE_URL",
            "postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa",
        )
    )
    owners = (TenantContext(uuid4(), uuid4()), TenantContext(uuid4(), uuid4()))
    service = KnowledgeService(database)
    service._embedder = cast(CPUEmbedder, FixtureEmbedder())
    try:
        async with database.session() as session, session.begin():
            try:
                await session.execute(text("SELECT 1"))
                await session.execute(select(KnowledgeSource.id).limit(1))
            except Exception as error:
                pytest.fail(
                    "Knowledge SQL checks require dedicated PostgreSQL with migrations applied "
                    f"({type(error).__name__}); run docker compose up -d and alembic upgrade head.",
                    pytrace=False,
                )
            session.add_all(
                Tenant(id=owner.tenant_id, name="knowledge-fixture") for owner in owners
            )
        yield service, *owners
    finally:
        await service.aclose()
        try:
            async with database.session() as session, session.begin():
                await session.execute(
                    delete(Tenant).where(Tenant.id.in_([owner.tenant_id for owner in owners]))
                )
        finally:
            await database.aclose()


@pytest.mark.integration
async def test_service_sql_tenant_scope_identity_and_atomic_deletion(
    service_fixture: tuple[KnowledgeService, TenantContext, TenantContext],
) -> None:
    service, own, foreign = service_fixture
    source = await service.add_text(own, "Hours", "We open on weekdays at nine.")
    foreign_source = await service.add_text(foreign, "Foreign", "Private foreign tenant content.")
    assert [item.id for item in await service.list_sources(own)] == [source.id]
    assert [item.id for item in await service.list_sources(foreign)] == [foreign_source.id]
    assert not await service.delete_source(foreign, source.id)
    matches = await service.search(own, "When do you open?")
    assert len(matches) == 1
    assert matches[0].tenant_id == str(own.tenant_id)
    assert matches[0].source_id == str(source.id)
    assert "Private foreign" not in matches[0].text
    async with service.database.session() as session, session.begin():
        session.add(
            KnowledgeChunk(
                tenant_id=own.tenant_id,
                source_id=source.id,
                ordinal=1,
                content="Obsolete embedding must never surface",
                embedding=[1.0] + [0.0] * 383,
                embedding_identity="obsolete-vector-v0",
            )
        )
    assert len(await service.search(own, "When do you open?")) == 1
    assert await service.delete_source(own, source.id)
    assert not await service.delete_source(own, source.id)
    assert await service.search(own, "When do you open?") == []
    async with service.database.session() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.source_id == source.id)
            )
            == 0
        )
    assert len(await service.search(foreign, "private")) == 1


@pytest.mark.integration
async def test_concurrent_source_quota_is_atomic_and_tenant_scoped(
    service_fixture: tuple[KnowledgeService, TenantContext, TenantContext],
) -> None:
    service, own, foreign = service_fixture
    async with service.database.session() as session, session.begin():
        session.add_all(
            KnowledgeSource(
                tenant_id=own.tenant_id,
                name=f"Existing {index}",
                kind="text",
                created_at=datetime.now(UTC),
                chunk_count=1,
            )
            for index in range(99)
        )
    results = await asyncio.gather(
        service.add_text(own, "Last A", "The final document A"),
        service.add_text(own, "Last B", "The final document B"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, KnowledgeSource) for result in results) == 1
    failures = [result for result in results if isinstance(result, ValueError)]
    assert len(failures) == 1 and "capacity" in str(failures[0])
    assert len(await service.list_sources(own)) == 100
    async with service.database.session() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.tenant_id == own.tenant_id)
            )
            == 1
        )
    assert (await service.add_text(foreign, "Independent quota", "Foreign quota unaffected")).id


@pytest.mark.integration
async def test_invalid_vectors_do_not_persist_partial_source(
    service_fixture: tuple[KnowledgeService, TenantContext, TenantContext],
) -> None:
    service, own, _ = service_fixture

    class InvalidEmbedder(FixtureEmbedder):
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[float("nan")] * 384 for _ in texts]

    service._embedder = cast(CPUEmbedder, InvalidEmbedder())
    with pytest.raises(ValueError, match="embedding"):
        await service.add_text(own, "Broken", "This source must not be persisted")
    assert await service.list_sources(own) == []


async def test_cancellation_retains_native_capacity_and_close_drains_workers() -> None:
    database = Database("postgresql+asyncpg://vasa:vasa_local_only@127.0.0.1:54329/vasa")
    service = KnowledgeService(database)
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    counts = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def work(index: int) -> str:
        with lock:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        if index < 2:
            started[index].set()
        assert release.wait(3), "worker release must be bounded"
        with lock:
            counts["active"] -= 1
        return "done"

    callers = [asyncio.create_task(service._offload(lambda i=i: work(i))) for i in range(4)]
    close: asyncio.Task[None] | None = None
    try:
        for event in started:
            assert await asyncio.to_thread(event.wait, 1)
        callers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await callers[0]
        with pytest.raises(RuntimeError, match="capacity"):
            await service._offload(lambda: "overflow")
        assert counts["active"] == 2
        close = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        assert not close.done()
        with pytest.raises(RuntimeError, match="capacity"):
            await service._offload(lambda: "closed")
        release.set()
        await asyncio.wait_for(close, 2)
        assert await asyncio.gather(*callers[1:]) == ["done"] * 3
        assert counts == {"active": 0, "peak": 2}
        assert not service._tasks
    finally:
        release.set()
        await service.aclose()
        await asyncio.gather(*callers, return_exceptions=True)
        await database.aclose()

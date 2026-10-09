import asyncio
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePath
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import delete, func, select

from vasa.contracts.models import TenantContext
from vasa.knowledge.embedding import CPUEmbedder
from vasa.knowledge.models import KnowledgeChunk, KnowledgeSource
from vasa.storage.database import Database
from vasa.tools.concrete import KnowledgeMatch

T = TypeVar("T")


class KnowledgeService:
    """Tenant-filtered vector retrieval; ingestion is bounded and atomic."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._embedder = CPUEmbedder()
        self._capacity = asyncio.Semaphore(2)
        self._tasks: set[asyncio.Task[object]] = set()
        self._closed = False

    async def _offload(self, work: Callable[[], T]) -> T:
        if self._closed or len(self._tasks) >= 4:
            raise RuntimeError("knowledge processing capacity unavailable")

        async def bounded() -> T:
            async with self._capacity:
                return await asyncio.to_thread(work)

        task = asyncio.create_task(bounded())
        self._tasks.add(cast(asyncio.Task[object], task))

        def finished(done: asyncio.Task[T]) -> None:
            self._tasks.discard(cast(asyncio.Task[object], done))
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        # Caller cancellation must not release native capacity while a thread runs.
        return await asyncio.shield(task)

    async def aclose(self) -> None:
        self._closed = True
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _embed(self, texts: list[str]) -> tuple[list[list[float]], str]:
        vectors = await self._offload(lambda: self._embedder.embed(texts))
        identity = self._embedder.identity
        if len(vectors) != len(texts) or any(
            len(vector) != 384 or any(not math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise ValueError("invalid embedding output")
        return vectors, identity

    async def add_text(self, context: TenantContext, name: str, text: str) -> KnowledgeSource:
        return await self._add(context, name, text, "text")

    async def add_document(
        self, context: TenantContext, name: str, content: bytes
    ) -> KnowledgeSource:
        from vasa.knowledge.processing import extract_document

        text = await self._offload(lambda: extract_document(name, content))
        return await self._add(context, name, text, PurePath(name).suffix.lower().lstrip("."))

    async def _add(
        self, context: TenantContext, name: str, text: str, kind: str
    ) -> KnowledgeSource:
        from vasa.knowledge.processing import process_text

        if not name.strip() or len(name) > 200 or any(c in name for c in ("/", "\\", "\x00")):
            raise ValueError("invalid source name")
        chunks = await self._offload(lambda: process_text(text))
        if not chunks or len(chunks) > 256:
            raise ValueError("source chunk capacity exceeded")
        vectors, identity = await self._embed(chunks)
        # Serialize tenant quota changes without holding a transaction during inference.
        from vasa.storage.models import Tenant

        async with self.database.session() as session, session.begin():
            tenant = await session.scalar(
                select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
            )
            if tenant is None:
                raise ValueError("unknown tenant")
            count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeSource)
                .where(KnowledgeSource.tenant_id == context.tenant_id)
            )
            total = await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.tenant_id == context.tenant_id)
            )
            if (count or 0) >= 100 or (total or 0) + len(chunks) > 2000:
                raise ValueError("tenant knowledge capacity exceeded")
            source = KnowledgeSource(
                tenant_id=context.tenant_id,
                name=name,
                kind=kind,
                created_at=datetime.now(UTC),
                chunk_count=len(chunks),
            )
            session.add(source)
            await session.flush()
            session.add_all(
                KnowledgeChunk(
                    tenant_id=context.tenant_id,
                    source_id=source.id,
                    ordinal=index,
                    content=chunk,
                    embedding=vector,
                    embedding_identity=identity,
                )
                for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            )
            await session.flush()
            return source

    async def list_sources(self, context: TenantContext) -> list[KnowledgeSource]:
        async with self.database.session() as session:
            return list(
                (
                    await session.scalars(
                        select(KnowledgeSource)
                        .where(KnowledgeSource.tenant_id == context.tenant_id)
                        .order_by(KnowledgeSource.created_at.desc())
                        .limit(100)
                    )
                ).all()
            )

    async def delete_source(self, context: TenantContext, source_id: UUID) -> bool:
        async with self.database.session() as session, session.begin():
            deleted = await session.scalar(
                delete(KnowledgeSource)
                .where(
                    KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == context.tenant_id
                )
                .returning(KnowledgeSource.id)
            )
            return deleted is not None

    async def search(
        self, context: TenantContext, query: str, top_k: int = 3
    ) -> list[KnowledgeMatch]:
        if not query.strip() or len(query) > 1000 or type(top_k) is not int or not 1 <= top_k <= 5:
            raise ValueError("invalid knowledge query")
        vectors, identity = await self._embed([query])
        distance = KnowledgeChunk.embedding.cosine_distance(vectors[0])
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(KnowledgeChunk, distance.label("distance"))
                    .where(
                        KnowledgeChunk.tenant_id == context.tenant_id,
                        KnowledgeChunk.embedding_identity == identity,
                    )
                    .order_by(distance, KnowledgeChunk.id)
                    .limit(top_k)
                )
            ).all()
        return [
            KnowledgeMatch(
                tenant_id=str(context.tenant_id),
                source_id=str(cast(KnowledgeChunk, chunk).source_id),
                chunk_id=str(cast(KnowledgeChunk, chunk).id),
                text=cast(KnowledgeChunk, chunk).content,
                score=max(-1.0, min(1.0, 1 - float(cast(float, value)))),
            )
            for chunk, value in rows
        ]

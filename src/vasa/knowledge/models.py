from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from vasa.storage.models import Base


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_sources_id_tenant"),
        CheckConstraint("chunk_count BETWEEN 1 AND 256", name="ck_sources_chunk_count"),
        CheckConstraint("kind IN ('text','txt','pdf','docx')", name="ck_sources_kind"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chunk_count: Mapped[int]


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "tenant_id"],
            ["knowledge_sources.id", "knowledge_sources.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("source_id", "ordinal", name="uq_chunks_ordinal"),
        CheckConstraint("length(content) BETWEEN 1 AND 4000", name="ck_chunks_content"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    ordinal: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    embedding_identity: Mapped[str] = mapped_column(String(200))

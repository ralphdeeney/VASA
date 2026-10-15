"""agent configuration and tenant vector knowledge

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("chunk_count BETWEEN 1 AND 256", name="ck_sources_chunk_count"),
        sa.CheckConstraint("kind IN ('text','txt','pdf','docx')", name="ck_sources_kind"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_sources_id_tenant"),
    )
    op.create_index(
        op.f("ix_knowledge_sources_tenant_id"), "knowledge_sources", ["tenant_id"], unique=False
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("embedding_identity", sa.String(length=200), nullable=False),
        sa.CheckConstraint("length(content) BETWEEN 1 AND 4000", name="ck_chunks_content"),
        sa.ForeignKeyConstraint(
            ["source_id", "tenant_id"],
            ["knowledge_sources.id", "knowledge_sources.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "ordinal", name="uq_chunks_ordinal"),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_source_id"), "knowledge_chunks", ["source_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_chunks_tenant_id"), "knowledge_chunks", ["tenant_id"], unique=False
    )
    op.add_column(
        "agents",
        sa.Column("business_name", sa.String(length=200), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column(
            "greeting",
            sa.String(length=1000),
            server_default="Hello, how can I help?",
            nullable=False,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "business_description", sa.String(length=2000), server_default="", nullable=False
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "instructions",
            sa.String(length=2000),
            server_default="Never invent business facts.",
            nullable=False,
        ),
    )
    op.add_column(
        "agents", sa.Column("language", sa.String(length=10), server_default="en", nullable=False)
    )
    op.add_column(
        "agents",
        sa.Column("voice", sa.String(length=40), server_default="ljspeech_en", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agents", "voice")
    op.drop_column("agents", "language")
    op.drop_column("agents", "instructions")
    op.drop_column("agents", "business_description")
    op.drop_column("agents", "greeting")
    op.drop_column("agents", "business_name")
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_source_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_sources_tenant_id"), table_name="knowledge_sources")
    op.drop_table("knowledge_sources")

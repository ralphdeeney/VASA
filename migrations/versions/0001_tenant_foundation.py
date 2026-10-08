"""Tenant foundation and pgvector availability.

Revision ID: 0001
Revises: none
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_agents_tenant_id", table_name="agents")
    op.drop_table("agents")
    op.drop_table("tenants")
    # Preserve the extension: other schemas may use it.

"""Authenticated users and tenant-owned WhatsApp instance mapping.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("users", "whatsapp_instances"):
        extra = (
            [
                sa.Column("email", sa.String(254), nullable=False, unique=True),
                sa.Column("password_hash", sa.Text(), nullable=False),
            ]
            if table == "users"
            else [
                sa.Column("external_id", sa.String(64), nullable=False, unique=True),
                sa.Column("name", sa.String(200), nullable=False),
            ]
        )
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            *extra,
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in ("whatsapp_instances", "users"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_table(table)

"""Align agent ownership with the tenant foundation model.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("agents_tenant_id_fkey", "agents", type_="foreignkey")
    op.create_foreign_key(
        "agents_tenant_id_fkey", "agents", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint("agents_tenant_id_fkey", "agents", type_="foreignkey")
    op.create_foreign_key("agents_tenant_id_fkey", "agents", "tenants", ["tenant_id"], ["id"])

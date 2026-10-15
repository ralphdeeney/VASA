"""Tenant-owned calls, transcript messages and non-content tool audit metadata.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_instances_id_tenant", "whatsapp_instances", ["id", "tenant_id"])
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("external_call_id", sa.String(200), nullable=False),
        sa.Column("caller", sa.String(128), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.String(4000), nullable=True),
        sa.Column("outcome", sa.String(200), nullable=True),
        sa.Column("message_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "tenant_id", name="uq_calls_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "instance_id", "external_call_id", name="uq_calls_external"
        ),
        sa.ForeignKeyConstraint(
            ["instance_id", "tenant_id"],
            ["whatsapp_instances.id", "whatsapp_instances.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_calls_times"),
        sa.CheckConstraint("message_sequence BETWEEN 0 AND 1000", name="ck_calls_sequence"),
        sa.CheckConstraint(
            "state IN ('RINGING','ANSWERING','CONNECTED','LISTENING','TRANSCRIBING',"
            "'THINKING','TOOL_EXECUTION','SPEAKING','ENDING','ENDED','ERROR')",
            name="ck_calls_state",
        ),
    )
    op.create_index("ix_calls_tenant_id", "calls", ["tenant_id"])
    op.create_table(
        "call_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id", "tenant_id"], ["calls.id", "calls.tenant_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("call_id", "sequence", name="uq_messages_sequence"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000", name="ck_messages_sequence"),
        sa.CheckConstraint("role IN ('customer','agent','tool','system')", name="ck_messages_role"),
        sa.CheckConstraint("length(content) BETWEEN 1 AND 16384", name="ck_messages_content"),
    )
    op.create_index("ix_call_messages_tenant_id", "call_messages", ["tenant_id"])
    op.create_index("ix_call_messages_call_id", "call_messages", ["call_id"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("error_code", sa.String(24), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_id", "tenant_id"], ["calls.id", "calls.tenant_id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('pending','succeeded','failed','cancelled','unknown')",
            name="ck_tool_calls_status",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_tool_calls_times"
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('busy','cancelled','denied','invalid_input',"
            "'invalid_output','timeout','unavailable')",
            name="ck_tool_calls_code",
        ),
    )
    op.create_index("ix_tool_calls_tenant_id", "tool_calls", ["tenant_id"])
    op.create_index("ix_tool_calls_call_id", "tool_calls", ["call_id"])


def downgrade() -> None:
    op.drop_table("tool_calls")
    op.drop_table("call_messages")
    op.drop_table("calls")
    op.drop_constraint("uq_instances_id_tenant", "whatsapp_instances", type_="unique")

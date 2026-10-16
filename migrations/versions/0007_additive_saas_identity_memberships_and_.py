"""additive SaaS identity memberships and audit

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','member')"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_organization_invitations_tenant_id"),
        "organization_invitations",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "organization_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active','pending','suspended')"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target", sa.String(length=100), server_default="", nullable=False),
        sa.Column("safe_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "identity_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('verify_email','password_reset')"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_identity_tokens_user_id"), "identity_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "organization_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="member", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner','admin','member')"),
        sa.CheckConstraint("status IN ('active','pending','revoked')"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
    )
    op.create_table(
        "platform_role_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=30), server_default="super_admin", nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role = 'super_admin'"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "registration_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('pending','approved','rejected')"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_registration_requests_user_id"), "registration_requests", ["user_id"], unique=False
    )
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_access", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active','pending','suspended')"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Preserve existing access without claiming email ownership or platform authority.
    op.execute(
        sa.text(
            "INSERT INTO user_profiles (user_id,name,status,legacy_access) "
            "SELECT id,'','active',true FROM users"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_profiles (tenant_id,slug,status) "
            "SELECT id,'workspace-' || id::text,'active' FROM tenants"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_memberships (user_id,tenant_id,role,status) "
            "SELECT id,tenant_id,'owner','active' FROM users"
        )
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_registration_requests_user_id"), table_name="registration_requests")
    op.drop_table("registration_requests")
    op.drop_table("platform_role_assignments")
    op.drop_table("organization_memberships")
    op.drop_index(op.f("ix_identity_tokens_user_id"), table_name="identity_tokens")
    op.drop_table("identity_tokens")
    op.drop_table("audit_events")
    op.drop_table("organization_profiles")
    op.drop_index(
        op.f("ix_organization_invitations_tenant_id"), table_name="organization_invitations"
    )
    op.drop_table("organization_invitations")

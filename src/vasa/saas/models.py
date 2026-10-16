"""Additive SaaS identity tables; existing users and tenants retain their IDs."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vasa.storage.models import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (CheckConstraint("status IN ('active','pending','suspended')"),)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationProfile(Base):
    __tablename__ = "organization_profiles"
    __table_args__ = (CheckConstraint("status IN ('active','pending','suspended')"),)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','member')"),
        CheckConstraint("status IN ('active','pending','revoked')"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member", server_default="member")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformRole(Base):
    __tablename__ = "platform_role_assignments"
    __table_args__ = (CheckConstraint("role = 'super_admin'"),)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(30), default="super_admin", server_default="super_admin"
    )
    granted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthToken(Base):
    __tablename__ = "identity_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('verify_email','password_reset')"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (CheckConstraint("role IN ('admin','member')"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100), default="", server_default="")
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected')"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

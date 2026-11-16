"""Tenants (restaurants), branches, RBAC and memberships.

Composite keys `(tenant_id, id)` + composite foreign keys make cross-tenant links impossible
(docs/02 conventions). RLS policies are created in migration 0002.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

TENANT_STATUSES = ("pending", "active", "suspended", "deactivated", "rejected")


class Tenant(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    status_reason: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    alcohol_licensed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    restaurant_type: Mapped[str] = mapped_column(String(60))
    cuisines: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list, server_default="{}")
    declared_branch_count: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"status IN {TENANT_STATUSES}", name="status"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        Index("ix_tenants_status", "status"),
    )


class Branch(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    address_line: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata", server_default="Asia/Kolkata")
    phone: Mapped[str | None] = mapped_column(String(16))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_branches_tenant_id_id"),
        Index("uq_branches_one_primary", "tenant_id", unique=True, postgresql_where="is_primary"),
    )


class Permission(Base):
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    module: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))


class Role(UUIDPkMixin, TimestampMixin, Base):
    """tenant_id NULL = system role shared by all tenants (Owner, Manager, ...)."""

    __tablename__ = "roles"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(200))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_id_key", postgresql_nulls_not_distinct=True),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        String(80), ForeignKey("permissions.key", ondelete="CASCADE"), primary_key=True
    )
    # Optional scope, e.g. "own_branches" for Manager (doc 04 "B")
    scope: Mapped[str] = mapped_column(String(20), default="all", server_default="all")


class Membership(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    all_branches: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        CheckConstraint("status IN ('active', 'invited', 'disabled')", name="status"),
        Index("ix_memberships_user_id", "user_id"),
    )


class UserBranch(Base):
    __tablename__ = "user_branches"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
    )

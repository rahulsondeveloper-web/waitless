"""Tables, sections, table sessions and assignments (PRD §11).

A *table session* is one party's visit. It carries the public code + PIN guests use to join it
(PRD §13, decision D8). An *assignment* links a session to a table; the partial unique index
`uq_table_assignments_open_per_table` makes double-seating a table impossible even under races.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

TABLE_STATUSES = ("available", "reserved", "occupied", "cleaning")
SESSION_STATUSES = ("open", "finished", "closed")
SESSION_SOURCES = ("walk_in", "queue", "reservation", "staff")


class TableSection(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "table_sections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_table_sections_tenant_id_id"),
        UniqueConstraint("branch_id", "name", name="uq_table_sections_branch_name"),
    )


class RestaurantTable(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_tables"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(12), default="available", server_default="available")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "section_id"],
            ["table_sections.tenant_id", "table_sections.id"],
            ondelete="SET NULL (section_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_restaurant_tables_tenant_id_id"),
        UniqueConstraint("branch_id", "label", name="uq_restaurant_tables_branch_label"),
        CheckConstraint("capacity BETWEEN 1 AND 50", name="capacity"),
        CheckConstraint(f"status IN {TABLE_STATUSES}", name="status"),
    )


class TableSession(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "table_sessions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    public_code: Mapped[str] = mapped_column(String(12))
    pin_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(12), default="walk_in", server_default="walk_in")
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    party_size: Mapped[int] = mapped_column(SmallInteger)
    guest_name: Mapped[str | None] = mapped_column(String(80))
    opened_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_table_sessions_tenant_id_id"),
        CheckConstraint("party_size BETWEEN 1 AND 100", name="party_size"),
        CheckConstraint(f"status IN {SESSION_STATUSES}", name="status"),
        CheckConstraint(f"source IN {SESSION_SOURCES}", name="source"),
        # A code is reusable once its session is closed.
        Index(
            "uq_table_sessions_open_code",
            "tenant_id",
            "public_code",
            unique=True,
            postgresql_where="status <> 'closed'",
        ),
    )


class TableAssignment(UUIDPkMixin, Base):
    __tablename__ = "table_assignments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_id"], ["restaurant_tables.tenant_id", "restaurant_tables.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"], ["table_sessions.tenant_id", "table_sessions.id"], ondelete="CASCADE"
        ),
        # PRD §11: never two open assignments for one table.
        Index("uq_table_assignments_open_per_table", "table_id", unique=True, postgresql_where="released_at IS NULL"),
        Index("ix_table_assignments_session", "table_session_id"),
    )

"""Floor Agent: the camera program on the restaurant's laptop, the table occupancy it reports, and the alerts
WaitLess sends to the waiter in charge of the table.

- **FloorAgent**: one paired laptop. The owner makes it a one-time pairing code; the agent swaps the code for a
  key (only a hash is kept here) and uses that key for everything after.
- **TableOccupancy**: one row per sitting, seen by the camera: guests sat at `seated_at`, left at `left_at`.
- **FloorAlert**: "guests at T2" / "T2 is empty", for one person (the waiter in charge) or, with no user, for the
  whole branch. Kept so a waiter who opens the app later still sees what is waiting for them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin

ALERT_KINDS = ("seated", "seated_unchecked", "left", "left_open")


class FloorAgent(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "floor_agents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(60))
    pairing_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # cleared once used
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_floor_agents_tenant_id_id"),
    )


class TableOccupancy(UUIDPkMixin, Base):
    __tablename__ = "table_occupancy"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("floor_agents.id", ondelete="SET NULL")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # the agent's id for the "seated" event
    guests: Mapped[int] = mapped_column(SmallInteger)
    seated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_id"], ["restaurant_tables.tenant_id", "restaurant_tables.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "event_id", name="uq_table_occupancy_tenant_id_event_id"),
        CheckConstraint("guests BETWEEN 1 AND 100", name="guests"),
        # One sitting at a time per table.
        Index("uq_table_occupancy_open_per_table", "table_id", unique=True, postgresql_where="left_at IS NULL"),
        Index("ix_table_occupancy_branch_seated", "tenant_id", "branch_id", "seated_at"),
    )


class FloorAlert(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "floor_alerts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_label: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )  # who is told; none = every waiter of the branch
    kind: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(160))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        CheckConstraint(f"kind IN {ALERT_KINDS}", name="kind"),
        Index("ix_floor_alerts_open", "tenant_id", "branch_id", "created_at", postgresql_where="acked_at IS NULL"),
        Index("ix_floor_alerts_user", "user_id"),
    )

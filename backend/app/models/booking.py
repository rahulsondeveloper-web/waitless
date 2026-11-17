"""Digital queue (PRD §10) and reservations (PRD §12) with booking payments.

Overlapping bookings are impossible at the database level: `reservation_tables` has a GiST exclusion
constraint on (table, time range) for active holds (btree_gist extension, migration 0001).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

QUEUE_STATUSES = ("waiting", "notified", "seated", "cancelled", "no_show", "skipped")
QUEUE_ACTIVE = ("waiting", "notified")
RESERVATION_STATUSES = ("pending_payment", "confirmed", "checked_in", "completed", "expired", "cancelled", "no_show")
RESERVATION_ACTIVE = ("pending_payment", "confirmed", "checked_in")
PAYMENT_STATUSES = ("created", "captured", "failed", "refunded", "partially_refunded")


class QueueEntry(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "queue_entries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    service_date: Mapped[date] = mapped_column(Date)  # branch-local day the token belongs to
    token: Mapped[str] = mapped_column(String(8))  # "A-017"
    sequence: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)  # ordering key; staff can move entries
    party_size: Mapped[int] = mapped_column(SmallInteger)
    guest_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(16))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(10), default="online", server_default="online")
    status: Mapped[str] = mapped_column(String(10), default="waiting", server_default="waiting")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_table_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("branch_id", "service_date", "sequence", name="uq_queue_entries_branch_day_seq"),
        CheckConstraint(f"status IN {QUEUE_STATUSES}", name="status"),
        CheckConstraint("source IN ('online', 'staff')", name="source"),
        CheckConstraint("party_size BETWEEN 1 AND 50", name="party_size"),
        # One live place in line per guest per branch.
        Index(
            "uq_queue_entries_one_active_per_customer",
            "branch_id",
            "customer_id",
            unique=True,
            postgresql_where="status IN ('waiting', 'notified') AND customer_id IS NOT NULL",
        ),
        Index("ix_queue_entries_branch_active", "branch_id", "status", "position"),
    )


class ReservationPolicy(TimestampMixin, Base):
    """Per-branch booking rules. Copied into each reservation (policy_snapshot) when it is made."""

    __tablename__ = "reservation_policies"

    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    accepts_reservations: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    accepts_queue: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    free_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    paid_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    booking_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    dining_minutes: Mapped[int] = mapped_column(SmallInteger, default=90, server_default="90")
    grace_minutes: Mapped[int] = mapped_column(SmallInteger, default=15, server_default="15")
    min_lead_minutes: Mapped[int] = mapped_column(SmallInteger, default=60, server_default="60")
    max_advance_days: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    min_party: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    max_party: Mapped[int] = mapped_column(SmallInteger, default=12, server_default="12")
    free_cancel_hours: Mapped[int] = mapped_column(SmallInteger, default=2, server_default="2")
    refund_on_no_show: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        CheckConstraint("booking_fee >= 0", name="fee_non_negative"),
        CheckConstraint("slot_minutes IN (15, 30, 60)", name="slot_minutes"),
        CheckConstraint("dining_minutes BETWEEN 30 AND 360", name="dining_minutes"),
        CheckConstraint("grace_minutes BETWEEN 0 AND 120", name="grace_minutes"),
        CheckConstraint("min_party >= 1 AND max_party >= min_party AND max_party <= 50", name="party_range"),
        CheckConstraint("NOT paid_enabled OR booking_fee > 0", name="paid_needs_fee"),
    )


class Reservation(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "reservations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(String(10))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    guest_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(16))
    party_size: Mapped[int] = mapped_column(SmallInteger)
    type: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # starts_at + grace
    payment_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booking_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(10), default="online", server_default="online")
    staff_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # PRD §12 arrival
    table_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("tenant_id", "id", name="uq_reservations_tenant_id_id"),
        UniqueConstraint("tenant_id", "code", name="uq_reservations_tenant_code"),
        CheckConstraint(f"status IN {RESERVATION_STATUSES}", name="status"),
        CheckConstraint("type IN ('free', 'paid')", name="type"),
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("party_size BETWEEN 1 AND 50", name="party_size"),
        CheckConstraint("booking_fee >= 0", name="fee_non_negative"),
        Index("ix_reservations_branch_start", "branch_id", "starts_at"),
        Index("ix_reservations_customer", "customer_id"),
        Index("ix_reservations_status_deadline", "status", "arrival_deadline"),
    )


class ReservationTable(UUIDPkMixin, Base):
    """A table held for a reservation over a time range. Active holds can never overlap on one table."""

    __tablename__ = "reservation_tables"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    slot: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["reservations.tenant_id", "reservations.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "table_id"], ["restaurant_tables.tenant_id", "restaurant_tables.id"], ondelete="CASCADE"
        ),
        ExcludeConstraint(
            ("table_id", "="),
            ("slot", "&&"),
            where="active",
            using="gist",
            name="ex_reservation_tables_no_overlap",
        ),
        Index("ix_reservation_tables_reservation", "reservation_id"),
    )


class ReservationPayment(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "reservation_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(20))
    provider_order_id: Mapped[str] = mapped_column(String(80), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(String(20), default="created", server_default="created")
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["reservations.tenant_id", "reservations.id"], ondelete="CASCADE"
        ),
        CheckConstraint(f"status IN {PAYMENT_STATUSES}", name="status"),
        CheckConstraint("amount > 0 AND refunded_amount >= 0 AND refunded_amount <= amount", name="amounts"),
        Index("ix_reservation_payments_reservation", "reservation_id"),
    )

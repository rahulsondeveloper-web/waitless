"""15-minute serving promise & automatic discounts (PRD §14).

- `discount_policies`: one per restaurant (defaults apply until the owner saves one).
- `order_sla`: one per order, created when its timer starts. The policy is *copied* into
  `policy_snapshot`, so later policy edits never change running or past orders (D15).
  `sla_started_at` and `policy_snapshot` are immutable (database trigger).
- `order_discounts`: the discount an order receives; one `sla_delay` row per order, updated at
  each boundary until served, then frozen. `manual`/`promo` come with billing (Phase 10).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

SLA_STATUSES = ("running", "served", "cancelled")
SLA_START_REASONS = ("accepted", "arrival_confirmed")
DISCOUNT_BASES = ("food_subtotal", "order_total")
DISCOUNT_KINDS = ("sla_delay", "manual", "promo")


class DiscountPolicy(TimestampMixin, Base):
    __tablename__ = "discount_policies"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    serving_minutes: Mapped[int] = mapped_column(SmallInteger, default=15, server_default="15")
    initial_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2"), server_default="2")
    interval_minutes: Mapped[int] = mapped_column(SmallInteger, default=5, server_default="5")
    increment_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2"), server_default="2")
    max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20"), server_default="20")
    eligible_order_types: Mapped[list[str]] = mapped_column(ARRAY(String(14)))
    base: Mapped[str] = mapped_column(String(14), default="food_subtotal", server_default="food_subtotal")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        CheckConstraint("serving_minutes BETWEEN 1 AND 180", name="serving_minutes"),
        CheckConstraint("interval_minutes BETWEEN 1 AND 60", name="interval_minutes"),
        CheckConstraint(
            "initial_pct BETWEEN 0 AND 100 AND increment_pct BETWEEN 0 AND 100 AND max_pct BETWEEN 0 AND 100",
            name="pcts",
        ),
        CheckConstraint(f"base IN {DISCOUNT_BASES}", name="base"),
    )


class OrderSla(Base):
    __tablename__ = "order_sla"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sla_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # server UTC, set once
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_reason: Mapped[str] = mapped_column(String(18))
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), default="running", server_default="running")
    current_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")
    next_boundary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # worker wakes here
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # served or cancelled
    final_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="CASCADE"),
        CheckConstraint(f"status IN {SLA_STATUSES}", name="status"),
        CheckConstraint(f"start_reason IN {SLA_START_REASONS}", name="start_reason"),
        CheckConstraint("deadline_at > sla_started_at", name="deadline"),
        CheckConstraint("(status = 'running') = (ended_at IS NULL)", name="ended"),
        Index("ix_order_sla_next_boundary", "next_boundary_at", postgresql_where="status = 'running'"),
    )


class OrderDiscount(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "order_discounts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(10))
    pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        CheckConstraint(f"kind IN {DISCOUNT_KINDS}", name="kind"),
        CheckConstraint("pct BETWEEN 0 AND 100 AND amount >= 0", name="amounts"),
        Index("uq_order_discounts_sla", "order_id", unique=True, postgresql_where="kind = 'sla_delay'"),
        Index("ix_order_discounts_order", "order_id"),
    )

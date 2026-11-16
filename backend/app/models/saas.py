"""SaaS plans and subscriptions. Completely separate from restaurant billing (PRD §9)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

LIVE_SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due")


class Plan(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    price_yearly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    trial_days: Mapped[int] = mapped_column(SmallInteger, default=14, server_default="14")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (CheckConstraint("price_monthly >= 0 AND price_yearly >= 0", name="price_non_negative"),)


class PlanFeature(Base):
    __tablename__ = "plan_features"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    limit_value: Mapped[int | None] = mapped_column(Integer)  # NULL = unlimited


class Subscription(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(20))
    billing_cycle: Mapped[str] = mapped_column(String(10), default="monthly", server_default="monthly")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('trialing', 'active', 'past_due', 'cancelled', 'expired')", name="status"),
        CheckConstraint("billing_cycle IN ('monthly', 'yearly')", name="billing_cycle"),
        Index(
            "uq_subscriptions_one_live_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where="status IN ('trialing', 'active', 'past_due')",
        ),
    )

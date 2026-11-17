"""WaitLess platform administration (PRD §16–17): SaaS invoices & payments (separate from restaurant bills, D18),
website content, platform settings, notification templates and support-desk notes."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

SAAS_INVOICE_STATUSES = ("due", "paid", "void")
SAAS_PAYMENT_METHODS = ("gateway", "bank", "upi", "card", "cash", "waived")


class SaasInvoice(UUIDPkMixin, TimestampMixin, Base):
    """What a restaurant owes WaitLess for its plan. Platform-level (Super Admin + the restaurant owner)."""

    __tablename__ = "saas_invoices"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(Integer, unique=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # WL-000012
    description: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"), server_default="18")
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(String(6), default="due", server_default="due")
    due_date: Mapped[date] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(10), default="renewal", server_default="renewal")  # renewal | manual
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"status IN {SAAS_INVOICE_STATUSES}", name="status"),
        CheckConstraint("kind IN ('renewal', 'manual')", name="kind"),
        CheckConstraint("amount >= 0 AND tax >= 0 AND total >= 0", name="amounts"),
        Index("ix_saas_invoices_tenant", "tenant_id", "created_at"),
    )


class SaasPayment(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "saas_payments"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saas_invoices.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), default="captured", server_default="captured")
    reference: Mapped[str] = mapped_column(String(80), default="", server_default="")
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_order_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"method IN {SAAS_PAYMENT_METHODS}", name="method"),
        CheckConstraint("status IN ('pending', 'captured', 'failed')", name="status"),
        CheckConstraint("amount >= 0", name="amount"),
        Index("ix_saas_payments_invoice", "invoice_id"),
    )


class PlatformContent(TimestampMixin, Base):
    """Editable WaitLess website sections (home hero, features, about, terms …), JSON per section."""

    __tablename__ = "platform_content"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class PlatformSetting(TimestampMixin, Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class NotificationTemplate(UUIDPkMixin, TimestampMixin, Base):
    """Wording of a notification per event and channel; `{placeholders}` are filled from the event."""

    __tablename__ = "notification_templates"

    event: Mapped[str] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(10), default="in_app", server_default="in_app")
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("event", "channel", name="uq_notification_templates_event_channel"),
        CheckConstraint("channel IN ('in_app', 'sms', 'whatsapp', 'email')", name="channel"),
    )


class SupportNote(UUIDPkMixin, CreatedAtMixin, Base):
    """Internal notes on a support ticket — never shown to the person who wrote in."""

    __tablename__ = "support_notes"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_support_notes_ticket", "ticket_id"),)

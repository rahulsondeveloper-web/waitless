"""Restaurant billing & POS (PRD §9) — completely separate from WaitLess SaaS billing (decision D18).

- A table visit (session) has one or more **bills** (split by items, or merged with another table's bill).
  Each order line is on exactly one bill (`UNIQUE (order_item_id)`), so nothing is ever charged twice.
- An open bill is recalculated from the orders; the first payment **locks** it (lines and amounts frozen).
- Fully paid → an **invoice** is issued: an immutable snapshot (insert-only, trigger). Refunds issue a
  credit note referencing the invoice; nothing is ever edited.
- All money is NUMERIC(12,2).
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
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

BILL_STATUSES = ("open", "paid", "void")
PAYMENT_METHODS = ("cash", "upi", "card", "gateway", "other")
PAYMENT_STATUSES = ("pending", "captured", "failed")
INVOICE_KINDS = ("invoice", "credit_note")
MONEY = Numeric(12, 2)


def _money(default: str = "0") -> Any:
    return mapped_column(MONEY, default=Decimal(default), server_default=default)


class Bill(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "bills"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sequence: Mapped[int] = mapped_column(SmallInteger)  # 1, 2 … within the visit ("Bill 2")
    status: Mapped[str] = mapped_column(String(6), default="open", server_default="open")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # a payment exists
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subtotal: Mapped[Decimal] = _money()  # food before any discount
    sla_discount: Mapped[Decimal] = _money()  # serving-time discount taken off the food (before tax)
    sla_discount_after_tax: Mapped[Decimal] = _money()  # for policies on the order total
    manual_discount: Mapped[Decimal] = _money()
    manual_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    manual_discount_reason: Mapped[str | None] = mapped_column(String(200))
    manual_discount_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    taxable: Mapped[Decimal] = _money()  # food after discounts
    service_charge_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")
    service_charge: Mapped[Decimal] = _money()
    tax_total: Mapped[Decimal] = _money()
    booking_credit: Mapped[Decimal] = _money()
    round_off: Mapped[Decimal] = _money()
    grand_total: Mapped[Decimal] = _money()
    paid_total: Mapped[Decimal] = _money()
    refunded_total: Mapped[Decimal] = _money()
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # tax by rate etc.
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"], ["table_sessions.tenant_id", "table_sessions.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_bills_tenant_id_id"),
        UniqueConstraint("table_session_id", "sequence", name="uq_bills_session_sequence"),
        CheckConstraint(f"status IN {BILL_STATUSES}", name="status"),
        CheckConstraint(
            "subtotal >= 0 AND sla_discount >= 0 AND sla_discount_after_tax >= 0 AND manual_discount >= 0"
            " AND taxable >= 0 AND service_charge >= 0 AND tax_total >= 0 AND booking_credit >= 0"
            " AND grand_total >= 0 AND paid_total >= 0 AND refunded_total >= 0 AND refunded_total <= paid_total",
            name="amounts",
        ),
        CheckConstraint("round_off BETWEEN -1 AND 1", name="round_off"),
        Index("ix_bills_session", "table_session_id"),
        Index("ix_bills_branch_status", "branch_id", "status"),
    )


class BillItem(UUIDPkMixin, Base):
    __tablename__ = "bill_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_number: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(SmallInteger)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    sla_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")
    sla_discount: Mapped[Decimal] = _money()
    manual_discount: Mapped[Decimal] = _money()
    taxable: Mapped[Decimal] = _money()
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "bill_id"], ["bills.tenant_id", "bills.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["order_item_id"], ["order_items.id"], ondelete="CASCADE"),
        UniqueConstraint("order_item_id", name="uq_bill_items_order_item"),  # never billed twice
        Index("ix_bill_items_bill", "bill_id"),
    )


class BillPayment(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "bill_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    method: Mapped[str] = mapped_column(String(8))
    method_label: Mapped[str] = mapped_column(String(40), default="", server_default="")  # "Sodexo", "Paytm" …
    amount: Mapped[Decimal] = mapped_column(MONEY)
    tendered: Mapped[Decimal | None] = mapped_column(MONEY)  # cash handed over
    change_due: Mapped[Decimal] = _money()
    status: Mapped[str] = mapped_column(String(8), default="captured", server_default="captured")
    reference: Mapped[str] = mapped_column(String(80), default="", server_default="")
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_order_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    refunded_amount: Mapped[Decimal] = _money()
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "bill_id"], ["bills.tenant_id", "bills.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_bill_payments_tenant_id_id"),
        Index(
            "uq_bill_payments_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="method"),
        CheckConstraint(f"status IN {PAYMENT_STATUSES}", name="status"),
        CheckConstraint(
            "amount > 0 AND change_due >= 0 AND refunded_amount >= 0 AND refunded_amount <= amount", name="amounts"
        ),
        Index("ix_bill_payments_bill", "bill_id"),
        Index("ix_bill_payments_branch_created", "branch_id", "created_at"),
    )


class BillRefund(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "bill_refunds"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(String(200))
    provider_refund_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "bill_id"], ["bills.tenant_id", "bills.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"], ["bill_payments.tenant_id", "bill_payments.id"], ondelete="CASCADE"
        ),
        Index(
            "uq_bill_refunds_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("length(trim(reason)) > 0", name="reason"),
        Index("ix_bill_refunds_payment", "payment_id"),
    )


class Invoice(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable (insert-only). `snapshot` holds everything printed on it."""

    __tablename__ = "invoices"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(12), default="invoice", server_default="invoice")
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(24))
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    total: Mapped[Decimal] = mapped_column(MONEY)  # negative for credit notes
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "bill_id"], ["bills.tenant_id", "bills.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "number", name="uq_invoices_number"),
        UniqueConstraint("tenant_id", "kind", "sequence", name="uq_invoices_sequence"),
        Index("uq_invoices_one_per_bill", "bill_id", unique=True, postgresql_where="kind = 'invoice'"),
        CheckConstraint(f"kind IN {INVOICE_KINDS}", name="kind"),
        Index("ix_invoices_branch_issued", "branch_id", "issued_at"),
    )

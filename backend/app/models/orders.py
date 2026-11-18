"""Food ordering & kitchen (PRD §13).

- Prices, names and add-ons are *snapshotted* on each line, so later menu edits never change an order.
- `UNIQUE (tenant_id, idempotency_key)` makes a retried submission return the original order.
- Status flow: placed → accepted → preparing → ready → served (cancelled from placed/accepted).
  "Ready" (kitchen) is not "Served" (waiter) — separate permissions.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

ORDER_STATUSES = ("placed", "accepted", "preparing", "ready", "served", "cancelled")
ORDER_ACTIVE = ("placed", "accepted", "preparing", "ready")
# walk_in: guest at a walk-in/queue table · booking: guest at a table seated from a reservation
# staff: placed by a waiter · paid_preorder: placed before arrival on a paid booking (PRD §12)
ORDER_TYPES = ("walk_in", "booking", "staff", "paid_preorder")
ORDER_SOURCES = ("guest", "staff")


class Order(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    placed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # staff user, if any
    service_date: Mapped[date] = mapped_column(Date)  # branch-local day (numbering restarts daily)
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(8))  # "017"
    order_type: Mapped[str] = mapped_column(String(14))
    source: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(10), default="placed", server_default="placed")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str] = mapped_column(String(300), default="", server_default="")
    # Who at the table ordered it ("Riya") — shown to the table, kitchen and staff, never on the invoice.
    ordered_by_name: Mapped[str | None] = mapped_column(String(60))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preparing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"],
            ["table_sessions.tenant_id", "table_sessions.id"],
            ondelete="SET NULL (table_session_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["reservations.tenant_id", "reservations.id"],
            ondelete="SET NULL (reservation_id)",
        ),
        ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("tenant_id", "id", name="uq_orders_tenant_id_id"),
        UniqueConstraint("branch_id", "service_date", "sequence", name="uq_orders_branch_day_sequence"),
        Index(
            "uq_orders_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        Index("ix_orders_branch_status", "branch_id", "status"),
        Index("ix_orders_session", "table_session_id"),
        Index("ix_orders_reservation", "reservation_id"),
        Index("ix_orders_customer", "customer_id"),
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        CheckConstraint(f"order_type IN {ORDER_TYPES}", name="order_type"),
        CheckConstraint(f"source IN {ORDER_SOURCES}", name="source"),
        CheckConstraint("table_session_id IS NOT NULL OR reservation_id IS NOT NULL", name="has_context"),
        CheckConstraint("subtotal >= 0 AND tax_total >= 0 AND total >= 0", name="amounts"),
    )


class OrderItem(UUIDPkMixin, Base):
    __tablename__ = "order_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    variant_name: Mapped[str | None] = mapped_column(String(40))
    addons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    food_class: Mapped[str] = mapped_column(String(10))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # variant/base + add-ons
    quantity: Mapped[int] = mapped_column(SmallInteger)
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # before tax
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    instructions: Mapped[str] = mapped_column(String(200), default="", server_default="")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="SET NULL (menu_item_id)",
        ),
        CheckConstraint("quantity BETWEEN 1 AND 50", name="quantity"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0 AND tax_amount >= 0", name="amounts"),
        Index("ix_order_items_order", "order_id"),
    )


class OrderStatusHistory(UUIDPkMixin, Base):
    __tablename__ = "order_status_history"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_status: Mapped[str | None] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="CASCADE"),
        Index("ix_order_status_history_order", "order_id"),
    )

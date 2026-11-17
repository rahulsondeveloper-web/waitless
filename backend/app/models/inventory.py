"""Inventory (PRD §8): items, stock per branch, the movement ledger, suppliers, purchases, transfers, recipes.

- The **movement ledger is the truth** (insert-only — a trigger blocks updates). `inventory_stock.on_hand`
  is a cache changed in the same transaction as each movement, so it never drifts silently.
- Every manual movement carries a reason and the user who made it (PRD §8.2 "never modify stock silently").
- One deduction per order line and ingredient: unique `(order_item_id, item_id)` for `consumption`,
  and one reversal for the same pair — so retrying Accept or Cancel can never double-count (D22).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

UNITS = ("kg", "g", "l", "ml", "pcs", "pkt", "box")
MOVEMENT_TYPES = (
    "opening",
    "purchase",
    "addition",
    "consumption",
    "reversal",
    "wastage",
    "damage",
    "adjustment",
    "transfer_out",
    "transfer_in",
    "return",
)
PURCHASE_STATUSES = ("draft", "ordered", "received", "cancelled")
PAYMENT_STATUSES = ("unpaid", "partial", "paid")
TRANSFER_STATUSES = ("in_transit", "received", "cancelled")
QTY = Numeric(14, 3)


class InventoryCategory(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "inventory_categories"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_categories_tenant_id_id"),
        Index("uq_inventory_categories_name", "tenant_id", text("lower(name)"), unique=True),
    )


class Supplier(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    contact_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(20), default="", server_default="")
    email: Mapped[str] = mapped_column(String(120), default="", server_default="")
    address: Mapped[str] = mapped_column(String(300), default="", server_default="")
    gstin: Mapped[str] = mapped_column(String(20), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_id_id"),
        Index("uq_suppliers_name", "tenant_id", text("lower(name)"), unique=True),
    )


class InventoryItem(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "inventory_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # preferred supplier
    name: Mapped[str] = mapped_column(String(120))
    sku: Mapped[str | None] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(4))
    min_stock: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"), server_default="0")
    reorder_level: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"), server_default="0")
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    tracks_expiry: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    storage_location: Mapped[str] = mapped_column(String(80), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["inventory_categories.tenant_id", "inventory_categories.id"],
            ondelete="SET NULL (category_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], ondelete="SET NULL (supplier_id)"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inventory_items_tenant_id_id"),
        Index("uq_inventory_items_name", "tenant_id", text("lower(name)"), unique=True),
        Index(
            "uq_inventory_items_sku", "tenant_id", text("lower(sku)"), unique=True, postgresql_where="sku IS NOT NULL"
        ),
        CheckConstraint(f"unit IN {UNITS}", name="unit"),
        CheckConstraint("min_stock >= 0 AND reorder_level >= 0 AND purchase_price >= 0", name="amounts"),
    )


class InventoryStock(Base):
    """Cached balance per item and branch (kept in step with the ledger in the same transaction)."""

    __tablename__ = "inventory_stock"

    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    on_hand: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"), server_default="0")
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"), server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "item_id"], ["inventory_items.tenant_id", "inventory_items.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        Index("ix_inventory_stock_branch", "branch_id"),
    )


class PurchaseOrder(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(12))  # PO-0007
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    invoice_number: Mapped[str] = mapped_column(String(40), default="", server_default="")
    invoice_date: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    payment_status: Mapped[str] = mapped_column(String(8), default="unpaid", server_default="unpaid")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], ondelete="SET NULL (supplier_id)"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_purchase_orders_tenant_id_id"),
        UniqueConstraint("tenant_id", "sequence", name="uq_purchase_orders_sequence"),
        CheckConstraint(f"status IN {PURCHASE_STATUSES}", name="status"),
        CheckConstraint(f"payment_status IN {PAYMENT_STATUSES}", name="payment_status"),
        CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND grand_total >= 0 AND amount_paid >= 0 AND amount_paid <= grand_total",
            name="amounts",
        ),
        Index("ix_purchase_orders_supplier", "supplier_id"),
    )


class PurchaseOrderItem(UUIDPkMixin, Base):
    __tablename__ = "purchase_order_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    purchase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    received_quantity: Mapped[Decimal | None] = mapped_column(QTY)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "purchase_id"], ["purchase_orders.tenant_id", "purchase_orders.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"], ["inventory_items.tenant_id", "inventory_items.id"], ondelete="CASCADE"
        ),
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND tax_pct BETWEEN 0 AND 40", name="amounts"),
        CheckConstraint("received_quantity IS NULL OR received_quantity >= 0", name="received"),
        Index("ix_purchase_order_items_purchase", "purchase_id"),
    )


class PurchasePayment(UUIDPkMixin, CreatedAtMixin, Base):
    """Payments to a supplier against a purchase (PRD §8.3 "track supplier payments")."""

    __tablename__ = "purchase_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    purchase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(12))
    reference: Mapped[str] = mapped_column(String(60), default="", server_default="")
    paid_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "purchase_id"], ["purchase_orders.tenant_id", "purchase_orders.id"], ondelete="CASCADE"
        ),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("method IN ('cash', 'upi', 'bank', 'card', 'cheque')", name="method"),
        Index("ix_purchase_payments_purchase", "purchase_id"),
    )


class StockTransfer(UUIDPkMixin, TimestampMixin, Base):
    """Controlled transfer between branches: stock leaves on send, arrives only when the other branch receives."""

    __tablename__ = "stock_transfers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    to_branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(12))  # TR-0003
    status: Mapped[str] = mapped_column(String(10), default="in_transit", server_default="in_transit")
    notes: Mapped[str] = mapped_column(String(300), default="", server_default="")
    sent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "from_branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "to_branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_stock_transfers_tenant_id_id"),
        UniqueConstraint("tenant_id", "sequence", name="uq_stock_transfers_sequence"),
        CheckConstraint("from_branch_id <> to_branch_id", name="branches"),
        CheckConstraint(f"status IN {TRANSFER_STATUSES}", name="status"),
    )


class StockTransferItem(UUIDPkMixin, Base):
    __tablename__ = "stock_transfer_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"), server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "transfer_id"], ["stock_transfers.tenant_id", "stock_transfers.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"], ["inventory_items.tenant_id", "inventory_items.id"], ondelete="CASCADE"
        ),
        CheckConstraint("quantity > 0", name="quantity"),
        Index("ix_stock_transfer_items_transfer", "transfer_id"),
    )


class RecipeIngredient(UUIDPkMixin, Base):
    """Ingredients of a dish (PRD §8.5). `variant_id` NULL = the base recipe; rows for a size replace it."""

    __tablename__ = "recipe_ingredients"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    menu_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[Decimal] = mapped_column(QTY)  # in `unit` (e.g. 150 g of an item stocked in kg)
    unit: Mapped[str] = mapped_column(String(4))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"], ["menu_items.tenant_id", "menu_items.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["variant_id"], ["menu_item_variants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"], ondelete="CASCADE"
        ),
        UniqueConstraint(
            "menu_item_id",
            "variant_id",
            "inventory_item_id",
            name="uq_recipe_ingredient",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint(f"unit IN {UNITS}", name="unit"),
        Index("ix_recipe_ingredients_menu_item", "menu_item_id"),
    )


class InventoryMovement(UUIDPkMixin, CreatedAtMixin, Base):
    """Insert-only stock ledger. `quantity` is signed in the item's unit; `balance_after` is the branch balance."""

    __tablename__ = "inventory_movements"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(14))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    balance_after: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    reason: Mapped[str] = mapped_column(String(200))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    expiry_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "item_id"], ["inventory_items.tenant_id", "inventory_items.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        CheckConstraint(f"type IN {MOVEMENT_TYPES}", name="type"),
        CheckConstraint("quantity <> 0", name="quantity"),
        CheckConstraint("length(trim(reason)) > 0", name="reason"),
        CheckConstraint(
            "type NOT IN ('wastage', 'damage', 'adjustment', 'addition', 'return', 'opening')"
            " OR actor_user_id IS NOT NULL",
            name="manual_actor",
        ),
        Index(
            "uq_inventory_consumption",
            "order_item_id",
            "item_id",
            unique=True,
            postgresql_where="type = 'consumption'",
        ),
        Index("uq_inventory_reversal", "order_item_id", "item_id", unique=True, postgresql_where="type = 'reversal'"),
        Index("ix_inventory_movements_item_branch", "item_id", "branch_id", "created_at"),
        Index("ix_inventory_movements_branch_created", "branch_id", "created_at"),
        Index("ix_inventory_movements_order", "order_id"),
    )

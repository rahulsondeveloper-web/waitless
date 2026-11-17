import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel

Unit = Literal["kg", "g", "l", "ml", "pcs", "pkt", "box"]
ManualType = Literal["opening", "addition", "wastage", "damage", "adjustment", "return"]
MovementType = Literal[
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
]
Qty = Decimal


# ---------- categories, suppliers, items ----------


class CategoryIn(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0, le=999)


class CategoryOut(CategoryIn):
    id: uuid.UUID


class SupplierIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=300)
    gstin: str = Field(default="", max_length=20)
    notes: str = Field(default="", max_length=2000)
    is_active: bool = True


class SupplierOut(SupplierIn):
    id: uuid.UUID
    purchases_count: int = 0
    purchases_total: Decimal = Decimal("0.00")
    outstanding: Decimal = Decimal("0.00")  # received purchases not yet paid


class ItemIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    sku: str | None = Field(default=None, max_length=40)
    category_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    unit: Unit
    min_stock: Qty = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    reorder_level: Qty = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    tracks_expiry: bool = False
    storage_location: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("sku")
    @classmethod
    def _blank_sku(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None


class ItemOut(ItemIn):
    id: uuid.UUID
    category_name: str | None = None
    supplier_name: str | None = None


# ---------- stock ----------


class StockRow(ApiModel):
    """One item at one branch, with its alert state."""

    item_id: uuid.UUID
    name: str
    sku: str | None
    unit: str
    category_name: str | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    storage_location: str
    on_hand: Decimal
    min_stock: Decimal
    reorder_level: Decimal
    avg_cost: Decimal
    value: Decimal
    state: Literal["ok", "low", "out"]
    is_active: bool
    tracks_expiry: bool


class MovementIn(ApiModel):
    """Manual stock change. `adjustment` takes the *counted* quantity; the others take the change."""

    branch_id: uuid.UUID
    item_id: uuid.UUID
    type: ManualType
    quantity: Qty = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str = Field(default="", max_length=200)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    expiry_date: date | None = None

    @model_validator(mode="after")
    def _rules(self) -> "MovementIn":
        if self.type != "adjustment" and self.quantity <= 0:
            raise ValueError("Enter a quantity greater than 0.")
        if self.type not in ("opening",) and not self.reason.strip():
            raise ValueError("A reason is required for every stock change.")
        return self


class MovementOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    unit: str
    type: MovementType
    quantity: Decimal
    balance_after: Decimal
    unit_cost: Decimal | None
    reason: str
    actor_name: str | None
    order_number: str | None = None
    purchase_number: str | None = None
    transfer_number: str | None = None
    expiry_date: date | None
    created_at: datetime


# ---------- transfers ----------


class TransferLineIn(ApiModel):
    item_id: uuid.UUID
    quantity: Qty = Field(gt=0, max_digits=14, decimal_places=3)


class TransferIn(ApiModel):
    from_branch_id: uuid.UUID
    to_branch_id: uuid.UUID
    items: list[TransferLineIn] = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _distinct(self) -> "TransferIn":
        if self.from_branch_id == self.to_branch_id:
            raise ValueError("Choose two different branches.")
        if len({ln.item_id for ln in self.items}) != len(self.items):
            raise ValueError("Each item can appear only once.")
        return self


class TransferLineOut(ApiModel):
    item_id: uuid.UUID
    name: str
    unit: str
    quantity: Decimal


class TransferOut(ApiModel):
    id: uuid.UUID
    number: str
    status: Literal["in_transit", "received", "cancelled"]
    from_branch_id: uuid.UUID
    from_branch_name: str
    to_branch_id: uuid.UUID
    to_branch_name: str
    items: list[TransferLineOut]
    notes: str
    created_at: datetime
    received_at: datetime | None


# ---------- purchases ----------


class PurchaseLineIn(ApiModel):
    item_id: uuid.UUID
    quantity: Qty = Field(gt=0, max_digits=14, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    tax_pct: Decimal = Field(default=Decimal("0"), ge=0, le=40, decimal_places=2)


class PurchaseIn(ApiModel):
    branch_id: uuid.UUID
    supplier_id: uuid.UUID | None = None
    order_date: date | None = None
    expected_date: date | None = None
    invoice_number: str = Field(default="", max_length=40)
    invoice_date: date | None = None
    notes: str = Field(default="", max_length=2000)
    items: list[PurchaseLineIn] = Field(min_length=1, max_length=100)
    status: Literal["draft", "ordered"] = "draft"


class ReceiveLineIn(ApiModel):
    item_id: uuid.UUID
    received_quantity: Qty = Field(ge=0, max_digits=14, decimal_places=3)
    expiry_date: date | None = None


class ReceiveIn(ApiModel):
    items: list[ReceiveLineIn] = Field(default_factory=list, max_length=100)  # empty = everything as ordered
    invoice_number: str | None = Field(default=None, max_length=40)
    invoice_date: date | None = None


class PaymentIn(ApiModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: Literal["cash", "upi", "bank", "card", "cheque"]
    reference: str = Field(default="", max_length=60)
    paid_on: date | None = None


class PurchaseLineOut(ApiModel):
    item_id: uuid.UUID
    name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    tax_pct: Decimal
    line_total: Decimal
    tax_amount: Decimal
    received_quantity: Decimal | None
    expiry_date: date | None


class PaymentOut(ApiModel):
    id: uuid.UUID
    amount: Decimal
    method: str
    reference: str
    paid_on: date


class PurchaseOut(ApiModel):
    id: uuid.UUID
    number: str
    status: Literal["draft", "ordered", "received", "cancelled"]
    branch_id: uuid.UUID
    branch_name: str
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    order_date: date
    expected_date: date | None
    invoice_number: str
    invoice_date: date | None
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    amount_paid: Decimal
    payment_status: Literal["unpaid", "partial", "paid"]
    notes: str
    items: list[PurchaseLineOut]
    payments: list[PaymentOut]
    received_at: datetime | None
    created_at: datetime


# ---------- recipes ----------


class RecipeLineIn(ApiModel):
    inventory_item_id: uuid.UUID
    variant_id: uuid.UUID | None = None  # None = every size (base recipe)
    quantity: Qty = Field(gt=0, max_digits=14, decimal_places=3)
    unit: Unit


class RecipeIn(ApiModel):
    lines: list[RecipeLineIn] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def _unique(self) -> "RecipeIn":
        keys = [(ln.variant_id, ln.inventory_item_id) for ln in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError("Each ingredient can appear only once per size.")
        return self


class RecipeLineOut(RecipeLineIn):
    name: str
    stock_unit: str
    cost: Decimal  # at the item's purchase price


class RecipeOut(ApiModel):
    menu_item_id: uuid.UUID
    lines: list[RecipeLineOut]
    cost: Decimal  # base recipe cost per portion


# ---------- alerts & reports ----------


class AlertRow(ApiModel):
    item_id: uuid.UUID
    name: str
    unit: str
    on_hand: Decimal
    reorder_level: Decimal
    min_stock: Decimal
    state: Literal["low", "out"]
    suggested_quantity: Decimal  # up to twice the reorder level
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    purchase_price: Decimal


class ExpiryRow(ApiModel):
    item_id: uuid.UUID
    name: str
    unit: str
    quantity: Decimal  # received in that batch
    expiry_date: date
    days_left: int
    on_hand: Decimal


class AlertsOut(ApiModel):
    low: list[AlertRow]
    out: list[AlertRow]
    expiring: list[ExpiryRow]


class ReportOut(ApiModel):
    """A generic table: the UI renders it and exports CSV."""

    kind: str
    title: str
    columns: list[str]
    rows: list[list[str | int | float | None]]
    totals: dict[str, str] = Field(default_factory=dict)

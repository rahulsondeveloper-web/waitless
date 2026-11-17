import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import ApiModel
from app.schemas.sla import PromiseOut, SlaOut

OrderStatus = Literal["placed", "accepted", "preparing", "ready", "served", "cancelled"]


# ---------- placing ----------


class OrderLineIn(ApiModel):
    menu_item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    addon_ids: list[uuid.UUID] = Field(default_factory=list, max_length=40)
    quantity: int = Field(default=1, ge=1, le=50)
    instructions: str = Field(default="", max_length=200)

    @field_validator("addon_ids")
    @classmethod
    def _unique(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(v))


class OrderIn(ApiModel):
    items: list[OrderLineIn] = Field(min_length=1, max_length=50)
    notes: str = Field(default="", max_length=300)


class StaffOrderIn(OrderIn):
    table_session_id: uuid.UUID


class TableJoinIn(ApiModel):
    code: str = Field(min_length=4, max_length=12)
    pin: str = Field(pattern=r"^\d{4}$")

    @field_validator("code")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().upper()


class StatusIn(ApiModel):
    status: Literal["accepted", "preparing", "ready", "served"]


class CancelIn(ApiModel):
    reason: str = Field(default="", max_length=200)


# ---------- reading ----------


class OrderAddonOut(ApiModel):
    name: str
    price: Decimal


class OrderLineOut(ApiModel):
    id: uuid.UUID
    menu_item_id: uuid.UUID | None
    name: str
    variant_name: str | None
    addons: list[OrderAddonOut]
    food_class: str
    unit_price: Decimal
    quantity: int
    tax_pct: Decimal
    line_total: Decimal
    tax_amount: Decimal
    instructions: str


class OrderOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    number: str
    order_type: str
    source: str
    status: OrderStatus
    table_session_id: uuid.UUID | None
    session_code: str | None = None
    table_labels: list[str] = Field(default_factory=list)
    reservation_id: uuid.UUID | None
    reservation_code: str | None = None
    reservation_starts_at: datetime | None = None
    guest_name: str | None = None
    items: list[OrderLineOut]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    notes: str
    placed_at: datetime
    accepted_at: datetime | None
    preparing_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    sla: SlaOut | None = None  # serving timer (Phase 8): starts on accept, or at arrival for paid pre-orders
    discount_total: Decimal = Decimal("0.00")
    payable_total: Decimal | None = None  # total after the serving-time discount
    can_cancel: bool = False  # for the viewer (guest: only while "placed")
    restaurant_name: str | None = None
    restaurant_slug: str | None = None


class TableJoinOut(ApiModel):
    token: str
    expires_at: datetime
    session_id: uuid.UUID


class TableSessionView(ApiModel):
    """What guests at a table see (PRD §13): their orders, times, running total."""

    session_id: uuid.UUID
    code: str
    status: str
    restaurant_name: str
    restaurant_slug: str
    branch_id: uuid.UUID
    branch_name: str
    table_labels: list[str]
    party_size: int
    guest_name: str | None
    opened_at: datetime
    orders: list[OrderOut]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    discount_total: Decimal = Decimal("0.00")
    payable_total: Decimal = Decimal("0.00")
    promise: PromiseOut | None = None
    ordering_open: bool
    server_time: datetime

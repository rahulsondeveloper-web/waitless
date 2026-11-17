from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel

OrderType = Literal["walk_in", "booking", "staff", "paid_preorder"]
ALL_ORDER_TYPES: list[str] = ["walk_in", "booking", "staff", "paid_preorder"]


class DiscountPolicyIn(ApiModel):
    is_active: bool = True
    serving_minutes: int = Field(ge=1, le=180)
    initial_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    interval_minutes: int = Field(ge=1, le=60)
    increment_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    max_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    eligible_order_types: list[OrderType] = Field(min_length=0, max_length=4)
    base: Literal["food_subtotal", "order_total"] = "food_subtotal"

    @field_validator("eligible_order_types")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _cap(self) -> "DiscountPolicyIn":
        if self.max_pct < self.initial_pct:
            raise ValueError("The maximum discount cannot be lower than the first discount.")
        return self


class DiscountPolicyOut(DiscountPolicyIn):
    is_default: bool = False  # nothing saved yet — the PRD defaults apply
    updated_at: datetime | None = None


class PromiseOut(ApiModel):
    """The restaurant's promise, as guests see it ("served in 15 min or it gets cheaper")."""

    is_active: bool
    serving_minutes: int
    initial_pct: Decimal
    interval_minutes: int
    increment_pct: Decimal
    max_pct: Decimal


class SlaOut(ApiModel):
    """The order's serving timer. Clients count down locally from `started_at`/`deadline_at`
    (corrected with the response's `server_time`); the discount shown is computed by the server."""

    started_at: datetime
    deadline_at: datetime
    start_reason: str
    status: Literal["running", "served", "cancelled"]
    ended_at: datetime | None
    eligible: bool  # policy active and this order type earns discounts
    discount_pct: Decimal
    discount_amount: Decimal
    next_boundary_at: datetime | None
    serving_minutes: int
    initial_pct: Decimal
    interval_minutes: int
    increment_pct: Decimal
    max_pct: Decimal
    base: str

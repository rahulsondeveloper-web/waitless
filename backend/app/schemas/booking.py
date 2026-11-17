import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, PhoneNumber

ReservationType = Literal["free", "paid"]


# ---------- policy ----------


class PolicyIn(ApiModel):
    accepts_reservations: bool = True
    accepts_queue: bool = True
    free_enabled: bool = True
    paid_enabled: bool = False
    booking_fee: Decimal = Field(default=Decimal("0"), ge=0, le=100000, max_digits=8, decimal_places=2)
    slot_minutes: Literal[15, 30, 60] = 30
    dining_minutes: int = Field(default=90, ge=30, le=360)
    grace_minutes: int = Field(default=15, ge=0, le=120)
    min_lead_minutes: int = Field(default=60, ge=0, le=10080)
    max_advance_days: int = Field(default=30, ge=1, le=365)
    min_party: int = Field(default=1, ge=1, le=50)
    max_party: int = Field(default=12, ge=1, le=50)
    free_cancel_hours: int = Field(default=2, ge=0, le=168)
    refund_on_no_show: bool = False

    @model_validator(mode="after")
    def _rules(self) -> "PolicyIn":
        if self.max_party < self.min_party:
            raise ValueError("Maximum party size must be at least the minimum.")
        if self.paid_enabled and self.booking_fee <= 0:
            raise ValueError("Set a booking fee to offer paid bookings.")
        if not (self.free_enabled or self.paid_enabled) and self.accepts_reservations:
            raise ValueError("Enable free or paid bookings, or stop accepting reservations.")
        return self


class PolicyOut(PolicyIn):
    branch_id: uuid.UUID


# ---------- availability ----------


class Slot(ApiModel):
    starts_at: datetime
    label: str  # "19:30" in the branch's time zone
    available: bool


class Availability(ApiModel):
    branch_id: uuid.UUID
    date: date
    timezone: str
    party_size: int
    slots: list[Slot]
    free_enabled: bool
    paid_enabled: bool
    booking_fee: Decimal
    currency: str
    grace_minutes: int
    free_cancel_hours: int
    message: str | None = None  # e.g. closed that day


class BookingOptions(ApiModel):
    branch_id: uuid.UUID
    branch_name: str
    accepts_reservations: bool
    accepts_queue: bool
    free_enabled: bool
    paid_enabled: bool
    booking_fee: Decimal
    currency: str
    min_party: int
    max_party: int
    max_advance_days: int
    grace_minutes: int
    free_cancel_hours: int


# ---------- reservations ----------


class ReservationIn(ApiModel):
    branch_id: uuid.UUID
    starts_at: datetime
    party_size: int = Field(ge=1, le=50)
    type: ReservationType = "free"
    guest_name: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _aware(self) -> "ReservationIn":
        if self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a time zone (ISO-8601 with offset).")
        return self


class StaffReservationIn(ReservationIn):
    guest_name: str = Field(min_length=2, max_length=80)  # type: ignore[assignment]
    phone: PhoneNumber | None = None
    type: Literal["free"] = "free"  # type: ignore[assignment]  # staff-made bookings are free


class CheckoutOut(ApiModel):
    provider: str
    order_id: str
    amount: Decimal
    currency: str
    checkout: dict[str, Any]


class ReservationOut(ApiModel):
    id: uuid.UUID
    code: str
    branch_id: uuid.UUID
    branch_name: str | None = None
    restaurant_name: str | None = None
    restaurant_slug: str | None = None
    guest_name: str
    phone: str | None
    party_size: int
    type: ReservationType
    status: str
    starts_at: datetime
    ends_at: datetime
    arrival_deadline: datetime
    payment_due_at: datetime | None
    booking_fee: Decimal
    notes: str
    table_labels: list[str]
    staff_confirmed_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    payment_status: str | None = None
    refunded_amount: Decimal | None = None
    can_cancel: bool = False
    can_preorder: bool = False  # PRD §12: paid bookings only (ordering arrives in Phase 7)


class BookingResult(ApiModel):
    reservation: ReservationOut
    payment: CheckoutOut | None = None


class ArriveIn(ApiModel):
    table_id: uuid.UUID | None = None  # default: the table held for the booking


# ---------- queue ----------


class QueueJoinIn(ApiModel):
    branch_id: uuid.UUID
    party_size: int = Field(ge=1, le=50)
    guest_name: str | None = Field(default=None, max_length=80)


class StaffQueueIn(ApiModel):
    branch_id: uuid.UUID
    party_size: int = Field(ge=1, le=50)
    guest_name: str = Field(min_length=1, max_length=80)
    phone: PhoneNumber | None = None


class QueueEntryOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    token: str
    party_size: int
    guest_name: str
    phone: str | None
    source: str
    status: str
    position: int  # 1-based place among waiting/notified guests (0 when no longer waiting)
    ahead: int
    estimated_wait_minutes: int | None
    joined_at: datetime
    notified_at: datetime | None
    ended_at: datetime | None
    notified_table_label: str | None = None
    restaurant_name: str | None = None
    restaurant_slug: str | None = None


class QueueNotifyIn(ApiModel):
    table_id: uuid.UUID | None = None


class QueueSeatIn(ApiModel):
    table_id: uuid.UUID


class QueueMoveIn(ApiModel):
    direction: Literal["up", "down"]


class WaitTime(ApiModel):
    branch_id: uuid.UUID
    accepting: bool
    waiting: int
    estimated_wait_minutes: int | None
    free_tables: int


class MyBookings(ApiModel):
    reservations: list[ReservationOut]
    queue: list[QueueEntryOut]

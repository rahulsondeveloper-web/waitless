import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel

Method = Literal["cash", "upi", "card", "gateway", "other"]
StaffMethod = Literal["cash", "upi", "card", "other"]


class BillingSettings(ApiModel):
    """Per restaurant (PRD §9 "tax configuration … restaurant settings")."""

    service_charge_pct: Decimal = Field(default=Decimal("0"), ge=0, le=20, decimal_places=2)
    service_charge_tax_pct: Decimal = Field(default=Decimal("5"), ge=0, le=28, decimal_places=2)
    tax_split: Literal["cgst_sgst", "single"] = "cgst_sgst"
    round_off: bool = True
    invoice_prefix: str = Field(default="INV", min_length=1, max_length=8, pattern=r"^[A-Z0-9]+$")
    legal_name: str = Field(default="", max_length=120)
    gstin: str = Field(default="", max_length=20)
    address: str = Field(default="", max_length=300)
    invoice_footer: str = Field(default="Thank you for dining with us!", max_length=300)
    methods: list[Method] = Field(default_factory=lambda: ["cash", "upi", "card", "gateway"], min_length=1)
    other_method_label: str = Field(default="Other", max_length=40)
    # The restaurant's own UPI ID: guests pay it directly from the checkout page (QR / UPI app); staff confirm.
    upi_id: str = Field(default="", max_length=60, pattern=r"^$|^[A-Za-z0-9._-]{2,}@[A-Za-z][A-Za-z0-9.]{1,}$")
    upi_payee_name: str = Field(default="", max_length=60)


class BillLineOut(ApiModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_item_id: uuid.UUID
    order_number: str
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    tax_pct: Decimal
    sla_pct: Decimal
    sla_discount: Decimal
    manual_discount: Decimal
    taxable: Decimal
    ordered_by_name: str | None = None  # screens only — never printed on the invoice


class PaymentOut(ApiModel):
    id: uuid.UUID
    bill_id: uuid.UUID
    method: Method
    method_label: str
    amount: Decimal
    tendered: Decimal | None
    change_due: Decimal
    status: Literal["pending", "captured", "failed"]
    reference: str
    refunded_amount: Decimal
    received_by_name: str | None = None
    created_at: datetime
    captured_at: datetime | None
    # list views
    bill_label: str | None = None
    table_labels: list[str] = Field(default_factory=list)
    invoice_number: str | None = None


class RefundOut(ApiModel):
    id: uuid.UUID
    payment_id: uuid.UUID
    amount: Decimal
    reason: str
    created_at: datetime


class InvoiceRef(ApiModel):
    id: uuid.UUID
    number: str
    kind: Literal["invoice", "credit_note"]
    total: Decimal
    issued_at: datetime


class BillOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    table_session_id: uuid.UUID
    session_code: str
    table_labels: list[str]
    guest_name: str | None
    sequence: int
    label: str  # "Bill" or "Bill 2"
    status: Literal["open", "paid", "void"]
    locked: bool
    merged_into_id: uuid.UUID | None
    lines: list[BillLineOut]
    subtotal: Decimal
    sla_discount: Decimal
    sla_discount_after_tax: Decimal
    manual_discount: Decimal
    manual_discount_pct: Decimal | None
    manual_discount_reason: str | None
    taxable: Decimal
    service_charge_pct: Decimal
    service_charge: Decimal
    tax_total: Decimal
    taxes: list[dict[str, str]]
    booking_credit: Decimal
    round_off: Decimal
    grand_total: Decimal
    paid_total: Decimal
    refunded_total: Decimal
    due: Decimal
    unserved_orders: int  # orders on the bill not yet served
    payments: list[PaymentOut]
    refunds: list[RefundOut]
    invoices: list[InvoiceRef]
    methods: list[Method]
    other_method_label: str
    created_at: datetime
    paid_at: datetime | None


class SessionBillsOut(ApiModel):
    """A table visit with its bills (staff Billing screen and the guest's table page)."""

    session_id: uuid.UUID
    session_code: str
    session_status: str
    branch_id: uuid.UUID
    table_labels: list[str]
    guest_name: str | None
    party_size: int
    opened_at: datetime
    bills: list[BillOut]
    total_due: Decimal
    can_close: bool
    restaurant_name: str = ""
    upi_id: str = ""  # the restaurant's own UPI ID, when set
    upi_payee_name: str = ""


class ActiveTable(ApiModel):
    session_id: uuid.UUID
    session_code: str
    session_status: str
    table_labels: list[str]
    guest_name: str | None
    party_size: int
    opened_at: datetime
    orders: int
    total: Decimal  # all bills (or the running total when no bill yet)
    due: Decimal
    bills: int
    paid: bool


class SplitIn(ApiModel):
    order_item_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class MergeIn(ApiModel):
    source_bill_id: uuid.UUID


class DiscountIn(ApiModel):
    """Either a percentage or an amount (0 / null removes the discount)."""

    pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _one(self) -> "DiscountIn":
        if self.pct is not None and self.amount is not None:
            raise ValueError("Give a percentage or an amount, not both.")
        removing = not (self.pct or self.amount)
        if not removing and not self.reason.strip():
            raise ValueError("A reason is required for a discount.")
        return self


class PaymentIn(ApiModel):
    method: StaffMethod
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    tendered: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)  # cash handed over
    reference: str = Field(default="", max_length=80)
    method_label: str = Field(default="", max_length=40)


class RefundIn(ApiModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=1, max_length=200)


class UpiClaimIn(ApiModel):
    reference: str = Field(default="", max_length=80)  # UPI transaction / UTR number, if the guest has it
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)  # one person's share


class GuestPayIn(ApiModel):
    """Empty = pay everything that is due; `amount` = this person's equal share."""

    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class OnlinePaymentOut(ApiModel):
    payment_id: uuid.UUID
    provider: str
    order_id: str
    amount: Decimal
    currency: str
    checkout: dict[str, Any]


class InvoiceOut(ApiModel):
    id: uuid.UUID
    bill_id: uuid.UUID
    number: str
    kind: Literal["invoice", "credit_note"]
    total: Decimal
    issued_at: datetime
    original_invoice_id: uuid.UUID | None
    snapshot: dict[str, Any]

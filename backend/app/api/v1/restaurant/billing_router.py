"""Billing & POS (PRD §9). Staff routes need plan feature `billing_pos`; guests use their table token."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, TenantCtx, require_feature, require_permission
from app.schemas.billing import (
    ActiveTable,
    BillingSettings,
    BillOut,
    DiscountIn,
    InvoiceOut,
    MergeIn,
    OnlinePaymentOut,
    PaymentIn,
    PaymentOut,
    RefundIn,
    SessionBillsOut,
    SplitIn,
    UpiClaimIn,
)
from app.services import billing as svc
from app.services import invoice_pdf
from app.services.access import TenantContext

router = APIRouter(
    prefix="/restaurant", tags=["restaurant billing"], dependencies=[Depends(require_feature("billing_pos"))]
)
guest_router = APIRouter(tags=["table session billing"])

Billing = Annotated[TenantContext, Depends(require_permission("billing.operate"))]
Collect = Annotated[TenantContext, Depends(require_permission("payments.collect"))]
Refunds = Annotated[TenantContext, Depends(require_permission("payments.refund"))]
Discounts = Annotated[TenantContext, Depends(require_permission("billing.discount.apply"))]
SettingsManage = Annotated[TenantContext, Depends(require_permission("settings.manage"))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)]
TableToken = Annotated[str | None, Header(alias="X-Table-Token")]


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class MockPayIn(BaseModel):
    success: bool = True


class Ack(BaseModel):
    result: str


def _pdf(inv, receipt: bool) -> Response:  # type: ignore[no-untyped-def]
    data = invoice_pdf.render(inv.number, inv.issued_at.isoformat(), inv.snapshot, receipt=receipt)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{inv.number}.pdf"', "Cache-Control": "private, no-store"},
    )


# ---------- settings ----------


@router.get("/billing-settings", response_model=BillingSettings)
async def get_billing_settings(session: SessionDep, ctx: TenantCtx) -> BillingSettings:
    return await svc.get_settings(session, ctx.tenant_id)


@router.put("/billing-settings", response_model=BillingSettings, summary="Service charge, tax split, invoice details")
async def save_billing_settings(body: BillingSettings, session: SessionDep, ctx: SettingsManage) -> BillingSettings:
    return await svc.save_settings(session, ctx, body)


# ---------- tables & bills ----------


@router.get("/billing/tables", response_model=list[ActiveTable], summary="Tables with guests and what they owe")
async def active_tables(session: SessionDep, ctx: Billing, branch_id: uuid.UUID) -> list[ActiveTable]:
    return await svc.active_tables(session, ctx, branch_id)


@router.post("/table-sessions/{session_id}/bill", response_model=SessionBillsOut, summary="Generate / refresh the bill")
async def session_bill(session_id: uuid.UUID, session: SessionDep, ctx: Billing) -> SessionBillsOut:
    return await svc.session_bills(session, ctx, session_id)


@router.post("/table-sessions/{session_id}/reopen", response_model=SessionBillsOut, summary="Reopen a finished table")
async def reopen(session_id: uuid.UUID, session: SessionDep, ctx: Billing) -> SessionBillsOut:
    return await svc.reopen(session, ctx, session_id)


@router.get("/bills", response_model=list[BillOut], summary="Bills of a day, or by status")
async def list_bills(
    session: SessionDep,
    ctx: Billing,
    branch_id: uuid.UUID,
    day: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    status: str | None = Query(default=None, pattern="^(open|paid)$"),
) -> list[BillOut]:
    return await svc.list_bills(session, ctx, branch_id, day, status)


@router.get("/bills/{bill_id}", response_model=BillOut)
async def get_bill(bill_id: uuid.UUID, session: SessionDep, ctx: Billing) -> BillOut:
    return await svc.get_bill(session, ctx, bill_id)


@router.post("/bills/{bill_id}/split", response_model=SessionBillsOut, summary="Move chosen lines to a new bill")
async def split(bill_id: uuid.UUID, body: SplitIn, session: SessionDep, ctx: Billing) -> SessionBillsOut:
    return await svc.split(session, ctx, bill_id, body.order_item_ids)


@router.post("/bills/{bill_id}/merge", response_model=BillOut, summary="Bring another open bill into this one")
async def merge(bill_id: uuid.UUID, body: MergeIn, session: SessionDep, ctx: Billing) -> BillOut:
    return await svc.merge(session, ctx, bill_id, body.source_bill_id)


@router.post(
    "/bills/{bill_id}/discount", response_model=BillOut, summary="Manual discount (% or amount, with a reason)"
)
async def discount(bill_id: uuid.UUID, body: DiscountIn, session: SessionDep, ctx: Discounts) -> BillOut:
    return await svc.set_discount(session, ctx, bill_id, body)


@router.post("/bills/{bill_id}/void", response_model=BillOut, summary="Write off an unpaid bill")
async def void(bill_id: uuid.UUID, body: ReasonIn, session: SessionDep, ctx: Discounts) -> BillOut:
    return await svc.void_bill(session, ctx, bill_id, body.reason)


@router.post("/bills/{bill_id}/payments", response_model=BillOut, status_code=201, summary="Take a payment")
async def take_payment(
    bill_id: uuid.UUID, body: PaymentIn, session: SessionDep, ctx: Collect, idem: IdemKey = None
) -> BillOut:
    """Cash (with change), UPI, card or another method. Paid in full → invoice. Same key → no double charge."""
    return await svc.take_payment(session, ctx, bill_id, body, idem)


@router.post("/bills/{bill_id}/settle", response_model=BillOut, summary="Close a ₹0 bill (covered by credit)")
async def settle(bill_id: uuid.UUID, session: SessionDep, ctx: Billing) -> BillOut:
    return await svc.settle_zero(session, ctx, bill_id)


@router.post("/payments/{payment_id}/refunds", response_model=BillOut, status_code=201, summary="Refund (credit note)")
async def refund(
    payment_id: uuid.UUID, body: RefundIn, session: SessionDep, ctx: Refunds, idem: IdemKey = None
) -> BillOut:
    return await svc.refund(session, ctx, payment_id, body, idem)


@router.get("/payments", response_model=list[PaymentOut], summary="Payment history of a day")
async def payments(
    session: SessionDep,
    ctx: Collect,
    branch_id: uuid.UUID,
    day: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[PaymentOut]:
    return await svc.list_payments(session, ctx, branch_id, day)


@router.get("/invoices", response_model=list[InvoiceOut])
async def invoices(
    session: SessionDep,
    ctx: TenantCtx,
    branch_id: uuid.UUID,
    day: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[InvoiceOut]:
    return await svc.list_invoices(session, ctx, branch_id, day)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def invoice(invoice_id: uuid.UUID, session: SessionDep, ctx: TenantCtx) -> InvoiceOut:
    return svc.invoice_out(await svc.staff_invoice(session, ctx, invoice_id))


@router.get("/invoices/{invoice_id}/pdf", summary="Invoice PDF (A4, or ?format=receipt for 80 mm)")
async def invoice_pdf_route(
    invoice_id: uuid.UUID,
    session: SessionDep,
    ctx: TenantCtx,
    format: str = Query(default="a4", pattern="^(a4|receipt)$"),
) -> Response:
    return _pdf(await svc.staff_invoice(session, ctx, invoice_id), format == "receipt")


# ---------- guests at the table ----------


@guest_router.get("/table-session/bills", response_model=SessionBillsOut)
async def guest_bills(session: SessionDep, token: TableToken = None) -> SessionBillsOut:
    return await svc.guest_bills(session, token)


@guest_router.post(
    "/table-session/finish", response_model=SessionBillsOut, summary="Finish: no more orders, final bill"
)
async def finish(session: SessionDep, token: TableToken = None) -> SessionBillsOut:
    return await svc.finish(session, token)


@guest_router.post("/table-session/bills/{bill_id}/pay", response_model=OnlinePaymentOut, summary="Pay the bill online")
async def pay_online(bill_id: uuid.UUID, session: SessionDep, token: TableToken = None) -> OnlinePaymentOut:
    return await svc.pay_online(session, token, bill_id)


@guest_router.get("/table-session/invoices/{invoice_id}/pdf", summary="Receipt PDF for the guest")
async def guest_invoice_pdf(
    invoice_id: uuid.UUID,
    session: SessionDep,
    token: str | None = Query(default=None, alias="t"),
    x_token: TableToken = None,
) -> Response:
    """The token can come as a header or `?t=` (so the receipt opens in a new browser tab)."""
    return _pdf(await svc.guest_invoice(session, x_token or token, invoice_id), receipt=False)


@guest_router.post("/public/payments/mock-bill/{order_id}", response_model=Ack, summary="Dev mock checkout for bills")
async def mock_bill(order_id: str, body: MockPayIn, session: SessionDep, token: TableToken = None) -> Ack:
    from app.core.config import get_settings
    from app.core.errors import NotFoundError

    if get_settings().is_production or get_settings().payment_provider != "mock":
        raise NotFoundError("Not found.")
    return Ack(result=await svc.mock_bill_payment(session, token, order_id, body.success))


@router.post("/payments/{payment_id}/confirm", response_model=BillOut, summary="The guest's UPI payment arrived")
async def confirm_upi(payment_id: uuid.UUID, session: SessionDep, ctx: Collect) -> BillOut:
    return await svc.review_upi_claim(session, ctx, payment_id, accept=True)


@router.post("/payments/{payment_id}/reject", response_model=BillOut, summary="The guest's UPI payment did not arrive")
async def reject_upi(payment_id: uuid.UUID, session: SessionDep, ctx: Collect) -> BillOut:
    return await svc.review_upi_claim(session, ctx, payment_id, accept=False)


@guest_router.post(
    "/table-session/bills/{bill_id}/upi-claim", response_model=SessionBillsOut, summary="I paid the restaurant's UPI ID"
)
async def upi_claim(
    bill_id: uuid.UUID, body: UpiClaimIn, session: SessionDep, token: TableToken = None
) -> SessionBillsOut:
    return await svc.upi_claim(session, token, bill_id, body.reference)


@guest_router.get("/me/invoices", summary="My invoices at every restaurant (signed in)")
async def my_invoices(session: SessionDep, user: CurrentUser) -> list[dict]:
    return await svc.my_invoices(session, user)


@guest_router.get("/me/invoices/{invoice_id}/pdf", summary="Download one of my invoices")
async def my_invoice_pdf(invoice_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    return _pdf(await svc.my_invoice(session, user, invoice_id), receipt=False)

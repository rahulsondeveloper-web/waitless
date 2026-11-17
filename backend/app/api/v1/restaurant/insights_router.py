"""Restaurant reports (PRD §15), restaurant settings: WaitLess plan & invoices, manager limits, help requests."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, TenantCtx, require_permission
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models import Tenant
from app.services import analytics, platform, saas
from app.services.access import TenantContext
from app.services.audit import write_audit

router = APIRouter(prefix="/restaurant", tags=["restaurant insights & settings"])

Reports = Annotated[TenantContext, Depends(require_permission("reports.view"))]
Subscription = Annotated[TenantContext, Depends(require_permission("subscription.manage"))]
SettingsManage = Annotated[TenantContext, Depends(require_permission("settings.manage"))]


@router.get("/reports", summary="Available reports")
async def report_list(ctx: Reports) -> list[dict[str, str]]:
    return [{"kind": k, "title": v[0], "feature": v[2]} for k, v in analytics.KINDS.items() if ctx.has(v[1])]


@router.get(
    "/reports/{kind}", summary="Sales, orders, serving, discounts, payments, reservations, queue, top dishes, hours"
)
async def report(
    kind: str,
    session: SessionDep,
    ctx: Reports,
    branch_id: uuid.UUID | None = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    return await analytics.report(session, ctx, kind, branch_id, start, end)


# ---------- WaitLess plan ----------


@router.get("/subscription", summary="Plan, usage vs limits, last 30 days")
async def subscription(session: SessionDep, ctx: TenantCtx) -> dict[str, Any]:
    return await saas.usage(session, ctx.tenant_id)


@router.get("/saas-invoices", summary="WaitLess invoices for this restaurant")
async def my_invoices(session: SessionDep, ctx: Subscription) -> list[dict[str, Any]]:
    return await saas.list_invoices(session, ctx.tenant_id, None)


@router.post("/saas-invoices/{invoice_id}/pay", summary="Pay a WaitLess invoice online")
async def pay_invoice(invoice_id: uuid.UUID, session: SessionDep, ctx: Subscription) -> dict[str, Any]:
    return await saas.pay_online(session, ctx.tenant_id, invoice_id)


class MockIn(BaseModel):
    success: bool = True


@router.post("/saas-payments/mock/{order_id}", summary="Dev mock checkout for WaitLess invoices")
async def mock_saas_pay(order_id: str, body: MockIn, session: SessionDep, ctx: Subscription) -> dict[str, str]:
    if get_settings().is_production or get_settings().payment_provider != "mock":
        raise NotFoundError("Not found.")
    return {"result": await saas.mock_pay(session, ctx.tenant_id, order_id, body.success)}


# ---------- manager limits ----------


class LimitsIn(BaseModel):
    manual_discount_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    refund_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


@router.get("/settings/limits", summary="What managers may approve without the owner")
async def get_limits(session: SessionDep, ctx: TenantCtx) -> dict[str, str]:
    tenant = await session.get(Tenant, ctx.tenant_id)
    raw = (tenant.settings or {}).get("manager_limits") or {} if tenant else {}
    return {
        "manual_discount_pct": str(raw.get("manual_discount_pct", "10.00")),
        "refund_amount": str(raw.get("refund_amount", "2000.00")),
    }


@router.put("/settings/limits")
async def put_limits(body: LimitsIn, session: SessionDep, ctx: SettingsManage) -> dict[str, str]:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    settings = dict(tenant.settings or {})
    before = settings.get("manager_limits")
    settings["manager_limits"] = {
        "manual_discount_pct": str(body.manual_discount_pct),
        "refund_amount": str(body.refund_amount),
    }
    tenant.settings = settings
    write_audit(
        session,
        action="settings.manager_limits",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=ctx.user_id,
        diff={"before": before, "after": settings["manager_limits"]},
    )
    await session.commit()
    return settings["manager_limits"]


# ---------- help (support tickets to WaitLess) ----------


class HelpIn(BaseModel):
    topic: Literal["general", "billing", "technical", "complaint", "other"] = "general"
    message: str = Field(min_length=10, max_length=4000)


@router.get("/support", summary="Our help requests")
async def my_tickets(session: SessionDep, ctx: TenantCtx) -> list[dict[str, Any]]:
    return await platform.restaurant_tickets(session, ctx.tenant_id)


@router.post("/support", status_code=201, summary="Ask WaitLess for help")
async def new_ticket(body: HelpIn, session: SessionDep, ctx: TenantCtx, user: CurrentUser) -> dict[str, Any]:
    return await platform.restaurant_ticket(session, ctx.tenant_id, user, body.topic, body.message)

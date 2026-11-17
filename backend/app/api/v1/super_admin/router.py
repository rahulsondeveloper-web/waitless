import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep, SuperAdmin
from app.models import Plan
from app.schemas.common import ApiModel, Page
from app.schemas.tenancy import RestaurantAdminRow, RestaurantRegistration, StatusChangeRequest
from app.services import platform, registration, saas, super_admin

router = APIRouter(prefix="/super-admin", tags=["super-admin"])

TenantStatus = Literal["pending", "active", "suspended", "deactivated", "rejected"]


class PlanOut(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    trial_days: int
    is_active: bool


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/restaurants", response_model=Page[RestaurantAdminRow], summary="All restaurants")
async def list_restaurants(
    session: SessionDep,
    _admin: SuperAdmin,
    status_filter: TenantStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[RestaurantAdminRow]:
    return await super_admin.list_restaurants(session, status=status_filter, q=q, page=page, page_size=page_size)


@router.post(
    "/restaurants",
    response_model=RestaurantAdminRow,
    status_code=status.HTTP_201_CREATED,
    summary="Register a restaurant on behalf of an owner",
)
async def create_restaurant(
    body: RestaurantRegistration, session: SessionDep, admin: SuperAdmin, request: Request
) -> RestaurantAdminRow:
    tenant, _ = await registration.register_restaurant(session, body, actor_user_id=admin.id, ip=_ip(request))
    return await super_admin.get_restaurant(session, tenant.id)


@router.get("/restaurants/{tenant_id}", response_model=RestaurantAdminRow, summary="Restaurant detail")
async def get_restaurant(tenant_id: uuid.UUID, session: SessionDep, _admin: SuperAdmin) -> RestaurantAdminRow:
    return await super_admin.get_restaurant(session, tenant_id)


@router.patch(
    "/restaurants/{tenant_id}/status",
    response_model=RestaurantAdminRow,
    summary="Approve, reject, activate, suspend or deactivate a restaurant",
)
async def change_status(
    tenant_id: uuid.UUID, body: StatusChangeRequest, session: SessionDep, admin: SuperAdmin, request: Request
) -> RestaurantAdminRow:
    return await super_admin.change_status(
        session, tenant_id, body.action, body.reason, actor_user_id=admin.id, ip=_ip(request)
    )


@router.get("/plans", response_model=list[PlanOut], summary="Subscription plans")
async def list_plans(session: SessionDep, _admin: SuperAdmin) -> list[PlanOut]:
    rows = (await session.execute(select(Plan).order_by(Plan.sort_order))).scalars().all()
    return [PlanOut.model_validate(p) for p in rows]


# ---------- Phase 11: overview, plans, subscriptions, SaaS invoices ----------


class PlanAssignIn(BaseModel):
    plan_id: uuid.UUID
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    trial: bool = False
    waive_first_invoice: bool = False


class SubActionIn(BaseModel):
    action: Literal["renew", "extend", "cancel", "stop_renewal", "resume_renewal", "expire"]
    days: int | None = None


class ManualInvoiceIn(BaseModel):
    tenant_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(min_length=1, max_length=200)


class InvoicePaymentIn(BaseModel):
    method: Literal["bank", "upi", "card", "cash", "waived"]
    reference: str = Field(default="", max_length=80)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=500)
    enabled: bool = True


@router.get("/overview", summary="Platform overview (PRD §16)")
async def overview(session: SessionDep, _admin: SuperAdmin) -> dict[str, Any]:
    return await saas.overview(session)


@router.get("/features", summary="Feature & limit catalogue for the plan editor")
async def features(_admin: SuperAdmin) -> list[dict[str, str]]:
    return saas.FEATURE_CATALOG


@router.get("/plans/full", summary="Plans with features, limits and subscriber counts")
async def plans_full(session: SessionDep, _admin: SuperAdmin) -> list[dict[str, Any]]:
    return await saas.plans_out(session)


@router.post("/plans", status_code=201, summary="Create a plan (no code changes needed)")
async def create_plan(body: saas.PlanIn, session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    return await saas.save_plan(session, body, admin.id)


@router.put("/plans/{plan_id}", summary="Edit a plan: prices, features, limits")
async def update_plan(plan_id: uuid.UUID, body: saas.PlanIn, session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    return await saas.save_plan(session, body, admin.id, plan_id)


@router.get("/restaurants/{tenant_id}/usage", summary="Usage vs plan limits")
async def restaurant_usage(tenant_id: uuid.UUID, session: SessionDep, _admin: SuperAdmin) -> dict[str, Any]:
    return await saas.usage(session, tenant_id)


@router.post("/restaurants/{tenant_id}/subscription", summary="Assign / upgrade / downgrade a plan (immediate)")
async def assign_plan(
    tenant_id: uuid.UUID, body: PlanAssignIn, session: SessionDep, admin: SuperAdmin
) -> dict[str, Any]:
    return await saas.assign_plan(
        session,
        tenant_id,
        body.plan_id,
        body.billing_cycle,
        admin.id,
        trial=body.trial,
        waive_first_invoice=body.waive_first_invoice,
    )


@router.get("/subscriptions", summary="Latest subscription of every restaurant")
async def subscriptions(
    session: SessionDep,
    _admin: SuperAdmin,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(trialing|active|past_due|cancelled|expired|expiring)$"
    ),
    q: str | None = Query(default=None, max_length=100),
) -> list[dict[str, Any]]:
    return await saas.list_subscriptions(session, status_filter, q)


@router.post("/subscriptions/{sub_id}/actions", summary="Renew, extend, cancel, stop/resume renewal, expire")
async def subscription_action(
    sub_id: uuid.UUID, body: SubActionIn, session: SessionDep, admin: SuperAdmin
) -> dict[str, Any]:
    return await saas.update_subscription(session, sub_id, body.action, admin.id, body.days)


@router.post("/subscriptions/run-renewals", summary="Run the renewal / expiry job now")
async def run_renewals(session: SessionDep, _admin: SuperAdmin) -> dict[str, int]:
    return await saas.tick(session)


@router.get("/saas-invoices", summary="WaitLess invoices (separate from restaurant bills)")
async def saas_invoices(
    session: SessionDep,
    _admin: SuperAdmin,
    tenant_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(due|paid|void)$"),
) -> list[dict[str, Any]]:
    return await saas.list_invoices(session, tenant_id, status_filter)


@router.post("/saas-invoices", status_code=201, summary="Manual invoice")
async def create_saas_invoice(body: ManualInvoiceIn, session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    return await saas.manual_invoice(session, body.tenant_id, body.amount, body.description, admin.id)


@router.post("/saas-invoices/{invoice_id}/payments", summary="Record a payment (bank, UPI, card, cash, waived)")
async def pay_saas_invoice(
    invoice_id: uuid.UUID, body: InvoicePaymentIn, session: SessionDep, admin: SuperAdmin
) -> dict[str, Any]:
    return await saas.record_payment(session, invoice_id, body.method, body.reference, admin.id)


@router.post("/saas-invoices/{invoice_id}/void", summary="Void an unpaid invoice")
async def void_saas_invoice(
    invoice_id: uuid.UUID, body: ReasonIn, session: SessionDep, admin: SuperAdmin
) -> dict[str, Any]:
    return await saas.void_invoice(session, invoice_id, body.reason, admin.id)


# ---------- content, support, audit, settings, templates ----------


@router.get("/content", summary="All website sections (defaults + saved)")
async def get_content(session: SessionDep, _admin: SuperAdmin) -> dict[str, Any]:
    return await platform.content_all(session)


@router.put("/content/{key}", summary="Save one website section")
async def put_content(key: str, body: dict[str, Any], session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    return await platform.save_content(session, key, body, admin.id)


@router.get("/support/tickets")
async def support_tickets(
    session: SessionDep,
    _admin: SuperAdmin,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(active|open|in_progress|resolved|closed)$"
    ),
    q: str | None = Query(default=None, max_length=100),
    tenant_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    return await platform.tickets(session, status_filter, q, tenant_id)


@router.get("/support/tickets/{ticket_id}")
async def support_ticket(ticket_id: uuid.UUID, session: SessionDep, _admin: SuperAdmin) -> dict[str, Any]:
    return await platform.ticket(session, ticket_id)


@router.patch("/support/tickets/{ticket_id}", summary="Status, priority, assignee")
async def update_ticket(
    ticket_id: uuid.UUID, body: dict[str, Any], session: SessionDep, admin: SuperAdmin
) -> dict[str, Any]:
    allowed = {k: v for k, v in body.items() if k in ("status", "priority", "assigned_to_id")}
    return await platform.update_ticket(session, ticket_id, allowed, admin.id)


@router.post("/support/tickets/{ticket_id}/notes", summary="Internal note")
async def ticket_note(ticket_id: uuid.UUID, body: NoteIn, session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    return await platform.add_note(session, ticket_id, body.body, admin.id)


@router.get("/admins", summary="WaitLess administrators")
async def list_admins(session: SessionDep, _admin: SuperAdmin) -> list[dict[str, Any]]:
    return await platform.admins(session)


@router.get("/audit", summary="Platform audit log")
async def audit_log(
    session: SessionDep,
    _admin: SuperAdmin,
    tenant_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    admins_only: bool = False,
    action: str | None = Query(default=None, max_length=100),
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return await platform.audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        admins_only=admins_only,
        action=action,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get("/settings", summary="System settings and integration status")
async def get_settings_route(session: SessionDep, _admin: SuperAdmin) -> dict[str, Any]:
    return {"settings": await saas.platform_settings(session), "integrations": saas.integrations()}


@router.put("/settings", summary="Save system settings")
async def put_settings(body: dict[str, Any], session: SessionDep, admin: SuperAdmin) -> dict[str, Any]:
    saved = await saas.save_platform_settings(session, body, admin.id)
    platform.clear_cache()
    return {"settings": saved, "integrations": saas.integrations()}


@router.get("/notification-templates")
async def get_templates(session: SessionDep, _admin: SuperAdmin) -> list[dict[str, Any]]:
    return await platform.templates(session)


@router.put("/notification-templates/{event}")
async def put_template(event: str, body: TemplateIn, session: SessionDep, admin: SuperAdmin) -> list[dict[str, Any]]:
    return await platform.save_template(session, event, body.title, body.body, body.enabled, admin.id)

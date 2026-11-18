"""WaitLess SaaS administration (PRD §16–17): plans, subscriptions, renewals, SaaS invoices & payments,
platform overview and restaurant usage. Completely separate from restaurant bills (D18).

Plans are data: features (on/off) and limits live in `plan_features`, so new plans need no code. Limits are
read on every check (no cache), so a new plan or a changed limit applies immediately.

Subscription lifecycle (worker `subscription_tick`, daily + on demand):
  trialing --period end--> active (free plan) | past_due + renewal invoice (paid plan)
  active   --period end--> next period (free) | past_due + invoice (paid) | cancelled (auto-renew off)
  past_due --grace ends--> expired (paid features stop)
  paying the renewal invoice → active for the invoice's period.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.core.errors import AppError, ConflictError, NotFoundError
from app.integrations.payments.gateway import PaymentEvent, get_gateway
from app.models import Branch, Membership, Plan, PlanFeature, Subscription, Tenant, User
from app.models.billing import Bill
from app.models.booking import Reservation
from app.models.orders import Order
from app.models.platform_admin import PlatformSetting, SaasInvoice, SaasPayment
from app.models.saas import LIVE_SUBSCRIPTION_STATUSES
from app.models.tables import RestaurantTable
from app.services.audit import write_audit

log = logging.getLogger(__name__)
CENT = Decimal("0.01")

FEATURE_CATALOG: list[dict[str, str]] = [
    {"key": "storefront", "label": "Branded storefront", "kind": "feature"},
    {"key": "menu.basic", "label": "Digital menu", "kind": "feature"},
    {"key": "queue", "label": "Walk-in queue", "kind": "feature"},
    {"key": "tables", "label": "Table management", "kind": "feature"},
    {"key": "reservations", "label": "Reservations", "kind": "feature"},
    {"key": "reservations.paid", "label": "Paid bookings & pre-orders", "kind": "feature"},
    {"key": "ordering", "label": "Digital ordering, kitchen & 15-minute promise", "kind": "feature"},
    {"key": "inventory", "label": "Inventory, suppliers & recipes", "kind": "feature"},
    {"key": "billing_pos", "label": "Billing & POS", "kind": "feature"},
    {"key": "analytics.basic", "label": "Reports", "kind": "feature"},
    {"key": "analytics.advanced", "label": "Advanced analytics (best sellers, busy hours)", "kind": "feature"},
    {"key": "notifications.whatsapp", "label": "WhatsApp notifications", "kind": "feature"},
    {"key": "priority_support", "label": "Priority support", "kind": "feature"},
    {"key": "custom_integrations", "label": "Custom integrations", "kind": "feature"},
    {"key": "max_branches", "label": "Branches", "kind": "limit"},
    {"key": "max_staff", "label": "Employees", "kind": "limit"},
    {"key": "max_tables_per_branch", "label": "Tables per branch", "kind": "limit"},
]
_KNOWN = {f["key"] for f in FEATURE_CATALOG}
DEFAULT_PLATFORM_SETTINGS: dict[str, Any] = {
    "grace_days": 7,
    "saas_tax_pct": "18.00",
    "invoice_due_days": 7,
    "support_email": "support@waitless.app",
    "support_phone": "",
    "maintenance_banner": "",
    "allow_registration": True,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- schemas (kept with the service: platform-only) ----------


class FeatureIn(BaseModel):
    key: str
    enabled: bool = True
    limit: int | None = None  # for limits: None = unlimited


class PlanIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    price_monthly: Decimal = Decimal("0")
    price_yearly: Decimal = Decimal("0")
    currency: str = "INR"
    trial_days: int = 14
    is_public: bool = True
    is_active: bool = True
    sort_order: int = 0
    features: list[FeatureIn] = []


# ---------- platform settings ----------


async def platform_settings(session: AsyncSession) -> dict[str, Any]:
    await use_system(session)
    saved = {s.key: s.value for s in (await session.execute(select(PlatformSetting))).scalars()}
    return {**DEFAULT_PLATFORM_SETTINGS, **saved}


async def save_platform_settings(session: AsyncSession, data: dict[str, Any], actor: uuid.UUID) -> dict[str, Any]:
    await use_system(session)
    before = await platform_settings(session)
    for key, value in data.items():
        if key not in DEFAULT_PLATFORM_SETTINGS:
            raise AppError(f"Unknown setting {key}.", code="UNKNOWN_SETTING", status_code=422)
        row = await session.get(PlatformSetting, key)
        if row is None:
            session.add(PlatformSetting(key=key, value=value, updated_by=actor))
        else:
            row.value, row.updated_by = value, actor
    write_audit(
        session,
        action="platform.settings_updated",
        entity="platform",
        actor_user_id=actor,
        diff={"before": before, "after": data},
    )
    await session.commit()
    return await platform_settings(session)


def integrations() -> list[dict[str, str]]:
    """What is connected — never the secrets themselves."""
    from app.core.config import get_settings

    s = get_settings()
    rz = bool(s.cashfree_app_id and s.cashfree_secret_key)
    return [
        {
            "name": "Payments",
            "provider": s.payment_provider,
            "status": "test mode" if s.payment_provider == "mock" else ("connected" if rz else "keys missing"),
        },
        {
            "name": "Maps",
            "provider": "OpenStreetMap (Nominatim)",
            "status": "connected",
            "note": "Google Maps when a key is provided",
        },
        {"name": "File storage", "provider": "Local folder", "status": "connected", "note": "Amazon S3 in production"},
        {
            "name": "SMS / WhatsApp / e-mail",
            "provider": "Server log (development)",
            "status": "not connected",
            "note": "Real providers in Phase 12",
        },
        {
            "name": "Real-time",
            "provider": "Socket.IO + Redis",
            "status": "connected" if s.redis_enabled else "single server",
        },
    ]


# ---------- plans ----------


async def plans_out(session: AsyncSession) -> list[dict[str, Any]]:
    await use_system(session)
    plans = list((await session.execute(select(Plan).order_by(Plan.sort_order, Plan.name))).scalars())
    feats: dict[uuid.UUID, list[dict[str, Any]]] = {p.id: [] for p in plans}
    for f in (await session.execute(select(PlanFeature))).scalars():
        if f.plan_id in feats:
            feats[f.plan_id].append({"key": f.feature_key, "enabled": f.enabled, "limit": f.limit_value})
    subs = dict(
        (
            await session.execute(
                select(Subscription.plan_id, func.count())
                .where(Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
                .group_by(Subscription.plan_id)
            )
        )
        .tuples()
        .all()
    )
    return [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "price_monthly": str(p.price_monthly),
            "price_yearly": str(p.price_yearly),
            "currency": p.currency,
            "trial_days": p.trial_days,
            "is_public": p.is_public,
            "is_active": p.is_active,
            "sort_order": p.sort_order,
            "features": sorted(feats[p.id], key=lambda x: x["key"]),
            "subscribers": subs.get(p.id, 0),
        }
        for p in plans
    ]


def _validate_plan(data: PlanIn) -> None:
    if not data.code or not data.code.replace("_", "").replace("-", "").isalnum() or len(data.code) > 40:
        raise AppError("Use letters, numbers, - or _ for the code.", code="INVALID_CODE", status_code=422)
    if not data.name.strip():
        raise AppError("Give the plan a name.", code="NAME_REQUIRED", status_code=422)
    if data.price_monthly < 0 or data.price_yearly < 0 or not 0 <= data.trial_days <= 90:
        raise AppError("Prices cannot be negative and the trial is 0–90 days.", code="INVALID_PLAN", status_code=422)
    for f in data.features:
        if f.key not in _KNOWN:
            raise AppError(f"Unknown feature {f.key}.", code="UNKNOWN_FEATURE", status_code=422)
        if f.limit is not None and f.limit < 0:
            raise AppError("Limits cannot be negative.", code="INVALID_LIMIT", status_code=422)


async def save_plan(
    session: AsyncSession, data: PlanIn, actor: uuid.UUID, plan_id: uuid.UUID | None = None
) -> dict[str, Any]:
    await use_system(session)
    _validate_plan(data)
    plan = await session.get(Plan, plan_id) if plan_id else None
    if plan_id and plan is None:
        raise NotFoundError("Plan not found.")
    if plan is None:
        plan = Plan(code=data.code)
        session.add(plan)
    elif plan.code != data.code:
        raise ConflictError("The plan code cannot change.", code="CODE_LOCKED")
    for k in (
        "name",
        "description",
        "price_monthly",
        "price_yearly",
        "currency",
        "trial_days",
        "is_public",
        "is_active",
        "sort_order",
    ):
        setattr(plan, k, getattr(data, k))
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A plan with this code already exists.", code="DUPLICATE_CODE") from exc
    for old in (await session.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id))).scalars():
        await session.delete(old)
    await session.flush()
    for f in data.features:
        is_limit = f.key.startswith("max_")
        session.add(
            PlanFeature(
                plan_id=plan.id,
                feature_key=f.key,
                enabled=True if is_limit else f.enabled,
                limit_value=f.limit if is_limit else None,
            )
        )
    write_audit(
        session,
        action="plan.created" if plan_id is None else "plan.updated",
        entity="plan",
        entity_id=plan.id,
        actor_user_id=actor,
        diff=data.model_dump(mode="json"),
    )
    await session.commit()
    return next(p for p in await plans_out(session) if p["id"] == plan.id)


# ---------- subscriptions ----------


def _cycle(cycle: str) -> timedelta:
    return timedelta(days=365 if cycle == "yearly" else 30)


def _price(plan: Plan, cycle: str) -> Decimal:
    return plan.price_yearly if cycle == "yearly" else plan.price_monthly


async def _next_invoice_number(session: AsyncSession) -> tuple[int, str]:
    seq = (await session.execute(select(func.coalesce(func.max(SaasInvoice.sequence), 0)))).scalar_one() + 1
    return seq, f"WL-{seq:06d}"


async def create_invoice(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    amount: Decimal,
    description: str,
    *,
    sub: Subscription | None = None,
    plan: Plan | None = None,
    period: tuple[date, date] | None = None,
    kind: str = "renewal",
    actor: uuid.UUID | None = None,
) -> SaasInvoice:
    """Caller commits."""
    settings = await platform_settings(session)
    tax_pct = Decimal(str(settings["saas_tax_pct"]))
    tax = _money(amount * tax_pct / 100)
    for _attempt in range(5):
        seq, number = await _next_invoice_number(session)
        inv = SaasInvoice(
            tenant_id=tenant_id,
            subscription_id=sub.id if sub else None,
            plan_id=plan.id if plan else None,
            sequence=seq,
            number=number,
            description=description[:200],
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            amount=_money(amount),
            tax_pct=tax_pct,
            tax=tax,
            total=_money(amount + tax),
            currency=plan.currency if plan else "INR",
            status="due",
            due_date=_now().date() + timedelta(days=int(settings["invoice_due_days"])),
            kind=kind,
            created_by=actor,
        )
        try:
            async with session.begin_nested():
                session.add(inv)
                await session.flush()
            return inv
        except IntegrityError:
            continue
    raise ConflictError("Busy right now, please try again.", code="BUSY")  # pragma: no cover


async def assign_plan(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    cycle: str,
    actor: uuid.UUID,
    *,
    trial: bool = False,
    waive_first_invoice: bool = False,
) -> dict[str, Any]:
    """Upgrade / downgrade / assign. Takes effect immediately (the old subscription is cancelled)."""
    await use_system(session)
    tenant = await session.get(Tenant, tenant_id)
    plan = await session.get(Plan, plan_id)
    if tenant is None:
        raise NotFoundError("Restaurant not found.")
    if plan is None or not plan.is_active:
        raise NotFoundError("Plan not found or not active.")
    if cycle not in ("monthly", "yearly"):
        raise AppError("Choose monthly or yearly.", code="INVALID_CYCLE", status_code=422)
    now = _now()
    old = (
        await session.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
            .with_for_update()
        )
    ).scalar_one_or_none()
    old_plan = await session.get(Plan, old.plan_id) if old else None
    if old is not None:
        old.status, old.cancelled_at = "cancelled", now
        await session.flush()
    if trial and plan.trial_days:
        sub = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="trialing",
            billing_cycle=cycle,
            trial_ends_at=now + timedelta(days=plan.trial_days),
            current_period_start=now,
            current_period_end=now + timedelta(days=plan.trial_days),
        )
        session.add(sub)
        await session.flush()
    else:
        end = now + _cycle(cycle)
        price = _price(plan, cycle)
        sub = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="active",
            billing_cycle=cycle,
            current_period_start=now,
            current_period_end=end,
        )
        session.add(sub)
        await session.flush()
        if price > 0 and not waive_first_invoice:
            await create_invoice(
                session,
                tenant_id,
                price,
                f"{plan.name} plan ({cycle})",
                sub=sub,
                plan=plan,
                period=(now.date(), end.date()),
                actor=actor,
            )
    write_audit(
        session,
        action="subscription.plan_changed",
        entity="tenant",
        entity_id=tenant_id,
        tenant_id=tenant_id,
        actor_user_id=actor,
        diff={"from": old_plan.code if old_plan else None, "to": plan.code, "cycle": cycle, "trial": trial},
    )
    await session.commit()
    return await subscription_row(session, sub)


async def subscription_row(session: AsyncSession, sub: Subscription) -> dict[str, Any]:
    await session.refresh(sub)
    plan = await session.get(Plan, sub.plan_id, populate_existing=True)
    tenant = await session.get(Tenant, sub.tenant_id, populate_existing=True)
    due = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(SaasInvoice.total), 0)).where(
                SaasInvoice.tenant_id == sub.tenant_id, SaasInvoice.status == "due"
            )
        )
    ).one()
    return _row(sub, plan, tenant, int(due[0]), Decimal(due[1]))


def _row(
    sub: Subscription, plan: Plan | None, tenant: Tenant | None, due_count: int, due_sum: Decimal
) -> dict[str, Any]:
    return {
        "id": sub.id,
        "tenant_id": sub.tenant_id,
        "tenant_name": tenant.name if tenant else "",
        "tenant_slug": tenant.slug if tenant else "",
        "tenant_status": tenant.status if tenant else "",
        "plan_id": sub.plan_id,
        "plan_code": plan.code if plan else "",
        "plan_name": plan.name if plan else "",
        "status": sub.status,
        "billing_cycle": sub.billing_cycle,
        "trial_ends_at": sub.trial_ends_at,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "grace_ends_at": sub.grace_ends_at,
        "auto_renew": sub.auto_renew,
        "cancelled_at": sub.cancelled_at,
        "price": str(_price(plan, sub.billing_cycle)) if plan else "0.00",
        "invoices_due": due_count,
        "amount_due": str(_money(due_sum)),
    }


async def list_subscriptions(session: AsyncSession, status: str | None, q: str | None) -> list[dict[str, Any]]:
    """The latest subscription of every restaurant (live first)."""
    await use_system(session)
    latest = (
        select(Subscription.tenant_id, func.max(Subscription.created_at).label("at"))
        .group_by(Subscription.tenant_id)
        .subquery()
    )
    stmt = (
        select(Subscription)
        .join(latest, (latest.c.tenant_id == Subscription.tenant_id) & (latest.c.at == Subscription.created_at))
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .order_by(Subscription.current_period_end)
    )
    if status == "expiring":
        stmt = stmt.where(
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.current_period_end < _now() + timedelta(days=7),
        )
    elif status:
        stmt = stmt.where(Subscription.status == status)
    if q:
        stmt = stmt.where(or_(Tenant.name.ilike(f"%{q}%"), Tenant.slug.ilike(f"%{q}%")))
    subs = list((await session.execute(stmt.limit(500))).scalars())
    if not subs:
        return []
    # Three batched queries instead of four per restaurant (the list grows with every restaurant).
    tids = {x.tenant_id for x in subs}
    plans = {
        p.id: p for p in (await session.execute(select(Plan).where(Plan.id.in_({x.plan_id for x in subs})))).scalars()
    }
    tenants = {t.id: t for t in (await session.execute(select(Tenant).where(Tenant.id.in_(tids)))).scalars()}
    dues = {
        tid: (int(n), Decimal(total))
        for tid, n, total in (
            await session.execute(
                select(SaasInvoice.tenant_id, func.count(), func.coalesce(func.sum(SaasInvoice.total), 0))
                .where(SaasInvoice.tenant_id.in_(tids), SaasInvoice.status == "due")
                .group_by(SaasInvoice.tenant_id)
            )
        ).tuples()
    }
    return [
        _row(x, plans.get(x.plan_id), tenants.get(x.tenant_id), *dues.get(x.tenant_id, (0, Decimal(0)))) for x in subs
    ]


async def _sub(session: AsyncSession, sub_id: uuid.UUID) -> Subscription:
    await use_system(session)
    sub = (
        await session.execute(select(Subscription).where(Subscription.id == sub_id).with_for_update())
    ).scalar_one_or_none()
    if sub is None:
        raise NotFoundError("Subscription not found.")
    return sub


async def update_subscription(
    session: AsyncSession, sub_id: uuid.UUID, action: str, actor: uuid.UUID, days: int | None = None
) -> dict[str, Any]:
    """renew (invoice the next period now) · extend (free days) · cancel (now) ·
    stop_renewal · resume_renewal · expire."""
    sub = await _sub(session, sub_id)
    plan = await session.get(Plan, sub.plan_id)
    assert plan is not None
    now = _now()
    if action == "renew":
        if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
            raise ConflictError("Only a live subscription can be renewed — assign a plan instead.", code="NOT_LIVE")
        await _invoice_next_period(session, sub, plan, actor)
    elif action == "extend":
        if not days or not 1 <= days <= 366:
            raise AppError("Give 1–366 days.", code="INVALID_DAYS", status_code=422)
        sub.current_period_end = max(sub.current_period_end, now) + timedelta(days=days)
        if sub.status == "past_due":
            sub.status, sub.grace_ends_at = "active", None
        if sub.status == "trialing":
            sub.trial_ends_at = sub.current_period_end
    elif action == "cancel":
        if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
            raise ConflictError("This subscription is not live.", code="NOT_LIVE")
        sub.status, sub.cancelled_at = "cancelled", now
    elif action == "stop_renewal":
        sub.auto_renew = False
    elif action == "resume_renewal":
        sub.auto_renew = True
    elif action == "expire":
        if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
            raise ConflictError("This subscription is not live.", code="NOT_LIVE")
        sub.status = "expired"
    else:
        raise AppError("Unknown action.", code="UNKNOWN_ACTION", status_code=422)
    write_audit(
        session,
        action=f"subscription.{action}",
        entity="subscription",
        entity_id=sub.id,
        tenant_id=sub.tenant_id,
        actor_user_id=actor,
        diff={"days": days} if days else None,
    )
    await session.commit()
    return await subscription_row(session, sub)


async def _invoice_next_period(
    session: AsyncSession, sub: Subscription, plan: Plan, actor: uuid.UUID | None
) -> SaasInvoice | None:
    start = sub.current_period_end
    end = start + _cycle(sub.billing_cycle)
    existing = (
        await session.execute(
            select(SaasInvoice).where(
                SaasInvoice.subscription_id == sub.id,
                SaasInvoice.period_start == start.date(),
                SaasInvoice.status != "void",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await create_invoice(
        session,
        sub.tenant_id,
        _price(plan, sub.billing_cycle),
        f"{plan.name} plan renewal ({sub.billing_cycle})",
        sub=sub,
        plan=plan,
        period=(start.date(), end.date()),
        actor=actor,
    )


async def tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Renewals, past-due and expiry (worker, daily). Idempotent."""
    now = now or _now()
    await use_system(session)
    settings = await platform_settings(session)
    grace = timedelta(days=int(settings["grace_days"]))
    counts = {"renewed": 0, "invoiced": 0, "expired": 0, "ended": 0}
    subs = list(
        (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                    or_(Subscription.current_period_end < now, Subscription.grace_ends_at < now),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for sub in subs:
        plan = await session.get(Plan, sub.plan_id)
        assert plan is not None
        price = _price(plan, sub.billing_cycle)
        if sub.status == "past_due":
            if sub.grace_ends_at and sub.grace_ends_at < now:
                sub.status = "expired"
                counts["expired"] += 1
            continue
        if sub.current_period_end >= now:
            continue
        if not sub.auto_renew:
            sub.status, sub.cancelled_at = "cancelled", now
            counts["ended"] += 1
        elif price <= 0:
            while sub.current_period_end < now:  # free plan: roll on
                sub.current_period_start = sub.current_period_end
                sub.current_period_end = sub.current_period_end + _cycle(sub.billing_cycle)
            sub.status = "active"
            counts["renewed"] += 1
        else:
            await _invoice_next_period(session, sub, plan, None)
            sub.status, sub.grace_ends_at = "past_due", now + grace
            counts["invoiced"] += 1
        write_audit(
            session,
            action=f"subscription.{sub.status}",
            entity="subscription",
            entity_id=sub.id,
            tenant_id=sub.tenant_id,
        )
    await session.commit()
    return counts


# ---------- SaaS invoices & payments ----------


def invoice_row(
    inv: SaasInvoice, tenant: Tenant | None = None, payments: list[SaasPayment] | None = None
) -> dict[str, Any]:
    return {
        "id": inv.id,
        "number": inv.number,
        "tenant_id": inv.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "description": inv.description,
        "period_start": inv.period_start,
        "period_end": inv.period_end,
        "amount": str(inv.amount),
        "tax_pct": str(inv.tax_pct),
        "tax": str(inv.tax),
        "total": str(inv.total),
        "currency": inv.currency,
        "status": inv.status,
        "due_date": inv.due_date,
        "paid_at": inv.paid_at,
        "kind": inv.kind,
        "created_at": inv.created_at,
        "payments": [
            {
                "id": p.id,
                "amount": str(p.amount),
                "method": p.method,
                "status": p.status,
                "reference": p.reference,
                "created_at": p.created_at,
            }
            for p in (payments or [])
        ],
    }


async def list_invoices(session: AsyncSession, tenant_id: uuid.UUID | None, status: str | None) -> list[dict[str, Any]]:
    await use_system(session)
    stmt = select(SaasInvoice).order_by(SaasInvoice.created_at.desc()).limit(500)
    if tenant_id:
        stmt = stmt.where(SaasInvoice.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(SaasInvoice.status == status)
    invs = list((await session.execute(stmt)).scalars())
    tenants = (
        {
            t.id: t
            for t in (await session.execute(select(Tenant).where(Tenant.id.in_({i.tenant_id for i in invs})))).scalars()
        }
        if invs
        else {}
    )
    pays: dict[uuid.UUID, list[SaasPayment]] = {}
    if invs:
        for p in (
            await session.execute(
                select(SaasPayment)
                .where(SaasPayment.invoice_id.in_([i.id for i in invs]))
                .order_by(SaasPayment.created_at)
            )
        ).scalars():
            pays.setdefault(p.invoice_id, []).append(p)
    return [invoice_row(i, tenants.get(i.tenant_id), pays.get(i.id)) for i in invs]


async def _mark_paid(session: AsyncSession, inv: SaasInvoice) -> None:
    inv.status, inv.paid_at = "paid", _now()
    if inv.subscription_id:
        sub = await session.get(Subscription, inv.subscription_id)
        if sub is not None and sub.status in ("past_due", "active", "trialing") and inv.period_start and inv.period_end:
            start = datetime.combine(inv.period_start, datetime.min.time(), UTC)
            end = datetime.combine(inv.period_end, datetime.min.time(), UTC)
            if end > sub.current_period_end or sub.status == "past_due":
                sub.current_period_start, sub.current_period_end = start, max(end, sub.current_period_end)
            sub.status, sub.grace_ends_at = "active", None


async def record_payment(
    session: AsyncSession, invoice_id: uuid.UUID, method: str, reference: str, actor: uuid.UUID
) -> dict[str, Any]:
    await use_system(session)
    inv = (
        await session.execute(select(SaasInvoice).where(SaasInvoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if inv is None:
        raise NotFoundError("Invoice not found.")
    if inv.status != "due":
        raise ConflictError(f"This invoice is {inv.status}.", code="INVOICE_CLOSED")
    if method not in ("bank", "upi", "card", "cash", "waived"):
        raise AppError("Unknown payment method.", code="INVALID_METHOD", status_code=422)
    session.add(
        SaasPayment(
            invoice_id=inv.id,
            tenant_id=inv.tenant_id,
            amount=inv.total if method != "waived" else Decimal("0"),
            method=method,
            reference=reference[:80],
            recorded_by=actor,
        )
    )
    await _mark_paid(session, inv)
    write_audit(
        session,
        action="saas_invoice.paid",
        entity="saas_invoice",
        entity_id=inv.id,
        tenant_id=inv.tenant_id,
        actor_user_id=actor,
        diff={"method": method, "total": str(inv.total)},
    )
    await session.commit()
    return next(r for r in await list_invoices(session, inv.tenant_id, None) if r["id"] == inv.id)


async def void_invoice(session: AsyncSession, invoice_id: uuid.UUID, reason: str, actor: uuid.UUID) -> dict[str, Any]:
    await use_system(session)
    inv = (
        await session.execute(select(SaasInvoice).where(SaasInvoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if inv is None:
        raise NotFoundError("Invoice not found.")
    if inv.status != "due":
        raise ConflictError(f"This invoice is {inv.status}.", code="INVOICE_CLOSED")
    inv.status = "void"
    write_audit(
        session,
        action="saas_invoice.voided",
        entity="saas_invoice",
        entity_id=inv.id,
        tenant_id=inv.tenant_id,
        actor_user_id=actor,
        reason=reason,
    )
    await session.commit()
    return next(r for r in await list_invoices(session, inv.tenant_id, None) if r["id"] == inv.id)


async def manual_invoice(
    session: AsyncSession, tenant_id: uuid.UUID, amount: Decimal, description: str, actor: uuid.UUID
) -> dict[str, Any]:
    await use_system(session)
    if await session.get(Tenant, tenant_id) is None:
        raise NotFoundError("Restaurant not found.")
    if amount <= 0 or not description.strip():
        raise AppError("Give an amount and a description.", code="INVALID_INVOICE", status_code=422)
    inv = await create_invoice(session, tenant_id, amount, description.strip(), kind="manual", actor=actor)
    write_audit(
        session,
        action="saas_invoice.created",
        entity="saas_invoice",
        entity_id=inv.id,
        tenant_id=tenant_id,
        actor_user_id=actor,
        diff={"amount": str(amount)},
    )
    await session.commit()
    return next(r for r in await list_invoices(session, tenant_id, None) if r["id"] == inv.id)


async def pay_online(session: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> dict[str, Any]:
    """The restaurant owner pays a WaitLess invoice through the gateway (webhook confirms)."""
    await use_system(session)
    inv = (
        await session.execute(
            select(SaasInvoice).where(SaasInvoice.id == invoice_id, SaasInvoice.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if inv is None:
        raise NotFoundError("Invoice not found.")
    if inv.status != "due":
        raise ConflictError(f"This invoice is {inv.status}.", code="INVOICE_CLOSED")
    gateway = get_gateway()
    order = await gateway.create_order(inv.total, inv.currency, inv.number, {"saas_invoice": str(inv.id)})
    session.add(
        SaasPayment(
            invoice_id=inv.id,
            tenant_id=tenant_id,
            amount=inv.total,
            method="gateway",
            status="pending",
            provider=gateway.name,
            provider_order_id=order.order_id,
        )
    )
    await session.commit()
    return {
        "provider": gateway.name,
        "order_id": order.order_id,
        "amount": str(inv.total),
        "currency": inv.currency,
        "checkout": order.checkout,
    }


async def process_payment_event(session: AsyncSession, provider: str, event: PaymentEvent) -> str | None:
    await use_system(session)
    p = (
        await session.execute(
            select(SaasPayment)
            .where(SaasPayment.provider == provider, SaasPayment.provider_order_id == event.order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if p is None:
        return None
    if p.status != "pending":
        return "already_processed"
    inv = (
        await session.execute(select(SaasInvoice).where(SaasInvoice.id == p.invoice_id).with_for_update())
    ).scalar_one()
    if event.type == "payment.failed" or event.amount != p.amount:
        p.status = "failed"
        await session.commit()
        return "failed"
    p.status, p.provider_payment_id = "captured", event.payment_id
    if inv.status == "due":
        await _mark_paid(session, inv)
        result = "paid"
    else:
        await get_gateway(provider).refund(event.order_id, event.payment_id, p.amount)
        result = "refunded_overpayment"
    write_audit(
        session,
        action=f"saas_invoice.online_{result}",
        entity="saas_invoice",
        entity_id=inv.id,
        tenant_id=inv.tenant_id,
    )
    await session.commit()
    return result


async def mock_pay(session: AsyncSession, tenant_id: uuid.UUID, order_id: str, success: bool) -> str:
    from app.integrations.payments.gateway import MockGateway

    await use_system(session)
    p = (
        await session.execute(
            select(SaasPayment).where(
                SaasPayment.provider == "mock",
                SaasPayment.provider_order_id == order_id,
                SaasPayment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Payment not found.")
    raw, sig = MockGateway.build_event(order_id, p.amount, success)
    return await process_payment_event(session, "mock", MockGateway().parse_webhook(raw, sig)) or "unknown_order"


# ---------- overview & usage ----------


async def overview(session: AsyncSession) -> dict[str, Any]:
    await use_system(session)
    by_status = dict(
        (await session.execute(select(Tenant.status, func.count()).group_by(Tenant.status))).tuples().all()
    )
    branches = (await session.execute(select(func.count()).select_from(Branch))).scalar_one()
    customers = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(~User.is_super_admin, ~select(Membership.id).where(Membership.user_id == User.id).exists())
        )
    ).scalar_one()
    orders = (
        await session.execute(select(func.count()).select_from(Order).where(Order.status != "cancelled"))
    ).scalar_one()
    reservations = (await session.execute(select(func.count()).select_from(Reservation))).scalar_one()
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue_all, revenue_month = (
        await session.execute(
            select(
                func.coalesce(func.sum(SaasPayment.amount), 0),
                func.coalesce(func.sum(SaasPayment.amount).filter(SaasPayment.created_at >= month_start), 0),
            ).where(SaasPayment.status == "captured")
        )
    ).one()
    outstanding = (
        await session.execute(select(func.coalesce(func.sum(SaasInvoice.total), 0)).where(SaasInvoice.status == "due"))
    ).scalar_one()
    live = list(
        (
            await session.execute(
                select(Subscription, Plan)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
            )
        ).tuples()
    )
    mrr = sum(
        (
            p.price_monthly if s.billing_cycle == "monthly" else p.price_yearly / 12
            for s, p in live
            if s.status == "active"
        ),
        Decimal(0),
    )
    by_plan: dict[str, int] = {}
    for _s, p in live:
        by_plan[p.name] = by_plan.get(p.name, 0) + 1
    sub_status = dict(
        (
            await session.execute(
                select(Subscription.status, func.count())
                .where(Subscription.status.in_(("trialing", "active", "past_due")))
                .group_by(Subscription.status)
            )
        )
        .tuples()
        .all()
    )
    expired_30 = (
        await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == "expired", Subscription.updated_at >= _now() - timedelta(days=30))
        )
    ).scalar_one()
    restaurant_revenue = (
        await session.execute(
            select(func.coalesce(func.sum(Bill.grand_total - Bill.refunded_total), 0)).where(
                Bill.status == "paid", Bill.paid_at >= month_start
            )
        )
    ).scalar_one()
    from app.models.support import SupportTicket

    open_tickets = (
        await session.execute(
            select(func.count()).select_from(SupportTicket).where(SupportTicket.status.in_(("open", "in_progress")))
        )
    ).scalar_one()
    return {
        "restaurants_total": sum(by_status.values()),
        "restaurants_by_status": {
            k: by_status.get(k, 0) for k in ("pending", "active", "suspended", "deactivated", "rejected")
        },
        "branches": branches,
        "customers": customers,
        "orders": orders,
        "reservations": reservations,
        "saas_revenue_total": str(_money(Decimal(revenue_all))),
        "saas_revenue_month": str(_money(Decimal(revenue_month))),
        "saas_outstanding": str(_money(Decimal(outstanding))),
        "mrr": str(_money(mrr)),
        "subscriptions_by_status": {k: sub_status.get(k, 0) for k in ("trialing", "active", "past_due")},
        "subscriptions_expired_30d": expired_30,
        "subscriptions_by_plan": by_plan,
        "restaurant_sales_month": str(_money(Decimal(restaurant_revenue))),
        "open_tickets": open_tickets,
    }


async def usage(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Usage vs plan limits — for Super Admin and the restaurant's own Settings page."""
    from app.services.access import live_subscription, tenant_features

    await use_system(session)
    if await session.get(Tenant, tenant_id) is None:
        raise NotFoundError("Restaurant not found.")
    live = await live_subscription(session, tenant_id)
    feats = await tenant_features(session, live[1].id if live else None)
    branches = (
        await session.execute(
            select(func.count()).select_from(Branch).where(Branch.tenant_id == tenant_id, Branch.is_active)
        )
    ).scalar_one()
    staff = (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.status == "active")
        )
    ).scalar_one()
    per_branch = (
        (
            await session.execute(
                select(func.count())
                .where(RestaurantTable.tenant_id == tenant_id, RestaurantTable.is_active)
                .group_by(RestaurantTable.branch_id)
            )
        )
        .scalars()
        .all()
    )
    tables_max = max(per_branch or [0])
    since = _now() - timedelta(days=30)
    orders_30 = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.tenant_id == tenant_id, Order.placed_at >= since, Order.status != "cancelled")
        )
    ).scalar_one()
    sales_30 = (
        await session.execute(
            select(func.coalesce(func.sum(Bill.grand_total - Bill.refunded_total), 0)).where(
                Bill.tenant_id == tenant_id, Bill.status == "paid", Bill.paid_at >= since
            )
        )
    ).scalar_one()
    reservations_30 = (
        await session.execute(
            select(func.count())
            .select_from(Reservation)
            .where(Reservation.tenant_id == tenant_id, Reservation.created_at >= since)
        )
    ).scalar_one()

    def lim(key: str) -> int | None:
        f = feats.get(key)
        return f.limit if f else None

    return {
        "plan": {"code": live[1].code, "name": live[1].name} if live else None,
        "subscription": await subscription_row(session, live[0]) if live else None,
        "limits": [
            {"key": "max_branches", "label": "Branches", "used": branches, "limit": lim("max_branches")},
            {"key": "max_staff", "label": "Employees", "used": staff, "limit": lim("max_staff")},
            {
                "key": "max_tables_per_branch",
                "label": "Tables (busiest branch)",
                "used": tables_max,
                "limit": lim("max_tables_per_branch"),
            },
        ],
        "features": [
            {"key": f["key"], "label": f["label"], "enabled": bool(feats.get(f["key"]) and feats[f["key"]].enabled)}
            for f in FEATURE_CATALOG
            if f["kind"] == "feature"
        ],
        "last_30_days": {"orders": orders_30, "sales": str(_money(Decimal(sales_30))), "reservations": reservations_30},
    }

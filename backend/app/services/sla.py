"""15-minute serving promise & automatic discounts (PRD §14, decisions D11–D15, D71–D76).

Timer start (server UTC, stored once):
- walk_in / staff / booking (free booking, guests already seated): when the kitchen accepts.
- paid_preorder: when staff press Confirm Arrival (`staff_confirmed_at`), never at order time.

Discount (D14): for elapsed > serving_minutes,
    pct = min(max_pct, initial_pct + (ceil((elapsed − serving) / interval) − 1) × increment_pct)
With the defaults (15, 2, 5, 2, cap 20) that is the PRD table: 15:00 → 0 %, 15:01 → 2 %, 20:00 → 2 %,
20:01 → 4 % … The policy is copied onto the order when its timer starts; later edits never change it.

Served → the discount freezes. Cancelled → the timer stops and no discount applies.
The worker wakes each running timer at its next boundary (15, 20, 25 … min), stores the discount
and pushes `orders.changed`; between boundaries clients count down locally.
"""

import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.models.orders import Order
from app.models.sla import DiscountPolicy, OrderDiscount, OrderSla
from app.schemas.sla import ALL_ORDER_TYPES, DiscountPolicyIn, DiscountPolicyOut, PromiseOut, SlaOut
from app.services.access import TenantContext
from app.services.audit import write_audit

CENT = Decimal("0.01")
DEFAULT_POLICY: dict[str, Any] = {
    "is_active": True,
    "serving_minutes": 15,
    "initial_pct": "2.00",
    "interval_minutes": 5,
    "increment_pct": "2.00",
    "max_pct": "20.00",
    "eligible_order_types": list(ALL_ORDER_TYPES),
    "base": "food_subtotal",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- the formula (pure) ----------


def discount_pct(elapsed_seconds: float, policy: Mapping[str, Any]) -> Decimal:
    """Discount for an order that has waited `elapsed_seconds` since its timer started."""
    over = Decimal(str(elapsed_seconds)) - Decimal(int(policy["serving_minutes"]) * 60)
    if over <= 0:
        return Decimal("0.00")
    steps = math.ceil(over / Decimal(int(policy["interval_minutes"]) * 60))
    pct = Decimal(str(policy["initial_pct"])) + (steps - 1) * Decimal(str(policy["increment_pct"]))
    return min(Decimal(str(policy["max_pct"])), pct).quantize(CENT)


def next_boundary(started_at: datetime, now: datetime, policy: Mapping[str, Any]) -> datetime | None:
    """The boundary at or after `now` (15, 20, 25 … min after the start); the discount steps up just after it.
    None once the cap is reached. The worker handles a boundary once the clock is strictly past it."""
    if discount_pct((now - started_at).total_seconds(), policy) >= Decimal(str(policy["max_pct"])):
        return None
    serving = timedelta(minutes=int(policy["serving_minutes"]))
    interval = timedelta(minutes=int(policy["interval_minutes"]))
    first = started_at + serving
    if now <= first:
        return first
    return first + interval * math.ceil((now - first) / interval)


def apply_discount(subtotal: Decimal, tax_total: Decimal, pct: Decimal, base: str) -> tuple[Decimal, Decimal]:
    """(discount amount, total payable). Food-subtotal base (D12): tax is charged on the discounted food."""
    factor = pct / Decimal(100)
    if base == "order_total":
        amount = _money((subtotal + tax_total) * factor)
        return amount, _money(subtotal + tax_total - amount)
    amount = _money(subtotal * factor)
    tax_after = _money(tax_total * (1 - factor))
    return amount, _money(subtotal - amount + tax_after)


# ---------- policy ----------


def _row_to_dict(p: DiscountPolicy) -> dict[str, Any]:
    return {
        "is_active": p.is_active,
        "serving_minutes": p.serving_minutes,
        "initial_pct": str(p.initial_pct),
        "interval_minutes": p.interval_minutes,
        "increment_pct": str(p.increment_pct),
        "max_pct": str(p.max_pct),
        "eligible_order_types": list(p.eligible_order_types),
        "base": p.base,
    }


async def current_policy(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    p = await session.get(DiscountPolicy, tenant_id)
    return _row_to_dict(p) if p else dict(DEFAULT_POLICY)


async def get_policy(session: AsyncSession, ctx: TenantContext) -> DiscountPolicyOut:
    p = await session.get(DiscountPolicy, ctx.tenant_id)
    data = _row_to_dict(p) if p else dict(DEFAULT_POLICY)
    return DiscountPolicyOut(**data, is_default=p is None, updated_at=p.updated_at if p else None)


async def save_policy(session: AsyncSession, ctx: TenantContext, data: DiscountPolicyIn) -> DiscountPolicyOut:
    p = await session.get(DiscountPolicy, ctx.tenant_id)
    before = _row_to_dict(p) if p else dict(DEFAULT_POLICY)
    if p is None:
        p = DiscountPolicy(tenant_id=ctx.tenant_id)
        session.add(p)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    p.updated_by = ctx.user_id
    await session.flush()
    write_audit(
        session,
        action="discount_policy.updated",
        entity="discount_policy",
        entity_id=ctx.tenant_id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"before": before, "after": _row_to_dict(p)},
    )
    await session.commit()
    await session.refresh(p)
    return DiscountPolicyOut(**_row_to_dict(p), is_default=False, updated_at=p.updated_at)


def promise_out(policy: Mapping[str, Any]) -> PromiseOut:
    return PromiseOut(
        is_active=bool(policy["is_active"]),
        serving_minutes=int(policy["serving_minutes"]),
        initial_pct=Decimal(str(policy["initial_pct"])),
        interval_minutes=int(policy["interval_minutes"]),
        increment_pct=Decimal(str(policy["increment_pct"])),
        max_pct=Decimal(str(policy["max_pct"])),
    )


# ---------- timers ----------


async def start(session: AsyncSession, order: Order, at: datetime, reason: str) -> OrderSla:
    """Start the order's timer once (later calls return the existing timer). Caller commits."""
    existing = await session.get(OrderSla, order.id)
    if existing is not None:
        return existing
    policy = await current_policy(session, order.tenant_id)
    snapshot = {
        **policy,
        "eligible": bool(policy["is_active"]) and order.order_type in policy["eligible_order_types"],
        "order_type": order.order_type,
    }
    sla = OrderSla(
        order_id=order.id,
        tenant_id=order.tenant_id,
        branch_id=order.branch_id,
        sla_started_at=at,
        deadline_at=at + timedelta(minutes=int(policy["serving_minutes"])),
        start_reason=reason,
        policy_snapshot=snapshot,
        status="running",
        current_pct=Decimal("0.00"),
    )
    sla.next_boundary_at = next_boundary(at, _now(), snapshot) if snapshot["eligible"] else None
    session.add(sla)
    await session.flush()
    return sla


async def _store_discount(session: AsyncSession, order: Order, sla: OrderSla, pct: Decimal) -> None:
    amount, _ = apply_discount(order.subtotal, order.tax_total, pct, sla.policy_snapshot["base"])
    row = (
        await session.execute(
            select(OrderDiscount).where(OrderDiscount.order_id == order.id, OrderDiscount.kind == "sla_delay")
        )
    ).scalar_one_or_none()
    if pct <= 0:
        if row is not None:
            await session.delete(row)
        return
    if row is None:
        session.add(
            OrderDiscount(tenant_id=order.tenant_id, order_id=order.id, kind="sla_delay", pct=pct, amount=amount)
        )
    else:
        row.pct, row.amount = pct, amount


def _live_pct(sla: OrderSla, now: datetime) -> Decimal:
    if not sla.policy_snapshot.get("eligible"):
        return Decimal("0.00")
    if sla.status != "running":
        return sla.final_discount_pct or Decimal("0.00")
    return discount_pct((now - sla.sla_started_at).total_seconds(), sla.policy_snapshot)


async def finish(session: AsyncSession, order: Order, status: str, at: datetime) -> OrderSla | None:
    """Served → freeze the discount at `at`. Cancelled → stop, no discount. Caller commits."""
    sla = await session.get(OrderSla, order.id)
    if sla is None or sla.status != "running":
        return sla
    pct = _live_pct(sla, at)  # while still running: the discount earned up to `at`
    sla.status, sla.ended_at, sla.next_boundary_at = status, at, None
    if status == "served":
        sla.current_pct = sla.final_discount_pct = pct
        await _store_discount(session, order, sla, pct)
    else:
        sla.current_pct = sla.final_discount_pct = Decimal("0.00")
        await session.execute(
            delete(OrderDiscount).where(OrderDiscount.order_id == order.id, OrderDiscount.kind == "sla_delay")
        )
    return sla


async def tick(session: AsyncSession, now: datetime | None = None) -> list[Order]:
    """Worker: advance every running timer whose next boundary has passed. Returns the changed orders."""
    now = now or _now()
    await use_system(session)
    rows = (
        (
            await session.execute(
                select(OrderSla)
                .where(
                    OrderSla.status == "running",
                    OrderSla.next_boundary_at.is_not(None),
                    OrderSla.next_boundary_at < now,
                )
                .order_by(OrderSla.next_boundary_at)
                .limit(200)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    changed: list[Order] = []
    for sla in rows:
        order = await session.get(Order, sla.order_id)
        if order is None:  # pragma: no cover - cascade delete
            continue
        pct = _live_pct(sla, now)
        sla.next_boundary_at = next_boundary(sla.sla_started_at, now, sla.policy_snapshot)
        if pct != sla.current_pct:
            sla.current_pct = pct
            await _store_discount(session, order, sla, pct)
        changed.append(order)  # also the deadline itself (0 % → "running late") is worth a push
    await session.commit()
    return changed


async def load(session: AsyncSession, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, OrderSla]:
    if not order_ids:
        return {}
    return {
        s.order_id: s
        for s in (await session.execute(select(OrderSla).where(OrderSla.order_id.in_(order_ids)))).scalars()
    }


def sla_out(sla: OrderSla, order: Order, now: datetime) -> tuple[SlaOut, Decimal, Decimal]:
    """(timer view, discount amount, payable total) for one order."""
    snap = sla.policy_snapshot
    pct = Decimal("0.00") if order.status == "cancelled" else _live_pct(sla, now)
    amount, payable = apply_discount(order.subtotal, order.tax_total, pct, snap["base"])
    view = SlaOut(
        started_at=sla.sla_started_at,
        deadline_at=sla.deadline_at,
        start_reason=sla.start_reason,
        status=sla.status,  # type: ignore[arg-type]
        ended_at=sla.ended_at,
        eligible=bool(snap.get("eligible")),
        discount_pct=pct,
        discount_amount=amount,
        next_boundary_at=next_boundary(sla.sla_started_at, now, snap)
        if sla.status == "running" and snap.get("eligible")
        else None,
        serving_minutes=int(snap["serving_minutes"]),
        initial_pct=Decimal(str(snap["initial_pct"])),
        interval_minutes=int(snap["interval_minutes"]),
        increment_pct=Decimal(str(snap["increment_pct"])),
        max_pct=Decimal(str(snap["max_pct"])),
        base=snap["base"],
    )
    return view, amount, payable

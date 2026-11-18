"""Restaurant billing & POS (PRD §9; decisions D10, D16, D82–D90).

Bills follow the table visit (session):
- `sync` puts every order line of the visit on a bill (one bill by default; never twice — unique key),
  drops cancelled lines from bills that are still open, and recalculates them (`bill_calc`).
- Split moves chosen lines to a new bill; merge moves another table's open bill into this one.
- The first payment **locks** a bill. New orders after that go to a new bill.
- Paid in full → an immutable invoice (INV-000001). Refunds → credit notes (CN-000001); nothing is edited.
- Manual discounts and refunds by non-owners are capped by the owner's manager limits.
- Guests press **Finish** (no more orders) and can pay online; the verified gateway webhook records it.
"""

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system, use_tenant
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.integrations.payments.gateway import PaymentEvent, get_gateway
from app.models import Branch, Tenant, User
from app.models.billing import Bill, BillItem, BillPayment, BillRefund, Invoice
from app.models.booking import Reservation, ReservationPayment
from app.models.orders import Order, OrderItem
from app.models.sla import OrderSla
from app.models.tables import RestaurantTable, TableAssignment, TableSession
from app.schemas.billing import (
    ActiveTable,
    BillingSettings,
    BillLineOut,
    BillOut,
    DiscountIn,
    InvoiceOut,
    InvoiceRef,
    OnlinePaymentOut,
    PaymentIn,
    PaymentOut,
    RefundIn,
    RefundOut,
    SessionBillsOut,
)
from app.services import bill_calc
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.sla import _live_pct
from app.websocket.bus import branch_staff_room, emit

log = logging.getLogger(__name__)
ZERO = Decimal("0.00")
ACTIVE = ("open", "paid")


def _now() -> datetime:
    return datetime.now(UTC)


def _money(v: Decimal) -> Decimal:
    return bill_calc.money(v)


# ---------- settings ----------


def settings_of(tenant: Tenant) -> BillingSettings:
    raw: dict[str, Any] = dict((tenant.settings or {}).get("billing") or {})
    if "service_charge_pct" not in raw and (tenant.settings or {}).get("service_charge_pct") is not None:
        raw["service_charge_pct"] = tenant.settings["service_charge_pct"]
    raw.setdefault("legal_name", tenant.name)
    return BillingSettings(**raw)


async def get_settings(session: AsyncSession, tenant_id: uuid.UUID) -> BillingSettings:
    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    return settings_of(tenant)


async def save_settings(session: AsyncSession, ctx: TenantContext, data: BillingSettings) -> BillingSettings:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    before = settings_of(tenant).model_dump(mode="json")
    settings = dict(tenant.settings or {})
    settings["billing"] = data.model_dump(mode="json")
    settings["service_charge_pct"] = str(data.service_charge_pct)
    tenant.settings = settings
    write_audit(
        session,
        action="billing_settings.updated",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=ctx.user_id,
        diff={"before": before, "after": settings["billing"]},
    )
    await session.commit()
    return data


def _limits(tenant: Tenant) -> dict[str, Decimal]:
    raw = (tenant.settings or {}).get("manager_limits") or {}
    return {
        "manual_discount_pct": Decimal(str(raw.get("manual_discount_pct", "10.00"))),
        "refund_amount": Decimal(str(raw.get("refund_amount", "2000.00"))),
    }


# ---------- helpers ----------


async def _labels(session: AsyncSession, session_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = defaultdict(list)
    if not session_ids:
        return out
    for sid, label in (
        await session.execute(
            select(TableAssignment.table_session_id, RestaurantTable.label)
            .join(RestaurantTable, RestaurantTable.id == TableAssignment.table_id)
            .where(TableAssignment.table_session_id.in_(session_ids))
            .order_by(TableAssignment.released_at.is_(None).desc(), TableAssignment.assigned_at.desc())
        )
    ).tuples():
        if label not in out[sid]:
            out[sid].append(label)
    return out


async def _staff_session(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID, perm: str) -> TableSession:
    s = (
        await session.execute(select(TableSession).where(TableSession.id == session_id).with_for_update())
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError("Table session not found.")
    if not ctx.can_act_in_branch(perm, s.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return s


async def _staff_bill(session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID, perm: str) -> Bill:
    b = (await session.execute(select(Bill).where(Bill.id == bill_id).with_for_update())).scalar_one_or_none()
    if b is None:
        raise NotFoundError("Bill not found.")
    if not ctx.can_act_in_branch(perm, b.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return b


def _editable(b: Bill) -> None:
    if b.status != "open":
        raise ConflictError(f"This bill is {b.status}.", code="BILL_CLOSED")
    if b.locked:
        raise ConflictError("A payment was already taken on this bill, so it can no longer change.", code="BILL_LOCKED")


async def _changed(tenant_id: uuid.UUID, branch_id: uuid.UUID, session_ids: set[uuid.UUID]) -> None:
    from app.services.orders import table_session_room  # local: orders imports billing lazily too

    data = {"branch_id": str(branch_id)}
    await emit("bills.changed", data, branch_staff_room(tenant_id, branch_id))
    for sid in session_ids:
        await emit("bills.changed", {**data, "session_id": str(sid)}, table_session_room(tenant_id, sid))


# ---------- building & recalculating bills ----------


async def _bills_of(session: AsyncSession, s: TableSession) -> list[Bill]:
    return list(
        (
            await session.execute(
                select(Bill).where(Bill.table_session_id == s.id).order_by(Bill.sequence).with_for_update()
            )
        ).scalars()
    )


async def _new_bill(session: AsyncSession, s: TableSession, actor: uuid.UUID | None) -> Bill:
    seq = (
        await session.execute(select(func.coalesce(func.max(Bill.sequence), 0)).where(Bill.table_session_id == s.id))
    ).scalar_one() + 1
    b = Bill(tenant_id=s.tenant_id, branch_id=s.branch_id, table_session_id=s.id, sequence=seq, created_by=actor)
    session.add(b)
    await session.flush()
    return b


async def sync(session: AsyncSession, s: TableSession, actor: uuid.UUID | None) -> list[Bill]:
    """Every live order line of the visit on a bill; open bills recalculated (caller commits)."""
    orders = {o.id: o for o in (await session.execute(select(Order).where(Order.table_session_id == s.id))).scalars()}
    items = (
        list(
            (
                await session.execute(
                    select(OrderItem).where(OrderItem.order_id.in_(list(orders))).order_by(OrderItem.sort_order)
                )
            ).scalars()
        )
        if orders
        else []
    )
    billed = (
        {
            bi.order_item_id: bi
            for bi in (
                await session.execute(select(BillItem).where(BillItem.order_item_id.in_([i.id for i in items])))
            ).scalars()
        }
        if items
        else {}
    )
    bills = await _bills_of(session, s)
    by_id = {b.id: b for b in bills}

    # Cancelled orders leave open bills (a locked bill keeps its lines; refunds correct those).
    touched: set[uuid.UUID] = set()
    for it in items:
        bi = billed.get(it.id)
        if bi is None or orders[it.order_id].status != "cancelled":
            continue
        holder = by_id.get(bi.bill_id) or await session.get(Bill, bi.bill_id)
        if holder is not None and holder.status == "open" and not holder.locked:
            await session.delete(bi)
            touched.add(holder.id)
    await session.flush()

    # New lines go to the first open, unlocked bill of the visit (or the bill this visit was merged into).
    fresh = [it for it in items if it.id not in billed and orders[it.order_id].status != "cancelled"]
    if fresh:
        target = next((b for b in bills if b.status == "open" and not b.locked), None)
        if target is None:
            merged = next((b for b in bills if b.status == "void" and b.merged_into_id), None)
            if merged:
                host = await session.get(Bill, merged.merged_into_id)
                if host is not None and host.status == "open" and not host.locked:
                    target = host
        if target is None:
            target = await _new_bill(session, s, actor)
            bills.append(target)
        for it in fresh:
            o = orders[it.order_id]
            extras = ", ".join(a["name"] for a in it.addons)
            name = it.name + (f" ({it.variant_name})" if it.variant_name else "") + (f" + {extras}" if extras else "")
            session.add(
                BillItem(
                    tenant_id=s.tenant_id,
                    bill_id=target.id,
                    order_id=o.id,
                    order_item_id=it.id,
                    order_number=o.number,
                    name=name[:200],
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    line_total=it.line_total,
                    tax_pct=it.tax_pct,
                    sort_order=o.sequence * 100 + it.sort_order,
                )
            )
        touched.add(target.id)
        await session.flush()

    settings = await get_settings(session, s.tenant_id)
    for b in bills:
        if b.status == "open" and not b.locked:
            await recompute(session, b, settings)
    for bid in touched:
        if bid not in {b.id for b in bills}:
            other = await session.get(Bill, bid)
            if other is not None and other.status == "open" and not other.locked:
                await recompute(session, other, settings)
    return [b for b in await _bills_of(session, s)]


async def _credit_available(session: AsyncSession, b: Bill, session_ids: set[uuid.UUID]) -> Decimal:
    """Paid booking fees of the visits on this bill, minus what other bills already credited (D16)."""
    if not session_ids:
        return ZERO
    fee = (
        await session.execute(
            select(func.coalesce(func.sum(ReservationPayment.amount - ReservationPayment.refunded_amount), 0))
            .join(Reservation, Reservation.id == ReservationPayment.reservation_id)
            .where(
                Reservation.table_session_id.in_(session_ids),
                Reservation.type == "paid",
                ReservationPayment.status.in_(("captured", "refunded")),
            )
        )
    ).scalar_one()
    used = (
        await session.execute(
            select(func.coalesce(func.sum(Bill.booking_credit), 0)).where(
                Bill.id != b.id,
                Bill.status.in_(ACTIVE),
                Bill.id.in_(
                    select(BillItem.bill_id)
                    .join(Order, Order.id == BillItem.order_id)
                    .where(Order.table_session_id.in_(session_ids))
                ),
            )
        )
    ).scalar_one()
    return max(Decimal(fee) - Decimal(used), ZERO)


async def recompute(session: AsyncSession, b: Bill, settings: BillingSettings) -> None:
    lines = list(
        (
            await session.execute(select(BillItem).where(BillItem.bill_id == b.id).order_by(BillItem.sort_order))
        ).scalars()
    )
    order_ids = {ln.order_id for ln in lines}
    orders = (
        {o.id: o for o in (await session.execute(select(Order).where(Order.id.in_(order_ids)))).scalars()}
        if order_ids
        else {}
    )
    all_items: dict[uuid.UUID, list[OrderItem]] = defaultdict(list)
    if order_ids:
        for it in (await session.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids)))).scalars():
            all_items[it.order_id].append(it)
    slas = (
        {
            x.order_id: x
            for x in (await session.execute(select(OrderSla).where(OrderSla.order_id.in_(order_ids)))).scalars()
        }
        if order_ids
        else {}
    )
    now = _now()
    infos: dict[uuid.UUID, bill_calc.OrderInfo] = {}
    for oid in order_ids:
        sla = slas.get(oid)
        pct = _live_pct(sla, now) if sla is not None else ZERO
        infos[oid] = bill_calc.OrderInfo(
            pct=pct,
            base=sla.policy_snapshot.get("base", "food_subtotal") if sla is not None else "food_subtotal",
            line_totals={it.id: it.line_total for it in all_items[oid]},
            tax_pcts={it.id: it.tax_pct for it in all_items[oid]},
        )
    credit = await _credit_available(session, b, {o.table_session_id for o in orders.values() if o.table_session_id})
    r = bill_calc.compute(
        [bill_calc.LineIn(ln.order_item_id, ln.order_id, ln.line_total, ln.tax_pct) for ln in lines],
        infos,
        bill_calc.Settings(
            service_charge_pct=settings.service_charge_pct,
            service_charge_tax_pct=settings.service_charge_tax_pct,
            tax_split=settings.tax_split,
            round_off=settings.round_off,
        ),
        manual_pct=b.manual_discount_pct,
        manual_amount=b.manual_discount if b.manual_discount_pct is None else None,
        credit_available=credit,
    )
    for ln, lo in zip(lines, r.lines, strict=True):
        ln.sla_pct, ln.sla_discount, ln.manual_discount, ln.taxable = (
            lo.sla_pct,
            lo.sla_discount,
            lo.manual_discount,
            lo.taxable,
        )
    b.subtotal, b.sla_discount, b.sla_discount_after_tax = r.subtotal, r.sla_discount, r.sla_discount_after_tax
    b.manual_discount, b.taxable = r.manual_discount, r.taxable
    b.service_charge_pct, b.service_charge, b.tax_total = settings.service_charge_pct, r.service_charge, r.tax_total
    b.booking_credit, b.round_off, b.grand_total = r.booking_credit, r.round_off, r.grand_total
    b.breakdown = {"taxes": r.taxes}
    b.settings_snapshot = settings.model_dump(mode="json")
    if not lines and b.manual_discount_pct is None:
        b.manual_discount = ZERO
    await session.flush()


# ---------- output ----------


async def bills_out(session: AsyncSession, bills: list[Bill]) -> list[BillOut]:
    if not bills:
        return []
    ids = [b.id for b in bills]
    sids = {b.table_session_id for b in bills}
    sessions = {
        s.id: s for s in (await session.execute(select(TableSession).where(TableSession.id.in_(sids)))).scalars()
    }
    labels = await _labels(session, sids)
    lines: dict[uuid.UUID, list[BillItem]] = defaultdict(list)
    for li in (
        await session.execute(select(BillItem).where(BillItem.bill_id.in_(ids)).order_by(BillItem.sort_order))
    ).scalars():
        lines[li.bill_id].append(li)
    oids = {li.order_id for ls in lines.values() for li in ls}
    order_names = (
        dict((await session.execute(select(Order.id, Order.ordered_by_name).where(Order.id.in_(oids)))).tuples().all())
        if oids
        else {}
    )
    unserved: dict[uuid.UUID, int] = defaultdict(int)
    if oids:
        open_orders = {
            o.id
            for o in (
                await session.execute(
                    select(Order).where(Order.id.in_(oids), Order.status.not_in(("served", "cancelled")))
                )
            ).scalars()
        }
        for bid, ls in lines.items():
            unserved[bid] = len({li.order_id for li in ls if li.order_id in open_orders})
    pays: dict[uuid.UUID, list[BillPayment]] = defaultdict(list)
    for p in (
        await session.execute(select(BillPayment).where(BillPayment.bill_id.in_(ids)).order_by(BillPayment.created_at))
    ).scalars():
        pays[p.bill_id].append(p)
    uids = {p.received_by for ps in pays.values() for p in ps if p.received_by}
    names = (
        {u.id: u.full_name for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars()}
        if uids
        else {}
    )
    refunds: dict[uuid.UUID, list[BillRefund]] = defaultdict(list)
    for rf in (
        await session.execute(select(BillRefund).where(BillRefund.bill_id.in_(ids)).order_by(BillRefund.created_at))
    ).scalars():
        refunds[rf.bill_id].append(rf)
    invs: dict[uuid.UUID, list[Invoice]] = defaultdict(list)
    for inv in (
        await session.execute(select(Invoice).where(Invoice.bill_id.in_(ids)).order_by(Invoice.issued_at))
    ).scalars():
        invs[inv.bill_id].append(inv)
    per_session: dict[uuid.UUID, int] = defaultdict(int)
    for b in (
        await session.execute(
            select(Bill.table_session_id).where(Bill.table_session_id.in_(sids), Bill.status.in_(ACTIVE))
        )
    ).scalars():
        per_session[b] += 1
    out = []
    for b in bills:
        s = sessions[b.table_session_id]
        st = BillingSettings(**b.settings_snapshot) if b.settings_snapshot else BillingSettings()
        out.append(
            BillOut(
                id=b.id,
                branch_id=b.branch_id,
                table_session_id=b.table_session_id,
                session_code=s.public_code,
                table_labels=labels.get(s.id, []),
                guest_name=s.guest_name,
                sequence=b.sequence,
                label="Bill" if per_session[s.id] <= 1 and b.sequence == 1 else f"Bill {b.sequence}",
                status=b.status,  # type: ignore[arg-type]
                locked=b.locked,
                merged_into_id=b.merged_into_id,
                lines=[
                    BillLineOut.model_validate(li).model_copy(update={"ordered_by_name": order_names.get(li.order_id)})
                    for li in lines[b.id]
                ],
                subtotal=b.subtotal,
                sla_discount=b.sla_discount,
                sla_discount_after_tax=b.sla_discount_after_tax,
                manual_discount=b.manual_discount,
                manual_discount_pct=b.manual_discount_pct,
                manual_discount_reason=b.manual_discount_reason,
                taxable=b.taxable,
                service_charge_pct=b.service_charge_pct,
                service_charge=b.service_charge,
                tax_total=b.tax_total,
                taxes=(b.breakdown or {}).get("taxes", []),
                booking_credit=b.booking_credit,
                round_off=b.round_off,
                grand_total=b.grand_total,
                paid_total=b.paid_total,
                refunded_total=b.refunded_total,
                due=max(b.grand_total - b.paid_total, ZERO) if b.status == "open" else ZERO,
                unserved_orders=unserved[b.id],
                payments=[
                    PaymentOut.model_validate(p).model_copy(
                        update={"received_by_name": names.get(p.received_by) if p.received_by else None}
                    )
                    for p in pays[b.id]
                ],
                refunds=[RefundOut.model_validate(rf) for rf in refunds[b.id]],
                invoices=[InvoiceRef.model_validate(i) for i in invs[b.id]],
                methods=st.methods,
                other_method_label=st.other_method_label,
                created_at=b.created_at,
                paid_at=b.paid_at,
            )
        )
    return out


async def session_bills_out(session: AsyncSession, s: TableSession) -> SessionBillsOut:
    bills = [b for b in await _bills_of(session, s) if b.status != "void"]
    out = await bills_out(session, bills)
    labels = await _labels(session, {s.id})
    due = sum((b.due for b in out), ZERO)
    tenant = await session.get(Tenant, s.tenant_id)
    st = settings_of(tenant) if tenant else BillingSettings()
    return SessionBillsOut(
        restaurant_name=tenant.name if tenant else "",
        upi_id=st.upi_id,
        upi_payee_name=st.upi_payee_name or (tenant.name if tenant else ""),
        session_id=s.id,
        session_code=s.public_code,
        session_status=s.status,
        branch_id=s.branch_id,
        table_labels=labels.get(s.id, []),
        guest_name=s.guest_name,
        party_size=s.party_size,
        opened_at=s.opened_at,
        bills=out,
        total_due=due,
        can_close=s.status != "closed" and all(b.status == "paid" or (not b.lines) for b in out),
    )


# ---------- staff: bills ----------


async def session_bills(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID) -> SessionBillsOut:
    """Generate / refresh the visit's bills."""
    s = await _staff_session(session, ctx, session_id, "billing.operate")
    if s.status != "closed":
        await sync(session, s, ctx.user_id)
        await session.commit()
    return await session_bills_out(session, s)


async def active_tables(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[ActiveTable]:
    from app.services.tables import _branch

    await _branch(session, ctx, branch_id, "billing.operate")
    sessions = list(
        (
            await session.execute(
                select(TableSession)
                .where(TableSession.branch_id == branch_id, TableSession.status != "closed")
                .order_by(TableSession.opened_at)
            )
        ).scalars()
    )
    labels = await _labels(session, {s.id for s in sessions})
    out = []
    for s in sessions:
        orders = list(
            (
                await session.execute(select(Order).where(Order.table_session_id == s.id, Order.status != "cancelled"))
            ).scalars()
        )
        bills = [
            b
            for b in (
                await session.execute(select(Bill).where(Bill.table_session_id == s.id, Bill.status.in_(ACTIVE)))
            ).scalars()
        ]
        running = sum((o.total for o in orders), ZERO)
        total = sum((b.grand_total for b in bills), ZERO) if bills else running
        due = (
            sum((max(b.grand_total - b.paid_total, ZERO) for b in bills if b.status == "open"), ZERO)
            if bills
            else running
        )
        out.append(
            ActiveTable(
                session_id=s.id,
                session_code=s.public_code,
                session_status=s.status,
                table_labels=labels.get(s.id, []),
                guest_name=s.guest_name,
                party_size=s.party_size,
                opened_at=s.opened_at,
                orders=len(orders),
                total=total,
                due=due,
                bills=len(bills),
                paid=bool(bills) and all(b.status == "paid" for b in bills),
            )
        )
    return out


async def get_bill(session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID) -> BillOut:
    b = await _staff_bill(session, ctx, bill_id, "billing.operate")
    if b.status == "open" and not b.locked:
        await recompute(session, b, await get_settings(session, b.tenant_id))
        await session.commit()
    return (await bills_out(session, [b]))[0]


async def list_bills(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, day: str | None, status: str | None
) -> list[BillOut]:
    from app.services.tables import _branch

    branch = await _branch(session, ctx, branch_id, "billing.operate")
    tz = ZoneInfo(branch.timezone)
    d = datetime.fromisoformat(day).date() if day else _now().astimezone(tz).date()
    start = datetime.combine(d, datetime.min.time(), tz)
    stmt = select(Bill).where(Bill.branch_id == branch_id, Bill.status != "void")
    if status:
        stmt = stmt.where(Bill.status == status)
    else:
        stmt = stmt.where(Bill.created_at >= start, Bill.created_at < start + _day())
    return await bills_out(
        session, list((await session.execute(stmt.order_by(Bill.created_at.desc()).limit(300))).scalars())
    )


def _day():  # type: ignore[no-untyped-def]
    from datetime import timedelta

    return timedelta(days=1)


async def split(
    session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> SessionBillsOut:
    b = await _staff_bill(session, ctx, bill_id, "billing.operate")
    _editable(b)
    lines = list((await session.execute(select(BillItem).where(BillItem.bill_id == b.id))).scalars())
    chosen = [ln for ln in lines if ln.order_item_id in set(item_ids)]
    if len(chosen) != len(set(item_ids)):
        raise AppError("Choose lines from this bill.", code="INVALID_LINES", status_code=422)
    if len(chosen) == len(lines):
        raise AppError("Leave at least one line on this bill.", code="SPLIT_ALL", status_code=422)
    s = await session.get(TableSession, b.table_session_id)
    assert s is not None
    new = await _new_bill(session, s, ctx.user_id)
    for ln in chosen:
        ln.bill_id = new.id
    await session.flush()
    st = await get_settings(session, b.tenant_id)
    await recompute(session, b, st)
    await recompute(session, new, st)
    write_audit(
        session,
        action="bill.split",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"new_bill": str(new.id), "lines": len(chosen)},
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {s.id})
    return await session_bills_out(session, s)


async def merge(session: AsyncSession, ctx: TenantContext, target_id: uuid.UUID, source_id: uuid.UUID) -> BillOut:
    """Another table's (or this table's other) open bill joins this one; the source is voided."""
    if target_id == source_id:
        raise AppError("Choose a different bill.", code="SAME_BILL", status_code=422)
    target = await _staff_bill(session, ctx, target_id, "billing.operate")
    source = await _staff_bill(session, ctx, source_id, "billing.operate")
    _editable(target)
    _editable(source)
    if target.branch_id != source.branch_id:
        raise ConflictError("Bills of different branches cannot be merged.", code="OTHER_BRANCH")
    for ln in (await session.execute(select(BillItem).where(BillItem.bill_id == source.id))).scalars():
        ln.bill_id = target.id
    source.status, source.merged_into_id = "void", target.id
    for f in (
        "subtotal",
        "sla_discount",
        "sla_discount_after_tax",
        "manual_discount",
        "taxable",
        "service_charge",
        "tax_total",
        "booking_credit",
        "round_off",
        "grand_total",
    ):
        setattr(source, f, ZERO)
    source.manual_discount_pct = None
    await session.flush()
    await recompute(session, target, await get_settings(session, target.tenant_id))
    write_audit(
        session,
        action="bill.merged",
        entity="bill",
        entity_id=target.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"source": str(source.id)},
    )
    await session.commit()
    await _changed(ctx.tenant_id, target.branch_id, {target.table_session_id, source.table_session_id})
    return (await bills_out(session, [target]))[0]


async def set_discount(session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID, data: DiscountIn) -> BillOut:
    b = await _staff_bill(session, ctx, bill_id, "billing.discount.apply")
    _editable(b)
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    st = await get_settings(session, b.tenant_id)
    await recompute(session, b, st)  # current base
    base = b.subtotal - b.sla_discount
    pct = data.pct or None
    amount = data.amount or None
    if ctx.role_key != "owner" and (pct or amount):
        limit = _limits(tenant)["manual_discount_pct"]
        effective = pct if pct is not None else (amount / base * 100 if base > 0 else Decimal(100))  # type: ignore[operator]
        if effective > limit:
            raise ForbiddenError(
                f"Your limit is {limit.normalize():f}% — ask the owner for a bigger discount.",
                code="DISCOUNT_LIMIT",
                details={"limit_pct": str(limit)},
            )
    if amount is not None and amount > base:
        raise AppError("The discount is more than the food on this bill.", code="DISCOUNT_TOO_HIGH", status_code=422)
    b.manual_discount_pct = pct
    b.manual_discount = _money(amount) if amount is not None else ZERO
    b.manual_discount_reason = data.reason.strip() or None if (pct or amount) else None
    b.manual_discount_by = ctx.user_id if (pct or amount) else None
    await recompute(session, b, st)
    write_audit(
        session,
        action="bill.discount",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"pct": str(pct) if pct else None, "amount": str(b.manual_discount)},
        reason=data.reason or None,
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


async def void_bill(session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID, reason: str) -> BillOut:
    """Write off an unpaid bill (guests walked out, staff meal…) — managers/owners, always audited."""
    b = await _staff_bill(session, ctx, bill_id, "billing.discount.apply")
    _editable(b)
    if not reason.strip():
        raise AppError("A reason is required.", code="REASON_REQUIRED", status_code=422)
    b.status = "void"
    write_audit(
        session,
        action="bill.voided",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"grand_total": str(b.grand_total)},
        reason=reason.strip(),
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


# ---------- payments ----------


async def _paid_check(session: AsyncSession, b: Bill) -> None:
    """Fully paid → paid + invoice (caller commits)."""
    if b.status == "open" and b.paid_total >= b.grand_total:
        b.status, b.paid_at = "paid", _now()
        await _issue(session, b, "invoice", b.grand_total)


async def take_payment(
    session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID, data: PaymentIn, idem: str | None
) -> BillOut:
    key = f"m{ctx.user_id}:{idem.strip()[:60]}" if idem and idem.strip() else None
    if key:
        prior = (
            await session.execute(select(BillPayment).where(BillPayment.idempotency_key == key))
        ).scalar_one_or_none()
        if prior is not None:
            return (await bills_out(session, [await session.get(Bill, prior.bill_id)]))[0]  # type: ignore[list-item]
    b = await _staff_bill(session, ctx, bill_id, "payments.collect")
    if b.status != "open":
        raise ConflictError(f"This bill is {b.status}.", code="BILL_CLOSED")
    st = await get_settings(session, b.tenant_id)
    if data.method not in st.methods:
        raise AppError(
            "This payment method is switched off in billing settings.", code="METHOD_DISABLED", status_code=422
        )
    if not b.locked:
        await recompute(session, b, st)
    due = b.grand_total - b.paid_total
    if due <= 0:
        raise ConflictError("Nothing is due on this bill.", code="NOTHING_DUE")
    if data.amount > due:
        raise ConflictError(f"Only {due} is due.", code="OVERPAYMENT", details={"due": str(due)})
    change = ZERO
    if data.method == "cash" and data.tendered is not None:
        if data.tendered < data.amount:
            raise AppError("The cash handed over is less than the amount.", code="TENDERED_TOO_LOW", status_code=422)
        change = _money(data.tendered - data.amount)
    p = BillPayment(
        tenant_id=b.tenant_id,
        branch_id=b.branch_id,
        bill_id=b.id,
        method=data.method,
        method_label=(data.method_label.strip() or (st.other_method_label if data.method == "other" else ""))[:40],
        amount=data.amount,
        tendered=data.tendered if data.method == "cash" else None,
        change_due=change,
        status="captured",
        reference=data.reference.strip(),
        idempotency_key=key,
        received_by=ctx.user_id,
        captured_at=_now(),
    )
    try:
        async with session.begin_nested():
            session.add(p)
            await session.flush()
    except IntegrityError:
        prior = (await session.execute(select(BillPayment).where(BillPayment.idempotency_key == key))).scalar_one()
        return (await bills_out(session, [await session.get(Bill, prior.bill_id)]))[0]  # type: ignore[list-item]
    b.locked = True
    b.paid_total = _money(b.paid_total + data.amount)
    await _paid_check(session, b)
    write_audit(
        session,
        action="bill.payment",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"method": data.method, "amount": str(data.amount)},
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


async def settle_zero(session: AsyncSession, ctx: TenantContext, bill_id: uuid.UUID) -> BillOut:
    """A bill fully covered by the booking credit / discounts: close it with a ₹0 invoice."""
    b = await _staff_bill(session, ctx, bill_id, "billing.operate")
    if b.status != "open":
        raise ConflictError(f"This bill is {b.status}.", code="BILL_CLOSED")
    if not b.locked:
        await recompute(session, b, await get_settings(session, b.tenant_id))
    if b.grand_total - b.paid_total > 0:
        raise ConflictError("This bill still has money due.", code="BILL_UNPAID")
    b.locked = True
    await _paid_check(session, b)
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


async def refund(
    session: AsyncSession, ctx: TenantContext, payment_id: uuid.UUID, data: RefundIn, idem: str | None
) -> BillOut:
    key = f"m{ctx.user_id}:{idem.strip()[:60]}" if idem and idem.strip() else None
    if key:
        prior = (
            await session.execute(select(BillRefund).where(BillRefund.idempotency_key == key))
        ).scalar_one_or_none()
        if prior is not None:
            return (await bills_out(session, [await session.get(Bill, prior.bill_id)]))[0]  # type: ignore[list-item]
    p = (
        await session.execute(select(BillPayment).where(BillPayment.id == payment_id).with_for_update())
    ).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Payment not found.")
    if not ctx.can_act_in_branch("payments.refund", p.branch_id):
        raise ForbiddenError("You cannot refund payments here.", code="PERMISSION_DENIED")
    if p.status != "captured":
        raise ConflictError("Only received payments can be refunded.", code="NOT_REFUNDABLE")
    left = p.amount - p.refunded_amount
    if data.amount > left:
        raise ConflictError(f"Only {left} of this payment can still be refunded.", code="REFUND_TOO_HIGH")
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    if ctx.role_key != "owner":
        limit = _limits(tenant)["refund_amount"]
        if data.amount > limit:
            raise ForbiddenError(f"Your refund limit is {limit} — ask the owner.", code="REFUND_LIMIT")
    b = (await session.execute(select(Bill).where(Bill.id == p.bill_id).with_for_update())).scalar_one()
    provider_ref = None
    if p.method == "gateway" and p.provider and p.provider_payment_id:
        provider_ref = await get_gateway(p.provider).refund(p.provider_payment_id, data.amount)
    session.add(
        BillRefund(
            tenant_id=p.tenant_id,
            bill_id=b.id,
            payment_id=p.id,
            amount=data.amount,
            reason=data.reason.strip(),
            provider_refund_id=provider_ref,
            idempotency_key=key,
            approved_by=ctx.user_id,
        )
    )
    p.refunded_amount = _money(p.refunded_amount + data.amount)
    b.refunded_total = _money(b.refunded_total + data.amount)
    original = (
        await session.execute(select(Invoice).where(Invoice.bill_id == b.id, Invoice.kind == "invoice"))
    ).scalar_one_or_none()
    if original is not None:
        await _issue(session, b, "credit_note", -data.amount, original=original, reason=data.reason.strip())
    write_audit(
        session,
        action="bill.refund",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"payment": str(p.id), "amount": str(data.amount)},
        reason=data.reason.strip(),
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


async def list_payments(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, day: str | None
) -> list[PaymentOut]:
    from app.services.tables import _branch

    branch = await _branch(session, ctx, branch_id, "payments.collect")
    tz = ZoneInfo(branch.timezone)
    d = datetime.fromisoformat(day).date() if day else _now().astimezone(tz).date()
    start = datetime.combine(d, datetime.min.time(), tz)
    rows = list(
        (
            await session.execute(
                select(BillPayment)
                .where(
                    BillPayment.branch_id == branch_id,
                    BillPayment.created_at >= start,
                    BillPayment.created_at < start + _day(),
                )
                .order_by(BillPayment.created_at.desc())
            )
        ).scalars()
    )
    bills = (
        {b.id: b for b in (await session.execute(select(Bill).where(Bill.id.in_({p.bill_id for p in rows})))).scalars()}
        if rows
        else {}
    )
    labels = await _labels(session, {b.table_session_id for b in bills.values()})
    invs = (
        {
            i.bill_id: i.number
            for i in (
                await session.execute(
                    select(Invoice).where(Invoice.bill_id.in_(list(bills)), Invoice.kind == "invoice")
                )
            ).scalars()
        }
        if bills
        else {}
    )
    uids = {p.received_by for p in rows if p.received_by}
    names = (
        {u.id: u.full_name for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars()}
        if uids
        else {}
    )
    return [
        PaymentOut.model_validate(p).model_copy(
            update={
                "received_by_name": names.get(p.received_by) if p.received_by else None,
                "bill_label": f"Bill {bills[p.bill_id].sequence}",
                "table_labels": labels.get(bills[p.bill_id].table_session_id, []),
                "invoice_number": invs.get(p.bill_id),
            }
        )
        for p in rows
    ]


# ---------- invoices ----------


async def _issue(
    session: AsyncSession, b: Bill, kind: str, total: Decimal, *, original: Invoice | None = None, reason: str = ""
) -> Invoice:
    tenant = await session.get(Tenant, b.tenant_id)
    branch = await session.get(Branch, b.branch_id)
    assert tenant is not None and branch is not None
    st = BillingSettings(**b.settings_snapshot) if b.settings_snapshot else settings_of(tenant)
    await session.flush()
    view = (await bills_out(session, [b]))[0]
    prefix = st.invoice_prefix if kind == "invoice" else "CN"
    for _attempt in range(5):
        seq = (
            await session.execute(select(func.coalesce(func.max(Invoice.sequence), 0)).where(Invoice.kind == kind))
        ).scalar_one() + 1
        snapshot = {
            "kind": kind,
            "restaurant": {
                "name": tenant.name,
                "legal_name": st.legal_name or tenant.name,
                "gstin": st.gstin,
                "address": st.address or ", ".join(x for x in (branch.address_line, branch.city) if x),
                "branch": branch.name,
                "footer": st.invoice_footer,
                "currency": str((tenant.settings or {}).get("currency", "INR")),
                "tax_split": st.tax_split,
            },
            # The invoice never names who ate what (only the screens do).
            "bill": view.model_dump(
                mode="json",
                exclude={"methods": True, "other_method_label": True, "lines": {"__all__": {"ordered_by_name"}}},
            ),
            "original_number": original.number if original else None,
            "reason": reason or None,
            "total": str(total),
        }
        inv = Invoice(
            tenant_id=b.tenant_id,
            branch_id=b.branch_id,
            bill_id=b.id,
            kind=kind,
            sequence=seq,
            number=f"{prefix}-{seq:06d}",
            original_invoice_id=original.id if original else None,
            total=total,
            snapshot=snapshot,
            issued_at=_now(),
        )
        try:
            async with session.begin_nested():
                session.add(inv)
                await session.flush()
            return inv
        except IntegrityError:
            continue
    raise ConflictError("Busy right now, please try again.", code="BUSY")  # pragma: no cover


def invoice_out(inv: Invoice) -> InvoiceOut:
    return InvoiceOut.model_validate(inv)


async def list_invoices(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, day: str | None
) -> list[InvoiceOut]:
    from app.services.tables import _branch

    branch = await _branch(session, ctx, branch_id, "billing.operate")
    tz = ZoneInfo(branch.timezone)
    d = datetime.fromisoformat(day).date() if day else _now().astimezone(tz).date()
    start = datetime.combine(d, datetime.min.time(), tz)
    rows = (
        await session.execute(
            select(Invoice)
            .where(Invoice.branch_id == branch_id, Invoice.issued_at >= start, Invoice.issued_at < start + _day())
            .order_by(Invoice.issued_at.desc())
        )
    ).scalars()
    return [invoice_out(i) for i in rows]


async def staff_invoice(session: AsyncSession, ctx: TenantContext, invoice_id: uuid.UUID) -> Invoice:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice not found.")
    if not (
        ctx.can_act_in_branch("billing.operate", inv.branch_id)
        or ctx.can_act_in_branch("payments.collect", inv.branch_id)
    ):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return inv


# ---------- the visit: finish, reopen, close ----------


async def reopen(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID) -> SessionBillsOut:
    s = await _staff_session(session, ctx, session_id, "billing.operate")
    if s.status != "finished":
        raise ConflictError("Only a finished table can be reopened.", code="NOT_FINISHED")
    s.status = "open"
    write_audit(
        session,
        action="table_session.reopened",
        entity="table_session",
        entity_id=s.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    await _changed(ctx.tenant_id, s.branch_id, {s.id})
    return await session_bills_out(session, s)


async def ensure_settled(session: AsyncSession, s: TableSession, actor: uuid.UUID | None) -> None:
    """Before guests leave: every bill paid (₹0 bills are settled automatically). Caller commits."""
    from app.api.deps import feature_enabled

    if not await feature_enabled(session, s.tenant_id, "billing_pos"):
        return
    bills = await sync(session, s, actor)
    for b in bills:
        if b.status != "open":
            continue
        has_lines = (
            await session.execute(select(func.count()).select_from(BillItem).where(BillItem.bill_id == b.id))
        ).scalar_one()
        if not has_lines:
            b.status = "void"
            continue
        if b.grand_total - b.paid_total <= 0:
            b.locked = True
            await _paid_check(session, b)
            continue
        raise ConflictError(
            f"Bill {b.sequence} still has {b.grand_total - b.paid_total} due."
            " Take the payment first (or void the bill).",
            code="BILL_UNPAID",
            details={"bill_id": str(b.id)},
        )


# ---------- guests (table token) ----------


async def _require_billing(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    from app.api.deps import feature_enabled

    if not await feature_enabled(session, tenant_id, "billing_pos"):
        raise AppError("Please ask your waiter for the bill.", code="PLAN_FEATURE_REQUIRED", status_code=402)


async def guest_bills(session: AsyncSession, token: str | None) -> SessionBillsOut:
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    await _require_billing(session, s.tenant_id)
    if s.status != "closed":
        await sync(session, s, None)
        await session.commit()
    return await session_bills_out(session, s)


async def finish(session: AsyncSession, token: str | None) -> SessionBillsOut:
    """The guest's Finish (D10): no more orders; the final bill is ready to pay."""
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    await _require_billing(session, s.tenant_id)
    s = (await session.execute(select(TableSession).where(TableSession.id == s.id).with_for_update())).scalar_one()
    if s.status == "closed":
        raise ConflictError("This table is already closed.", code="SESSION_CLOSED")
    if s.status == "open":
        s.status = "finished"
    await sync(session, s, None)
    await session.commit()
    await _changed(s.tenant_id, s.branch_id, {s.id})
    return await session_bills_out(session, s)


async def _guest_bill(
    session: AsyncSession, token: str | None, bill_id: uuid.UUID
) -> tuple[Bill, TableSession, Tenant]:
    from app.services.orders import table_from_token

    s, tenant = await table_from_token(session, token)
    b = (await session.execute(select(Bill).where(Bill.id == bill_id).with_for_update())).scalar_one_or_none()
    if b is None or b.table_session_id != s.id:
        raise NotFoundError("Bill not found.")
    return b, s, tenant


async def pay_online(session: AsyncSession, token: str | None, bill_id: uuid.UUID) -> OnlinePaymentOut:
    b, s, tenant = await _guest_bill(session, token, bill_id)
    if b.status != "open":
        raise ConflictError(f"This bill is {b.status}.", code="BILL_CLOSED")
    st = settings_of(tenant)
    if "gateway" not in st.methods:
        raise AppError(
            "Online payment is not available here — please pay at the counter.", code="METHOD_DISABLED", status_code=422
        )
    if not b.locked:
        await recompute(session, b, st)
    due = b.grand_total - b.paid_total
    if due <= 0:
        raise ConflictError("Nothing is due on this bill.", code="NOTHING_DUE")
    currency = str((tenant.settings or {}).get("currency", "INR"))
    gateway = get_gateway()
    order = await gateway.create_order(due, currency, f"bill-{b.id}", {"bill_id": str(b.id), "tenant": tenant.slug})
    p = BillPayment(
        tenant_id=b.tenant_id,
        branch_id=b.branch_id,
        bill_id=b.id,
        method="gateway",
        amount=due,
        status="pending",
        provider=gateway.name,
        provider_order_id=order.order_id,
    )
    session.add(p)
    b.locked = True  # the amount being paid must not change underneath the guest
    await session.commit()
    return OnlinePaymentOut(
        payment_id=p.id,
        provider=gateway.name,
        order_id=order.order_id,
        amount=due,
        currency=currency,
        checkout=order.checkout,
    )


async def process_payment_event(session: AsyncSession, provider: str, event: PaymentEvent) -> str | None:
    """Verified webhook for a bill payment (None = not a bill payment). Idempotent."""
    await use_system(session)
    p = (
        await session.execute(
            select(BillPayment)
            .where(BillPayment.provider == provider, BillPayment.provider_order_id == event.order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if p is None:
        return None
    if p.status != "pending":
        return "already_processed"
    await use_tenant(session, p.tenant_id)
    b = (await session.execute(select(Bill).where(Bill.id == p.bill_id).with_for_update())).scalar_one()
    if event.type == "payment.failed" or event.amount != p.amount:
        p.status = "failed"
        await session.commit()
        await _changed(b.tenant_id, b.branch_id, {b.table_session_id})
        return "failed" if event.type == "payment.failed" else "amount_mismatch"
    p.status, p.provider_payment_id, p.captured_at = "captured", event.payment_id, _now()
    due = b.grand_total - b.paid_total
    if b.status != "open" or p.amount > due:
        # Paid at the counter meanwhile: give the online payment back automatically.
        ref = await get_gateway(provider).refund(event.payment_id or "", p.amount)
        p.refunded_amount = p.amount
        session.add(
            BillRefund(
                tenant_id=p.tenant_id,
                bill_id=b.id,
                payment_id=p.id,
                amount=p.amount,
                reason="Bill was already paid",
                provider_refund_id=ref,
            )
        )
        b.paid_total = _money(b.paid_total + p.amount)
        b.refunded_total = _money(b.refunded_total + p.amount)
        result = "refunded_overpayment"
    else:
        b.paid_total = _money(b.paid_total + p.amount)
        await _paid_check(session, b)
        result = "paid" if b.status == "paid" else "part_paid"
    write_audit(
        session,
        action=f"bill.online_{result}",
        entity="bill",
        entity_id=b.id,
        tenant_id=b.tenant_id,
        diff={"order_id": event.order_id, "amount": str(p.amount)},
    )
    await session.commit()
    await _changed(b.tenant_id, b.branch_id, {b.table_session_id})
    return result


async def guest_invoice(session: AsyncSession, token: str | None, invoice_id: uuid.UUID) -> Invoice:
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice not found.")
    b = await session.get(Bill, inv.bill_id)
    if b is None or b.table_session_id != s.id:
        raise NotFoundError("Invoice not found.")
    return inv


async def mock_bill_payment(session: AsyncSession, token: str | None, order_id: str, success: bool) -> str:
    """Development checkout for bills: sign a webhook and feed it through the verified path."""
    from app.integrations.payments.gateway import MockGateway
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    p = (
        await session.execute(
            select(BillPayment).where(BillPayment.provider == "mock", BillPayment.provider_order_id == order_id)
        )
    ).scalar_one_or_none()
    b = await session.get(Bill, p.bill_id) if p else None
    if p is None or b is None or b.table_session_id != s.id:
        raise NotFoundError("Payment not found.")
    raw, sig = MockGateway.build_event(order_id, p.amount, success)
    return await process_payment_event(session, "mock", MockGateway().parse_webhook(raw, sig)) or "unknown_order"


# ---------- paying the restaurant's own UPI ID (guest claims, staff confirm) ----------


async def upi_claim(session: AsyncSession, token: str | None, bill_id: uuid.UUID, reference: str) -> SessionBillsOut:
    """The guest paid the restaurant's UPI ID from the checkout page. WaitLess cannot see that money, so the
    payment waits as "pending" until staff confirm it on the Billing screen."""
    b, s, tenant = await _guest_bill(session, token, bill_id)
    st = settings_of(tenant)
    if not st.upi_id:
        raise AppError(
            "This restaurant has no UPI ID set up — pay online or at the counter.", code="UPI_NOT_SET", status_code=422
        )
    if b.status != "open":
        raise ConflictError(f"This bill is {b.status}.", code="BILL_CLOSED")
    pending = (
        await session.execute(
            select(BillPayment).where(
                BillPayment.bill_id == b.id, BillPayment.status == "pending", BillPayment.provider == "upi_direct"
            )
        )
    ).scalar_one_or_none()
    if pending is None:
        if not b.locked:
            await recompute(session, b, st)
        due = b.grand_total - b.paid_total
        if due <= 0:
            raise ConflictError("Nothing is due on this bill.", code="NOTHING_DUE")
        session.add(
            BillPayment(
                tenant_id=b.tenant_id,
                branch_id=b.branch_id,
                bill_id=b.id,
                method="upi",
                method_label="Paid to restaurant UPI",
                amount=due,
                status="pending",
                provider="upi_direct",
                reference=reference.strip()[:80],
            )
        )
        b.locked = True  # the amount the guest paid must not change underneath them
        write_audit(
            session,
            action="bill.upi_claimed",
            entity="bill",
            entity_id=b.id,
            tenant_id=b.tenant_id,
            diff={"amount": str(due), "reference": reference.strip()[:80]},
        )
        await session.commit()
        await _changed(b.tenant_id, b.branch_id, {s.id})
    return await session_bills_out(session, s)


async def review_upi_claim(session: AsyncSession, ctx: TenantContext, payment_id: uuid.UUID, accept: bool) -> BillOut:
    """Staff saw (or did not see) the money in the restaurant's UPI app."""
    p = (
        await session.execute(select(BillPayment).where(BillPayment.id == payment_id).with_for_update())
    ).scalar_one_or_none()
    if p is None or p.provider != "upi_direct":
        raise NotFoundError("Payment not found.")
    if not ctx.can_act_in_branch("payments.collect", p.branch_id):
        raise ForbiddenError("You cannot confirm payments here.", code="PERMISSION_DENIED")
    if p.status != "pending":
        raise ConflictError("This payment was already reviewed.", code="ALREADY_REVIEWED")
    b = (await session.execute(select(Bill).where(Bill.id == p.bill_id).with_for_update())).scalar_one()
    if accept:
        if b.status != "open" or p.amount > b.grand_total - b.paid_total:
            raise ConflictError("The bill was paid another way meanwhile — reject this one.", code="OVERPAYMENT")
        p.status, p.captured_at, p.received_by = "captured", _now(), ctx.user_id
        b.paid_total = _money(b.paid_total + p.amount)
        await _paid_check(session, b)
    else:
        p.status, p.received_by = "failed", ctx.user_id
        others = (
            await session.execute(
                select(func.count())
                .select_from(BillPayment)
                .where(
                    BillPayment.bill_id == b.id, BillPayment.id != p.id, BillPayment.status.in_(("captured", "pending"))
                )
            )
        ).scalar_one()
        if not others and b.status == "open":
            b.locked = False  # nothing was paid: the bill can change again
    write_audit(
        session,
        action="bill.upi_confirmed" if accept else "bill.upi_rejected",
        entity="bill",
        entity_id=b.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"amount": str(p.amount), "reference": p.reference},
    )
    await session.commit()
    await _changed(ctx.tenant_id, b.branch_id, {b.table_session_id})
    return (await bills_out(session, [b]))[0]


# ---------- the customer's own invoices (signed in) ----------


async def my_invoices(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Invoices of every visit where the signed-in customer ordered or had the booking, at all restaurants."""
    await use_system(session)
    bill_ids = select(BillItem.bill_id).join(Order, Order.id == BillItem.order_id).where(Order.customer_id == user.id)
    booked = (
        select(Bill.id)
        .join(Reservation, Reservation.table_session_id == Bill.table_session_id)
        .where(Reservation.customer_id == user.id)
    )
    rows = list(
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.bill_id.in_(bill_ids.union(booked)))
                .order_by(Invoice.issued_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    tenants = (
        {
            t.id: t
            for t in (await session.execute(select(Tenant).where(Tenant.id.in_({r.tenant_id for r in rows})))).scalars()
        }
        if rows
        else {}
    )
    out = []
    for inv in rows:
        snap = inv.snapshot or {}
        bill = snap.get("bill") or {}
        t = tenants.get(inv.tenant_id)
        out.append(
            {
                "id": inv.id,
                "number": inv.number,
                "kind": inv.kind,
                "total": str(inv.total),
                "issued_at": inv.issued_at,
                "restaurant_name": t.name if t else (snap.get("restaurant") or {}).get("name"),
                "restaurant_slug": t.slug if t else None,
                "items": [f"{ln['quantity']} × {ln['name']}" for ln in bill.get("lines", [])][:12],
            }
        )
    return out


async def my_invoice(session: AsyncSession, user: User, invoice_id: uuid.UUID) -> Invoice:
    ids = {r["id"] for r in await my_invoices(session, user)}
    if invoice_id not in ids:
        raise NotFoundError("Invoice not found.")
    inv = await session.get(Invoice, invoice_id)
    assert inv is not None
    return inv

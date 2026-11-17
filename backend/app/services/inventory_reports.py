"""Inventory reports (PRD §8.7): current stock, valuation, movements, consumption, wastage, purchases,
low stock and expiry — one branch, a date range in the branch's time zone. Returned as a plain table so
the screen and the CSV export are the same thing."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.inventory import InventoryItem, InventoryMovement, PurchaseOrder, Supplier
from app.schemas.inventory import ReportOut
from app.services import inventory as inv
from app.services.access import TenantContext
from app.services.tables import _branch

KINDS = ("current", "valuation", "movements", "consumption", "wastage", "purchases", "low_stock", "expiry")
TYPE_LABEL = {
    "opening": "Opening stock",
    "purchase": "Purchase",
    "addition": "Added",
    "consumption": "Used in orders",
    "reversal": "Order cancelled",
    "wastage": "Wastage",
    "damage": "Damaged",
    "adjustment": "Count correction",
    "transfer_out": "Transfer out",
    "transfer_in": "Transfer in",
    "return": "Returned to supplier",
}


def _n(v: Decimal) -> float:
    return float(v)


def _m(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'))}"


async def report(
    session: AsyncSession,
    ctx: TenantContext,
    kind: str,
    branch_id: uuid.UUID,
    start: date | None,
    end: date | None,
) -> ReportOut:
    if kind not in KINDS:
        raise AppError("Unknown report.", code="UNKNOWN_REPORT", status_code=404)
    branch = await _branch(session, ctx, branch_id, "inventory.view")
    tz = ZoneInfo(branch.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    end = end or today
    start = start or end - timedelta(days=29)
    t0 = datetime.combine(start, time.min, tz)
    t1 = datetime.combine(end + timedelta(days=1), time.min, tz)
    period = f"{start:%d %b %Y} – {end:%d %b %Y}"

    if kind in ("current", "valuation", "low_stock"):
        rows = await inv.stock(session, ctx, branch.id, include_inactive=False)
        if kind == "current":
            total = sum((r.value for r in rows), Decimal("0"))
            return ReportOut(
                kind=kind,
                title=f"Current stock · {branch.name}",
                columns=["Item", "SKU", "Category", "Unit", "On hand", "Reorder level", "Avg cost", "Value", "Status"],
                rows=[
                    [
                        r.name,
                        r.sku,
                        r.category_name,
                        r.unit,
                        _n(r.on_hand),
                        _n(r.reorder_level),
                        _m(r.avg_cost),
                        _m(r.value),
                        r.state,
                    ]
                    for r in rows
                ],
                totals={"Value": _m(total)},
            )
        if kind == "valuation":
            by_cat: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal("0"), Decimal("0")])
            for r in rows:
                by_cat[r.category_name or "Uncategorised"][0] += 1
                by_cat[r.category_name or "Uncategorised"][1] += r.value
            total = sum((v[1] for v in by_cat.values()), Decimal("0"))
            return ReportOut(
                kind=kind,
                title=f"Inventory valuation · {branch.name} (weighted average cost)",
                columns=["Category", "Items", "Value"],
                rows=[[c, int(v[0]), _m(v[1])] for c, v in sorted(by_cat.items())],
                totals={"Value": _m(total)},
            )
        low = [r for r in rows if r.state != "ok"]
        return ReportOut(
            kind=kind,
            title=f"Low & out of stock · {branch.name}",
            columns=["Item", "Unit", "On hand", "Reorder level", "Status", "Supplier"],
            rows=[[r.name, r.unit, _n(r.on_hand), _n(r.reorder_level), r.state, r.supplier_name] for r in low],
        )

    if kind == "expiry":
        rows = await inv.stock(session, ctx, branch.id, include_inactive=False)
        exp = await inv.expiring(session, branch.id, max((end - today).days, 30), {r.item_id: r for r in rows})
        return ReportOut(
            kind=kind,
            title=f"Expiry · {branch.name}",
            columns=["Item", "Batch quantity", "Unit", "Expires", "Days left", "On hand now"],
            rows=[[e.name, _n(e.quantity), e.unit, e.expiry_date.isoformat(), e.days_left, _n(e.on_hand)] for e in exp],
        )

    if kind == "purchases":
        sup = {s.id: s.name for s in (await session.execute(select(Supplier))).scalars()}
        pos = list(
            (
                await session.execute(
                    select(PurchaseOrder)
                    .where(
                        PurchaseOrder.branch_id == branch.id,
                        PurchaseOrder.order_date >= start,
                        PurchaseOrder.order_date <= end,
                    )
                    .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.sequence.desc())
                )
            ).scalars()
        )
        received = [p for p in pos if p.status == "received"]
        return ReportOut(
            kind=kind,
            title=f"Purchase history · {branch.name} · {period}",
            columns=["Number", "Date", "Supplier", "Invoice", "Status", "Total", "Paid", "Payment"],
            rows=[
                [
                    p.number,
                    p.order_date.isoformat(),
                    sup.get(p.supplier_id) if p.supplier_id else None,
                    p.invoice_number or None,
                    p.status,
                    _m(p.grand_total),
                    _m(p.amount_paid),
                    p.payment_status,
                ]
                for p in pos
            ],
            totals={
                "Received": _m(sum((p.grand_total for p in received), Decimal("0"))),
                "Outstanding": _m(sum((p.grand_total - p.amount_paid for p in received), Decimal("0"))),
            },
        )

    items = {i.id: i for i in (await session.execute(select(InventoryItem))).scalars()}
    in_range = (
        InventoryMovement.branch_id == branch.id,
        InventoryMovement.created_at >= t0,
        InventoryMovement.created_at < t1,
    )

    if kind == "consumption":
        rows_c = (
            await session.execute(
                select(InventoryMovement.item_id, InventoryMovement.type, func.sum(InventoryMovement.quantity))
                .where(*in_range, InventoryMovement.type.in_(("consumption", "reversal")))
                .group_by(InventoryMovement.item_id, InventoryMovement.type)
            )
        ).tuples()
        used: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        for iid, _t, q in rows_c:
            used[iid] -= Decimal(q)  # consumption is negative, reversal positive
        stock = {r.item_id: r for r in await inv.stock(session, ctx, branch.id, include_inactive=True)}
        out = []
        total = Decimal("0")
        for iid, q in sorted(used.items(), key=lambda kv: items[kv[0]].name.lower()):
            cost = q * (stock[iid].avg_cost if iid in stock else items[iid].purchase_price)
            total += cost
            out.append([items[iid].name, items[iid].unit, _n(q), _m(cost)])
        return ReportOut(
            kind=kind,
            title=f"Consumption by orders · {branch.name} · {period}",
            columns=["Item", "Unit", "Used", "Cost"],
            rows=out,
            totals={"Cost": _m(total)},
        )

    types = ("wastage", "damage") if kind == "wastage" else None
    stmt = select(InventoryMovement).where(*in_range)
    if types:
        stmt = stmt.where(InventoryMovement.type.in_(types))
    moves = await inv.movements_out(
        session, list((await session.execute(stmt.order_by(InventoryMovement.created_at.desc()).limit(5000))).scalars())
    )
    if kind == "wastage":
        total = Decimal("0")
        out = []
        for m in moves:
            cost = -m.quantity * (items[m.item_id].purchase_price)
            total += cost
            out.append(
                [
                    m.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                    m.item_name,
                    TYPE_LABEL[m.type],
                    _n(-m.quantity),
                    m.unit,
                    _m(cost),
                    m.reason,
                    m.actor_name,
                ]
            )
        return ReportOut(
            kind=kind,
            title=f"Wastage & damage · {branch.name} · {period}",
            columns=["When", "Item", "Type", "Quantity", "Unit", "Value", "Reason", "By"],
            rows=out,
            totals={"Value": _m(total)},
        )
    return ReportOut(
        kind=kind,
        title=f"Stock movements · {branch.name} · {period}",
        columns=["When", "Item", "Type", "Change", "Unit", "Balance", "Reason", "By"],
        rows=[
            [
                m.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                m.item_name,
                TYPE_LABEL[m.type],
                _n(m.quantity),
                m.unit,
                _n(m.balance_after),
                m.reason,
                m.actor_name,
            ]
            for m in moves
        ],
    )

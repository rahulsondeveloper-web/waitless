"""Restaurant analytics (PRD §15): dashboard figures and reports with charts.

Money comes from **paid bills** (Phase 10) — what was actually charged — net of refunds. Serving times come
from the order timers (Phase 8). Days are branch-local. Reports return a plain table plus chart series, so the
screen, the chart and the CSV export show exactly the same numbers.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.models import Branch
from app.models.billing import Bill, BillItem, BillPayment, BillRefund
from app.models.booking import QueueEntry, Reservation
from app.models.orders import Order
from app.models.sla import OrderSla
from app.services.access import TenantContext

ZERO = Decimal("0.00")
KINDS = {
    "sales": ("Sales", "reports.sales.view", "analytics.basic"),
    "payments": ("Payments by method", "reports.sales.view", "analytics.basic"),
    "orders": ("Orders", "reports.view", "analytics.basic"),
    "serving": ("Serving time & delays", "reports.view", "analytics.basic"),
    "discounts": ("Discounts given", "reports.sales.view", "analytics.basic"),
    "reservations": ("Reservations", "reports.view", "analytics.basic"),
    "queue": ("Walk-in queue", "reports.view", "analytics.basic"),
    "top_items": ("Best-selling dishes", "reports.sales.view", "analytics.advanced"),
    "hours": ("Busy hours", "reports.view", "analytics.advanced"),
}


def _m(v: Any) -> str:
    return f"{Decimal(v or 0).quantize(Decimal('0.01'))}"


def _minutes(seconds: float | None) -> float | None:
    return round(seconds / 60, 1) if seconds is not None else None


async def _tz(session: AsyncSession, branch_id: uuid.UUID | None) -> ZoneInfo:
    name = (
        await session.execute(
            select(Branch.timezone).where(Branch.id == branch_id)
            if branch_id
            else select(Branch.timezone).order_by(Branch.is_primary.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return ZoneInfo(name or "Asia/Kolkata")


def _zone_literal(tz: ZoneInfo):  # type: ignore[no-untyped-def]
    """The zone as an SQL literal (not a bind parameter), so GROUP BY matches the SELECT expression."""
    name = str(tz)
    if not all(c.isalnum() or c in "/_+-" for c in name):
        raise AppError("Invalid time zone.", code="INVALID_TZ", status_code=422)
    return literal_column(f"'{name}'")


def _window(tz: ZoneInfo, start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min, tz), datetime.combine(end + timedelta(days=1), time.min, tz)


def _scope(stmt, column, branch_id: uuid.UUID | None, allowed: frozenset[uuid.UUID] | None):  # type: ignore[no-untyped-def]
    if branch_id is not None:
        return stmt.where(column == branch_id)
    if allowed is not None:
        return stmt.where(column.in_(allowed))
    return stmt


def _allowed(ctx: TenantContext, perm: str) -> frozenset[uuid.UUID] | None:
    return None if (ctx.all_branches or ctx.permissions.get(perm) == "all") else ctx.branch_ids


# ---------- dashboard (PRD §15 statistics) ----------


async def dashboard_extras(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID | None) -> dict[str, Any]:
    """Today's revenue, discounts, average waiting & serving time, delayed orders, low-stock alerts."""
    tz = await _tz(session, branch_id)
    today = datetime.now(UTC).astimezone(tz).date()
    t0, t1 = _window(tz, today, today)
    allowed = _allowed(ctx, "tables.operate")
    out: dict[str, Any] = {}

    bills = (
        await session.execute(
            _scope(
                select(
                    func.coalesce(func.sum(Bill.grand_total), 0),
                    func.coalesce(func.sum(Bill.refunded_total), 0),
                    func.coalesce(func.sum(Bill.sla_discount + Bill.sla_discount_after_tax + Bill.manual_discount), 0),
                ).where(Bill.status == "paid", Bill.paid_at >= t0, Bill.paid_at < t1),
                Bill.branch_id,
                branch_id,
                allowed,
            )
        )
    ).one()
    if ctx.has("reports.sales.view") or ctx.has("billing.operate"):
        out["todays_revenue"] = _m(Decimal(bills[0]) - Decimal(bills[1]))
        out["discounts_today"] = _m(bills[2])

    wait = (
        await session.execute(
            _scope(
                select(func.avg(func.extract("epoch", QueueEntry.ended_at - QueueEntry.joined_at))).where(
                    QueueEntry.status == "seated", QueueEntry.ended_at >= t0, QueueEntry.ended_at < t1
                ),
                QueueEntry.branch_id,
                branch_id,
                allowed,
            )
        )
    ).scalar_one()
    out["average_wait_minutes"] = round(float(wait) / 60) if wait is not None else None

    served = (
        await session.execute(
            _scope(
                select(
                    func.avg(func.extract("epoch", OrderSla.ended_at - OrderSla.sla_started_at)),
                    func.count().filter(OrderSla.ended_at > OrderSla.deadline_at),
                ).where(OrderSla.status == "served", OrderSla.ended_at >= t0, OrderSla.ended_at < t1),
                OrderSla.branch_id,
                branch_id,
                allowed,
            )
        )
    ).one()
    running_late = (
        await session.execute(
            _scope(
                select(func.count()).where(OrderSla.status == "running", OrderSla.deadline_at < datetime.now(UTC)),
                OrderSla.branch_id,
                branch_id,
                allowed,
            )
        )
    ).scalar_one()
    out["average_serving_minutes"] = round(float(served[0]) / 60) if served[0] is not None else None
    out["delayed_orders"] = int(served[1]) + int(running_late)

    from app.api.deps import feature_enabled

    if ctx.has("inventory.view") and await feature_enabled(session, ctx.tenant_id, "inventory"):
        from app.services.inventory import stock

        bid = branch_id
        if bid is None:
            bid = (
                await session.execute(
                    select(Branch.id).where(Branch.is_active).order_by(Branch.is_primary.desc()).limit(1)
                )
            ).scalar_one_or_none()
        if bid is not None and ctx.can_act_in_branch("inventory.view", bid):
            rows = await stock(session, ctx, bid, include_inactive=False)
            out["low_inventory_alerts"] = sum(1 for r in rows if r.state != "ok")
    return out


# ---------- reports ----------


async def report(
    session: AsyncSession,
    ctx: TenantContext,
    kind: str,
    branch_id: uuid.UUID | None,
    start: date | None,
    end: date | None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise AppError("Unknown report.", code="UNKNOWN_REPORT", status_code=404)
    title, perm, feature = KINDS[kind]
    from app.api.deps import feature_enabled

    if not await feature_enabled(session, ctx.tenant_id, feature):
        raise AppError(
            "This report is part of a higher plan.",
            code="PLAN_FEATURE_REQUIRED",
            status_code=402,
            details={"feature": feature},
        )
    if not ctx.has(perm):
        raise ForbiddenError("You do not have permission to see this report.", code="PERMISSION_DENIED")
    if branch_id is not None:
        # Unknown here (another restaurant's branch is invisible through RLS) → 404, never an empty report.
        if (await session.execute(select(Branch.id).where(Branch.id == branch_id))).scalar_one_or_none() is None:
            raise NotFoundError("Branch not found.")
        if not ctx.can_act_in_branch(perm, branch_id):
            raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    tz = await _tz(session, branch_id)
    today = datetime.now(UTC).astimezone(tz).date()
    end = min(end or today, today + timedelta(days=366))
    start = start or end - timedelta(days=13)
    if start > end:
        start, end = end, start
    if (end - start).days > 366:
        raise AppError("Choose at most one year.", code="RANGE_TOO_LONG", status_code=422)
    t0, t1 = _window(tz, start, end)
    allowed = _allowed(ctx, perm)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    labels = [d.isoformat() for d in days]

    zone = _zone_literal(tz)

    def local_day(col):  # type: ignore[no-untyped-def]
        return func.date(func.timezone(zone, col))

    base: dict[str, Any] = {"kind": kind, "title": title, "from": start.isoformat(), "to": end.isoformat()}

    if kind == "sales":
        rows = {
            d: r
            for d, *r in (
                await session.execute(
                    _scope(
                        select(
                            local_day(Bill.paid_at),
                            func.count(),
                            func.sum(Bill.subtotal),
                            func.sum(Bill.sla_discount + Bill.sla_discount_after_tax + Bill.manual_discount),
                            func.sum(Bill.service_charge),
                            func.sum(Bill.tax_total),
                            func.sum(Bill.grand_total),
                            func.sum(Bill.refunded_total),
                        )
                        .where(Bill.status == "paid", Bill.paid_at >= t0, Bill.paid_at < t1)
                        .group_by(local_day(Bill.paid_at)),
                        Bill.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            ).tuples()
        }
        table, net_series = [], []
        tot = defaultdict(Decimal)
        for d in days:
            n, food, disc, svc, tax, gross, ref = rows.get(d, (0, 0, 0, 0, 0, 0, 0))
            net = Decimal(gross or 0) - Decimal(ref or 0)
            avg = net / n if n else ZERO
            table.append(
                [d.isoformat(), int(n), _m(food), _m(disc), _m(svc), _m(tax), _m(gross), _m(ref), _m(net), _m(avg)]
            )
            net_series.append(float(net))
            for k, v in (("bills", n), ("food", food), ("disc", disc), ("tax", tax), ("net", net)):
                tot[k] += Decimal(v or 0)
        return base | {
            "columns": [
                "Day",
                "Bills",
                "Food",
                "Discounts",
                "Service charge",
                "Tax",
                "Billed",
                "Refunded",
                "Net",
                "Average bill",
            ],
            "rows": table,
            "totals": {
                "Bills": str(int(tot["bills"])),
                "Net revenue": _m(tot["net"]),
                "Tax": _m(tot["tax"]),
                "Discounts": _m(tot["disc"]),
                "Average bill": _m(tot["net"] / tot["bills"]) if tot["bills"] else "0.00",
            },
            "chart": {"type": "bar", "labels": labels, "series": [{"name": "Net revenue", "data": net_series}]},
        }

    if kind == "payments":
        rows_p = (
            (
                await session.execute(
                    _scope(
                        select(
                            BillPayment.method,
                            func.count(),
                            func.sum(BillPayment.amount),
                            func.sum(BillPayment.refunded_amount),
                        )
                        .where(
                            BillPayment.status == "captured", BillPayment.created_at >= t0, BillPayment.created_at < t1
                        )
                        .group_by(BillPayment.method),
                        BillPayment.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            )
            .tuples()
            .all()
        )
        names = {"cash": "Cash", "upi": "UPI", "card": "Card", "gateway": "Online", "other": "Other"}
        table = [[names[m], int(n), _m(a), _m(r), _m(Decimal(a) - Decimal(r))] for m, n, a, r in rows_p]
        return base | {
            "columns": ["Method", "Payments", "Received", "Refunded", "Net"],
            "rows": table,
            "totals": {"Net": _m(sum((Decimal(r[4]) for r in table), Decimal(0)))},
            "chart": {
                "type": "doughnut",
                "labels": [r[0] for r in table],
                "series": [{"name": "Net", "data": [float(r[4]) for r in table]}],
            },
        }

    if kind == "orders":
        rows_o = defaultdict(dict)
        for d, status, n, total in (
            await session.execute(
                _scope(
                    select(local_day(Order.placed_at), Order.status, func.count(), func.sum(Order.total))
                    .where(Order.placed_at >= t0, Order.placed_at < t1)
                    .group_by(local_day(Order.placed_at), Order.status),
                    Order.branch_id,
                    branch_id,
                    allowed,
                )
            )
        ).tuples():
            rows_o[d][status] = (n, total)
        table, placed_s, cancelled_s = [], [], []
        tot = defaultdict(int)
        for d in days:
            st = rows_o.get(d, {})
            all_n = sum(v[0] for v in st.values())
            canc = st.get("cancelled", (0, 0))[0]
            value = sum((Decimal(v[1] or 0) for k, v in st.items() if k != "cancelled"), Decimal(0))
            table.append([d.isoformat(), all_n, all_n - canc, canc, _m(value)])
            placed_s.append(all_n - canc)
            cancelled_s.append(canc)
            tot["all"] += all_n
            tot["cancelled"] += canc
        return base | {
            "columns": ["Day", "Orders", "Kept", "Cancelled", "Order value"],
            "rows": table,
            "totals": {"Orders": str(tot["all"]), "Cancelled": str(tot["cancelled"])},
            "chart": {
                "type": "bar",
                "labels": labels,
                "stacked": True,
                "series": [{"name": "Orders", "data": placed_s}, {"name": "Cancelled", "data": cancelled_s}],
            },
        }

    if kind == "serving":
        rows_s = {
            d: r
            for d, *r in (
                await session.execute(
                    _scope(
                        select(
                            local_day(OrderSla.ended_at),
                            func.count(),
                            func.avg(func.extract("epoch", OrderSla.ended_at - OrderSla.sla_started_at)),
                            func.count().filter(OrderSla.ended_at > OrderSla.deadline_at),
                            func.max(func.extract("epoch", OrderSla.ended_at - OrderSla.sla_started_at)),
                        )
                        .where(OrderSla.status == "served", OrderSla.ended_at >= t0, OrderSla.ended_at < t1)
                        .group_by(local_day(OrderSla.ended_at)),
                        OrderSla.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            ).tuples()
        }
        table, avg_s, late_s = [], [], []
        served_total = late_total = 0
        weighted = 0.0
        for d in days:
            n, avg, late, worst = rows_s.get(d, (0, None, 0, None))
            on_time = round(100 * (n - late) / n) if n else None
            table.append(
                [
                    d.isoformat(),
                    int(n),
                    _minutes(float(avg)) if avg is not None else None,
                    int(late),
                    on_time,
                    _minutes(float(worst)) if worst is not None else None,
                ]
            )
            avg_s.append(_minutes(float(avg)) if avg is not None else 0)
            late_s.append(int(late))
            served_total += int(n)
            late_total += int(late)
            weighted += float(avg or 0) * int(n)
        return base | {
            "columns": ["Day", "Served", "Average minutes", "Late", "On time %", "Slowest (min)"],
            "rows": table,
            "totals": {
                "Served": str(served_total),
                "Late": str(late_total),
                "On time": f"{round(100 * (served_total - late_total) / served_total)}%" if served_total else "—",
                "Average": f"{_minutes(weighted / served_total)} min" if served_total else "—",
            },
            "chart": {
                "type": "line",
                "labels": labels,
                "series": [{"name": "Average minutes", "data": avg_s}, {"name": "Late orders", "data": late_s}],
            },
        }

    if kind == "discounts":
        rows_d = {
            d: r
            for d, *r in (
                await session.execute(
                    _scope(
                        select(
                            local_day(Bill.paid_at),
                            func.sum(Bill.sla_discount + Bill.sla_discount_after_tax),
                            func.sum(Bill.manual_discount),
                            func.sum(Bill.booking_credit),
                            func.count().filter(Bill.manual_discount > 0),
                        )
                        .where(Bill.status == "paid", Bill.paid_at >= t0, Bill.paid_at < t1)
                        .group_by(local_day(Bill.paid_at)),
                        Bill.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            ).tuples()
        }
        table, sla_s, man_s = [], [], []
        tot = defaultdict(Decimal)
        for d in days:
            sla, manual, credit, n_manual = rows_d.get(d, (0, 0, 0, 0))
            table.append([d.isoformat(), _m(sla), _m(manual), int(n_manual or 0), _m(credit)])
            sla_s.append(float(sla or 0))
            man_s.append(float(manual or 0))
            tot["sla"] += Decimal(sla or 0)
            tot["manual"] += Decimal(manual or 0)
            tot["credit"] += Decimal(credit or 0)
        return base | {
            "columns": [
                "Day",
                "Serving-time discounts",
                "Manual discounts",
                "Bills with a manual discount",
                "Booking fees credited",
            ],
            "rows": table,
            "totals": {
                "Serving-time": _m(tot["sla"]),
                "Manual": _m(tot["manual"]),
                "Booking credit": _m(tot["credit"]),
            },
            "chart": {
                "type": "bar",
                "labels": labels,
                "stacked": True,
                "series": [{"name": "Serving-time", "data": sla_s}, {"name": "Manual", "data": man_s}],
            },
        }

    if kind == "reservations":
        rows_r = defaultdict(dict)
        for d, status, n in (
            await session.execute(
                _scope(
                    select(local_day(Reservation.starts_at), Reservation.status, func.count())
                    .where(Reservation.starts_at >= t0, Reservation.starts_at < t1)
                    .group_by(local_day(Reservation.starts_at), Reservation.status),
                    Reservation.branch_id,
                    branch_id,
                    allowed,
                )
            )
        ).tuples():
            rows_r[d][status] = n
        cols = ["confirmed", "checked_in", "completed", "no_show", "cancelled", "expired"]
        table = []
        for d in days:
            st = rows_r.get(d, {})
            table.append([d.isoformat(), sum(st.values())] + [st.get(c, 0) for c in cols])
        return base | {
            "columns": ["Day", "Bookings", "Confirmed", "Arrived", "Completed", "No-show", "Cancelled", "Expired"],
            "rows": table,
            "totals": {"Bookings": str(sum(r[1] for r in table)), "No-shows": str(sum(r[5] for r in table))},
            "chart": {"type": "bar", "labels": labels, "series": [{"name": "Bookings", "data": [r[1] for r in table]}]},
        }

    if kind == "queue":
        rows_q = {
            d: r
            for d, *r in (
                await session.execute(
                    _scope(
                        select(
                            local_day(QueueEntry.joined_at),
                            func.count(),
                            func.count().filter(QueueEntry.status == "seated"),
                            func.avg(func.extract("epoch", QueueEntry.ended_at - QueueEntry.joined_at)).filter(
                                QueueEntry.status == "seated"
                            ),
                            func.count().filter(QueueEntry.status.in_(("cancelled", "skipped", "expired"))),
                        )
                        .where(QueueEntry.joined_at >= t0, QueueEntry.joined_at < t1)
                        .group_by(local_day(QueueEntry.joined_at)),
                        QueueEntry.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            ).tuples()
        }
        table = []
        for d in days:
            n, seated, avg, lost = rows_q.get(d, (0, 0, None, 0))
            table.append(
                [d.isoformat(), int(n), int(seated), _minutes(float(avg)) if avg is not None else None, int(lost)]
            )
        return base | {
            "columns": ["Day", "Joined", "Seated", "Average wait (min)", "Left / skipped"],
            "rows": table,
            "totals": {"Joined": str(sum(r[1] for r in table)), "Seated": str(sum(r[2] for r in table))},
            "chart": {
                "type": "line",
                "labels": labels,
                "series": [{"name": "Average wait (min)", "data": [r[3] or 0 for r in table]}],
            },
        }

    if kind == "top_items":
        rows_t = (
            (
                await session.execute(
                    _scope(
                        select(
                            BillItem.name,
                            func.sum(BillItem.quantity),
                            func.sum(BillItem.line_total),
                            func.sum(BillItem.sla_discount + BillItem.manual_discount),
                        )
                        .join(Bill, and_(Bill.id == BillItem.bill_id))
                        .where(Bill.status == "paid", Bill.paid_at >= t0, Bill.paid_at < t1)
                        .group_by(BillItem.name)
                        .order_by(func.sum(BillItem.line_total).desc())
                        .limit(25),
                        Bill.branch_id,
                        branch_id,
                        allowed,
                    )
                )
            )
            .tuples()
            .all()
        )
        table = [[name, int(q), _m(v), _m(dsc)] for name, q, v, dsc in rows_t]
        return base | {
            "columns": ["Dish", "Sold", "Food value", "Discounts"],
            "rows": table,
            "totals": {"Food value": _m(sum((Decimal(r[2]) for r in table), Decimal(0)))},
            "chart": {
                "type": "bar",
                "horizontal": True,
                "labels": [r[0] for r in table[:10]],
                "series": [{"name": "Food value", "data": [float(r[2]) for r in table[:10]]}],
            },
        }

    # hours: orders per hour of day (branch time)
    hour = func.extract("hour", func.timezone(zone, Order.placed_at))
    rows_h = dict(
        (
            await session.execute(
                _scope(
                    select(hour, func.count())
                    .where(Order.placed_at >= t0, Order.placed_at < t1, Order.status != "cancelled")
                    .group_by(hour),
                    Order.branch_id,
                    branch_id,
                    allowed,
                )
            )
        )
        .tuples()
        .all()
    )
    table = [[f"{h:02d}:00", int(rows_h.get(Decimal(h), rows_h.get(h, 0)) or 0)] for h in range(24)]
    return base | {
        "columns": ["Hour", "Orders"],
        "rows": table,
        "totals": {"Busiest": max(table, key=lambda r: r[1])[0] if any(r[1] for r in table) else "—"},
        "chart": {
            "type": "bar",
            "labels": [r[0] for r in table],
            "series": [{"name": "Orders", "data": [r[1] for r in table]}],
        },
    }


async def refunds_total(session: AsyncSession, t0: datetime, t1: datetime) -> Decimal:  # pragma: no cover - helper
    v = (
        await session.execute(
            select(func.coalesce(func.sum(BillRefund.amount), 0)).where(
                BillRefund.created_at >= t0, BillRefund.created_at < t1
            )
        )
    ).scalar_one()
    return Decimal(v)

"""Suppliers and purchases (PRD §8.3–8.4).

Purchase flow: draft → ordered → received (stock comes in, one `purchase` movement per line, at the
price paid before tax; the item's purchase price is updated) · draft/ordered → cancelled.
Payments to the supplier can be recorded at any time up to the purchase total.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Branch
from app.models.inventory import InventoryItem, PurchaseOrder, PurchaseOrderItem, PurchasePayment, Supplier
from app.schemas.inventory import (
    PaymentIn,
    PaymentOut,
    PurchaseIn,
    PurchaseLineOut,
    PurchaseOut,
    ReceiveIn,
    SupplierIn,
    SupplierOut,
)
from app.services import inventory as inv
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.tables import _branch

CENT = Decimal("0.01")
ZERO = Decimal("0")


def _money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- suppliers ----------


async def list_suppliers(session: AsyncSession) -> list[SupplierOut]:
    stats: dict[uuid.UUID, tuple[int, Decimal, Decimal]] = {}
    for sid, n, total, outstanding in (
        await session.execute(
            select(
                PurchaseOrder.supplier_id,
                func.count(),
                func.coalesce(func.sum(PurchaseOrder.grand_total), 0),
                func.coalesce(func.sum(PurchaseOrder.grand_total - PurchaseOrder.amount_paid), 0),
            )
            .where(PurchaseOrder.status == "received", PurchaseOrder.supplier_id.is_not(None))
            .group_by(PurchaseOrder.supplier_id)
        )
    ).tuples():
        stats[sid] = (n, Decimal(total), Decimal(outstanding))
    out = []
    for s in (await session.execute(select(Supplier).order_by(func.lower(Supplier.name)))).scalars():
        n, total, outstanding = stats.get(s.id, (0, ZERO, ZERO))
        out.append(
            SupplierOut.model_validate(s).model_copy(
                update={"purchases_count": n, "purchases_total": _money(total), "outstanding": _money(outstanding)}
            )
        )
    return out


async def save_supplier(
    session: AsyncSession, ctx: TenantContext, data: SupplierIn, supplier_id: uuid.UUID | None = None
) -> SupplierOut:
    s = await session.get(Supplier, supplier_id) if supplier_id else None
    if supplier_id and s is None:
        raise NotFoundError("Supplier not found.")
    created = s is None
    if s is None:
        s = Supplier(tenant_id=ctx.tenant_id)
        session.add(s)
    for k, v in data.model_dump().items():
        setattr(s, k, v.strip() if isinstance(v, str) else v)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A supplier with this name already exists.", code="DUPLICATE_NAME") from exc
    write_audit(
        session,
        action="supplier.created" if created else "supplier.updated",
        entity="supplier",
        entity_id=s.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    return next(x for x in await list_suppliers(session) if x.id == s.id)


# ---------- purchases ----------


async def purchases_out(session: AsyncSession, purchases: list[PurchaseOrder]) -> list[PurchaseOut]:
    if not purchases:
        return []
    ids = [p.id for p in purchases]
    branches = {b.id: b.name for b in (await session.execute(select(Branch))).scalars()}
    suppliers = {s.id: s.name for s in (await session.execute(select(Supplier))).scalars()}
    lines: dict[uuid.UUID, list[PurchaseLineOut]] = defaultdict(list)
    for li, item in (
        await session.execute(
            select(PurchaseOrderItem, InventoryItem)
            .join(InventoryItem, InventoryItem.id == PurchaseOrderItem.item_id)
            .where(PurchaseOrderItem.purchase_id.in_(ids))
            .order_by(PurchaseOrderItem.sort_order)
        )
    ).tuples():
        lines[li.purchase_id].append(
            PurchaseLineOut(
                item_id=item.id,
                name=item.name,
                unit=item.unit,
                quantity=li.quantity,
                unit_price=li.unit_price,
                tax_pct=li.tax_pct,
                line_total=li.line_total,
                tax_amount=li.tax_amount,
                received_quantity=li.received_quantity,
                expiry_date=li.expiry_date,
            )
        )
    pays: dict[uuid.UUID, list[PaymentOut]] = defaultdict(list)
    for pay in (
        await session.execute(
            select(PurchasePayment).where(PurchasePayment.purchase_id.in_(ids)).order_by(PurchasePayment.created_at)
        )
    ).scalars():
        pays[pay.purchase_id].append(PaymentOut.model_validate(pay))
    return [
        PurchaseOut(
            id=p.id,
            number=p.number,
            status=p.status,  # type: ignore[arg-type]
            branch_id=p.branch_id,
            branch_name=branches.get(p.branch_id, ""),
            supplier_id=p.supplier_id,
            supplier_name=suppliers.get(p.supplier_id) if p.supplier_id else None,
            order_date=p.order_date,
            expected_date=p.expected_date,
            invoice_number=p.invoice_number,
            invoice_date=p.invoice_date,
            subtotal=p.subtotal,
            tax_total=p.tax_total,
            grand_total=p.grand_total,
            amount_paid=p.amount_paid,
            payment_status=p.payment_status,  # type: ignore[arg-type]
            notes=p.notes,
            items=lines[p.id],
            payments=pays[p.id],
            received_at=p.received_at,
            created_at=p.created_at,
        )
        for p in purchases
    ]


async def list_purchases(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID | None, supplier_id: uuid.UUID | None
) -> list[PurchaseOut]:
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).limit(300)
    if branch_id:
        await _branch(session, ctx, branch_id, "purchases.manage")
        stmt = stmt.where(PurchaseOrder.branch_id == branch_id)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    rows = [
        p for p in (await session.execute(stmt)).scalars() if ctx.can_act_in_branch("purchases.manage", p.branch_id)
    ]
    return await purchases_out(session, rows)


async def _purchase(session: AsyncSession, ctx: TenantContext, purchase_id: uuid.UUID) -> PurchaseOrder:
    p = (
        await session.execute(select(PurchaseOrder).where(PurchaseOrder.id == purchase_id).with_for_update())
    ).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Purchase not found.")
    if not ctx.can_act_in_branch("purchases.manage", p.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return p


async def _set_lines(session: AsyncSession, p: PurchaseOrder, data: PurchaseIn) -> None:
    for old in (
        await session.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_id == p.id))
    ).scalars():
        await session.delete(old)
    await session.flush()
    subtotal = tax = ZERO
    seen: set[uuid.UUID] = set()
    for i, ln in enumerate(data.items):
        if ln.item_id in seen:
            raise AppError("Each item can appear only once.", code="DUPLICATE_LINE", status_code=422)
        seen.add(ln.item_id)
        await inv._item(session, ln.item_id)
        line_total = _money(ln.quantity * ln.unit_price)
        line_tax = _money(line_total * ln.tax_pct / 100)
        subtotal += line_total
        tax += line_tax
        session.add(
            PurchaseOrderItem(
                tenant_id=p.tenant_id,
                purchase_id=p.id,
                item_id=ln.item_id,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                tax_pct=ln.tax_pct,
                line_total=line_total,
                tax_amount=line_tax,
                sort_order=i,
            )
        )
    p.subtotal, p.tax_total, p.grand_total = _money(subtotal), _money(tax), _money(subtotal + tax)


async def save_purchase(
    session: AsyncSession, ctx: TenantContext, data: PurchaseIn, purchase_id: uuid.UUID | None = None
) -> PurchaseOut:
    branch = await _branch(session, ctx, data.branch_id, "purchases.manage")
    if data.supplier_id and await session.get(Supplier, data.supplier_id) is None:
        raise NotFoundError("Supplier not found.")
    if purchase_id:
        p = await _purchase(session, ctx, purchase_id)
        if p.status not in ("draft", "ordered"):
            raise ConflictError(f"A {p.status} purchase cannot be edited.", code="PURCHASE_LOCKED")
    else:
        today = datetime.now(UTC).astimezone(ZoneInfo(branch.timezone)).date()
        for _attempt in range(5):
            seq = (await session.execute(select(func.coalesce(func.max(PurchaseOrder.sequence), 0)))).scalar_one() + 1
            p = PurchaseOrder(
                tenant_id=ctx.tenant_id,
                branch_id=branch.id,
                sequence=seq,
                number=f"PO-{seq:04d}",
                order_date=data.order_date or today,
                created_by=ctx.user_id,
            )
            try:
                async with session.begin_nested():
                    session.add(p)
                    await session.flush()
                break
            except IntegrityError:
                continue
        else:  # pragma: no cover
            raise ConflictError("Busy right now, please try again.", code="BUSY")
    p.branch_id, p.supplier_id = branch.id, data.supplier_id
    p.order_date = data.order_date or p.order_date
    p.expected_date, p.invoice_number, p.invoice_date = (
        data.expected_date,
        data.invoice_number.strip(),
        data.invoice_date,
    )
    p.notes, p.status = data.notes.strip(), data.status
    await _set_lines(session, p, data)
    if p.amount_paid > p.grand_total:
        raise ConflictError("The total is now below what was already paid.", code="PAID_EXCEEDS_TOTAL")
    _payment_status(p)
    write_audit(
        session,
        action="purchase.updated" if purchase_id else "purchase.created",
        entity="purchase",
        entity_id=p.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"total": str(p.grand_total), "status": p.status},
    )
    await session.commit()
    return (await purchases_out(session, [p]))[0]


def _payment_status(p: PurchaseOrder) -> None:
    p.payment_status = (
        "paid" if p.grand_total > 0 and p.amount_paid >= p.grand_total else "partial" if p.amount_paid > 0 else "unpaid"
    )


async def set_status(session: AsyncSession, ctx: TenantContext, purchase_id: uuid.UUID, to: str) -> PurchaseOut:
    p = await _purchase(session, ctx, purchase_id)
    allowed = {("draft", "ordered"), ("draft", "cancelled"), ("ordered", "cancelled"), ("ordered", "draft")}
    if (p.status, to) not in allowed:
        raise ConflictError(f"A {p.status} purchase cannot become {to}.", code="INVALID_TRANSITION")
    if to == "cancelled" and p.amount_paid > 0:
        raise ConflictError("Payments were recorded on this purchase.", code="PURCHASE_HAS_PAYMENTS")
    p.status = to
    write_audit(
        session,
        action=f"purchase.{to}",
        entity="purchase",
        entity_id=p.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    return (await purchases_out(session, [p]))[0]


async def receive(session: AsyncSession, ctx: TenantContext, purchase_id: uuid.UUID, data: ReceiveIn) -> PurchaseOut:
    """Goods arrived: stock comes in at the price paid (before tax), with expiry dates where given."""
    p = await _purchase(session, ctx, purchase_id)
    if p.status not in ("draft", "ordered"):
        raise ConflictError(f"This purchase is already {p.status}.", code="PURCHASE_LOCKED")
    given = {ln.item_id: ln for ln in data.items}
    lines = list(
        (await session.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_id == p.id))).scalars()
    )
    unknown = set(given) - {li.item_id for li in lines}
    if unknown:
        raise AppError("Only items on this purchase can be received.", code="INVALID_LINE", status_code=422)
    subtotal = tax = ZERO
    for li in lines:
        item = await inv._item(session, li.item_id)
        g = given.get(li.item_id)
        qty = g.received_quantity if g else li.quantity
        li.received_quantity, li.expiry_date = qty, g.expiry_date if g else None
        if item.tracks_expiry and qty > 0 and li.expiry_date is None:
            raise AppError(f"Enter the expiry date for {item.name}.", code="EXPIRY_REQUIRED", status_code=422)
        # Bill what actually arrived.
        li.line_total = _money(qty * li.unit_price)
        li.tax_amount = _money(li.line_total * li.tax_pct / 100)
        subtotal += li.line_total
        tax += li.tax_amount
        if qty > 0:
            await inv.apply(
                session,
                tenant_id=p.tenant_id,
                branch_id=p.branch_id,
                item=item,
                delta=qty,
                type="purchase",
                reason=f"{p.number}"
                + (
                    f" · invoice {data.invoice_number or p.invoice_number}"
                    if (data.invoice_number or p.invoice_number)
                    else ""
                ),
                actor_user_id=ctx.user_id,
                unit_cost=li.unit_price,
                purchase_id=p.id,
                expiry_date=li.expiry_date,
            )
            item.purchase_price = li.unit_price  # last purchase price
            if p.supplier_id and item.supplier_id is None:
                item.supplier_id = p.supplier_id
    p.subtotal, p.tax_total, p.grand_total = _money(subtotal), _money(tax), _money(subtotal + tax)
    if p.amount_paid > p.grand_total:
        raise ConflictError("More was paid than the goods received.", code="PAID_EXCEEDS_TOTAL")
    if data.invoice_number is not None:
        p.invoice_number = data.invoice_number.strip()
    if data.invoice_date:
        p.invoice_date = data.invoice_date
    p.status, p.received_at, p.received_by = "received", datetime.now(UTC), ctx.user_id
    _payment_status(p)
    write_audit(
        session,
        action="purchase.received",
        entity="purchase",
        entity_id=p.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"total": str(p.grand_total)},
    )
    await session.commit()
    await inv.flush_alerts(session)
    await inv._changed(ctx.tenant_id, p.branch_id)
    return (await purchases_out(session, [p]))[0]


async def add_payment(
    session: AsyncSession, ctx: TenantContext, purchase_id: uuid.UUID, data: PaymentIn
) -> PurchaseOut:
    p = await _purchase(session, ctx, purchase_id)
    if p.status == "cancelled":
        raise ConflictError("This purchase was cancelled.", code="PURCHASE_LOCKED")
    if p.amount_paid + data.amount > p.grand_total:
        raise ConflictError(f"Only {p.grand_total - p.amount_paid} is outstanding on {p.number}.", code="OVERPAYMENT")
    session.add(
        PurchasePayment(
            tenant_id=p.tenant_id,
            purchase_id=p.id,
            amount=data.amount,
            method=data.method,
            reference=data.reference.strip(),
            paid_on=data.paid_on or datetime.now(UTC).date(),
            created_by=ctx.user_id,
        )
    )
    p.amount_paid = _money(p.amount_paid + data.amount)
    _payment_status(p)
    write_audit(
        session,
        action="purchase.payment",
        entity="purchase",
        entity_id=p.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"amount": str(data.amount), "method": data.method},
    )
    await session.commit()
    return (await purchases_out(session, [p]))[0]

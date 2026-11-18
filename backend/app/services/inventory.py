"""Inventory (PRD §8): items, the stock engine, manual movements, transfers, recipes, order consumption, alerts.

Stock engine (`apply`)
- Every change is one insert into the ledger plus an update of the cached balance, in the same transaction,
  under a row lock on the balance — so concurrent changes never lose an update.
- Manual reductions (wastage, damage, return, transfer) cannot take stock below zero: 409 `INSUFFICIENT_STOCK`.
  Order consumption may (the kitchen is never blocked by a missed delivery); the item then shows "out" and a
  count correction fixes it.

Order consumption (decision D22)
- Deducted when the kitchen **accepts** an order (or starts preparing it directly), once per order line and
  ingredient — guarded by the partial unique index `uq_inventory_consumption`.
- Cancelling after that writes one reversing movement per deduction (`uq_inventory_reversal`).
- Recipes: rows for a size replace the base recipe for that size. Quantities are converted g↔kg, ml↔l.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Branch, User
from app.models.inventory import (
    InventoryCategory,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    PurchaseOrder,
    RecipeIngredient,
    StockTransfer,
    StockTransferItem,
    Supplier,
)
from app.models.menu import MenuItem, MenuItemVariant
from app.models.orders import Order, OrderItem
from app.models.tenancy import Membership, RolePermission, UserBranch
from app.schemas.inventory import (
    AlertRow,
    AlertsOut,
    CategoryIn,
    CategoryOut,
    ExpiryRow,
    ItemIn,
    ItemOut,
    MovementIn,
    MovementOut,
    RecipeIn,
    RecipeLineOut,
    RecipeOut,
    StockRow,
    TransferIn,
    TransferLineOut,
    TransferOut,
)
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.notify import user_room
from app.services.tables import _branch
from app.websocket.bus import branch_staff_room, emit

log = logging.getLogger(__name__)
Q3 = Decimal("0.001")
CENT = Decimal("0.01")
ZERO = Decimal("0")
# factor to convert 1 <from> into <to>
_CONVERT: dict[tuple[str, str], Decimal] = {
    ("g", "kg"): Decimal("0.001"),
    ("kg", "g"): Decimal("1000"),
    ("ml", "l"): Decimal("0.001"),
    ("l", "ml"): Decimal("1000"),
}
INBOUND_COSTED = ("opening", "purchase", "addition", "transfer_in")
_ALERTS_KEY = "inventory_alerts"


def _now() -> datetime:
    return datetime.now(UTC)


def _q(v: Decimal) -> Decimal:
    return v.quantize(Q3, rounding=ROUND_HALF_UP)


def compatible(a: str, b: str) -> bool:
    return a == b or (a, b) in _CONVERT


def convert(quantity: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """150 g → 0.150 kg. Pieces, packets and boxes only convert to themselves."""
    if from_unit == to_unit:
        return quantity
    factor = _CONVERT.get((from_unit, to_unit))
    if factor is None:
        raise AppError(f"{from_unit} cannot be converted to {to_unit}.", code="UNIT_MISMATCH", status_code=422)
    return quantity * factor


def _state(on_hand: Decimal, reorder_level: Decimal) -> str:
    if on_hand <= 0:
        return "out"
    if reorder_level > 0 and on_hand <= reorder_level:
        return "low"
    return "ok"


# ---------- the stock engine ----------


async def apply(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    branch_id: uuid.UUID,
    item: InventoryItem,
    delta: Decimal,
    type: str,
    reason: str,
    actor_user_id: uuid.UUID | None,
    unit_cost: Decimal | None = None,
    allow_negative: bool = False,
    **refs: Any,
) -> InventoryMovement:
    """Write one ledger movement and update the cached balance (caller commits)."""
    delta = _q(delta)
    if delta == 0:
        raise ConflictError("Nothing to change.", code="NO_CHANGE")
    await session.execute(
        pg_insert(InventoryStock)
        .values(item_id=item.id, branch_id=branch_id, tenant_id=tenant_id, on_hand=ZERO, avg_cost=ZERO)
        .on_conflict_do_nothing(index_elements=["item_id", "branch_id"])
    )
    stock = (
        await session.execute(
            select(InventoryStock)
            .where(InventoryStock.item_id == item.id, InventoryStock.branch_id == branch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    before = stock.on_hand
    after = before + delta
    if after < 0 and not allow_negative:
        raise ConflictError(
            f"Only {_fmt(before)} {item.unit} of {item.name} in stock.",
            code="INSUFFICIENT_STOCK",
            details={"item_id": str(item.id), "on_hand": str(before)},
        )
    if delta > 0 and type in INBOUND_COSTED and unit_cost is not None:
        base = max(before, ZERO)
        stock.avg_cost = ((base * stock.avg_cost + delta * unit_cost) / (base + delta)).quantize(Decimal("0.0001"))
    stock.on_hand = after
    m = InventoryMovement(
        tenant_id=tenant_id,
        branch_id=branch_id,
        item_id=item.id,
        type=type,
        quantity=delta,
        balance_after=after,
        unit_cost=unit_cost,
        reason=reason.strip()[:200],
        actor_user_id=actor_user_id,
        **refs,
    )
    session.add(m)
    level = item.reorder_level
    crossed_low = level > 0 and before > level >= after
    crossed_out = before > 0 >= after
    if crossed_low or crossed_out:
        session.info.setdefault(_ALERTS_KEY, []).append(
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "item": item.name,
                "unit": item.unit,
                "on_hand": after,
                "out": after <= 0,
            }
        )
    return m


def _fmt(v: Decimal) -> str:
    return f"{v.normalize():f}" if v == v.to_integral() else f"{v.quantize(Q3).normalize():f}"


async def flush_alerts(session: AsyncSession) -> None:
    """After commit: tell owners/managers that stock reached its reorder level (PRD §8.6) and refresh screens."""
    alerts: list[dict[str, Any]] = session.info.pop(_ALERTS_KEY, [])
    branches = {(a["tenant_id"], a["branch_id"]) for a in alerts}
    for tid, bid in branches:
        await emit("inventory.changed", {"branch_id": str(bid)}, branch_staff_room(tid, bid))
    for a in alerts:
        users = await _stock_managers(session, a["branch_id"])
        title = f"{a['item']} is {'out of stock' if a['out'] else 'running low'}"
        body = f"{_fmt(a['on_hand'])} {a['unit']} left. Create a purchase order from Inventory → Alerts."
        log.info("inventory alert: %s — %s", title, body)
        for uid in users:
            await emit(
                "notification",
                {"event": "inventory.low_stock", "title": title, "body": body, "link": "/restaurant-admin/inventory"},
                user_room(uid),
            )


async def _stock_managers(session: AsyncSession, branch_id: uuid.UUID) -> list[uuid.UUID]:
    """Active staff who can order stock (`purchases.manage`) for this branch."""
    rows = await session.execute(
        select(Membership.user_id)
        .join(RolePermission, RolePermission.role_id == Membership.role_id)
        .outerjoin(UserBranch, and_(UserBranch.membership_id == Membership.id, UserBranch.branch_id == branch_id))
        .where(
            RolePermission.permission_key == "purchases.manage",
            Membership.status == "active",
            or_(Membership.all_branches, RolePermission.scope == "all", UserBranch.branch_id.is_not(None)),
        )
        .distinct()
    )
    return list(rows.scalars())


async def _changed(tenant_id: uuid.UUID, *branch_ids: uuid.UUID) -> None:
    for bid in set(branch_ids):
        await emit("inventory.changed", {"branch_id": str(bid)}, branch_staff_room(tenant_id, bid))


# ---------- categories ----------


async def list_categories(session: AsyncSession) -> list[CategoryOut]:
    rows = (
        await session.execute(select(InventoryCategory).order_by(InventoryCategory.sort_order, InventoryCategory.name))
    ).scalars()
    return [CategoryOut.model_validate(c) for c in rows]


async def save_category(
    session: AsyncSession, ctx: TenantContext, data: CategoryIn, category_id: uuid.UUID | None = None
) -> CategoryOut:
    c = await session.get(InventoryCategory, category_id) if category_id else None
    if category_id and c is None:
        raise NotFoundError("Category not found.")
    if c is None:
        c = InventoryCategory(tenant_id=ctx.tenant_id)
        session.add(c)
    c.name, c.sort_order = data.name.strip(), data.sort_order
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A category with this name already exists.", code="DUPLICATE_NAME") from exc
    return CategoryOut.model_validate(c)


async def delete_category(session: AsyncSession, category_id: uuid.UUID) -> None:
    c = await session.get(InventoryCategory, category_id)
    if c is None:
        raise NotFoundError("Category not found.")
    await session.delete(c)  # items keep existing without a category
    await session.commit()


# ---------- items ----------


async def _item(session: AsyncSession, item_id: uuid.UUID) -> InventoryItem:
    item = await session.get(InventoryItem, item_id)
    if item is None:
        raise NotFoundError("Inventory item not found.")
    return item


async def _items_out(session: AsyncSession, items: list[InventoryItem]) -> list[ItemOut]:
    cats = {c.id: c.name for c in (await session.execute(select(InventoryCategory))).scalars()}
    sups = {s.id: s.name for s in (await session.execute(select(Supplier))).scalars()}
    return [
        ItemOut.model_validate(i).model_copy(
            update={
                "category_name": cats.get(i.category_id) if i.category_id else None,
                "supplier_name": sups.get(i.supplier_id) if i.supplier_id else None,
            }
        )
        for i in items
    ]


async def list_items(session: AsyncSession) -> list[ItemOut]:
    items = list((await session.execute(select(InventoryItem).order_by(func.lower(InventoryItem.name)))).scalars())
    return await _items_out(session, items)


async def save_item(
    session: AsyncSession, ctx: TenantContext, data: ItemIn, item_id: uuid.UUID | None = None
) -> ItemOut:
    item = await _item(session, item_id) if item_id else None
    if item is not None and item.unit != data.unit:
        used = (
            await session.execute(
                select(func.count()).select_from(InventoryMovement).where(InventoryMovement.item_id == item.id)
            )
        ).scalar_one()
        if used:
            raise ConflictError(
                "The unit cannot change once stock has been recorded — create a new item instead.",
                code="UNIT_LOCKED",
            )
    if data.category_id and await session.get(InventoryCategory, data.category_id) is None:
        raise NotFoundError("Category not found.")
    if data.supplier_id and await session.get(Supplier, data.supplier_id) is None:
        raise NotFoundError("Supplier not found.")
    created = item is None
    if item is None:
        item = InventoryItem(tenant_id=ctx.tenant_id)
        session.add(item)
    for k, v in data.model_dump().items():
        setattr(item, k, v.strip() if isinstance(v, str) else v)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        msg = (
            "An item with this SKU already exists."
            if "sku" in str(exc.orig)
            else "An item with this name already exists."
        )
        raise ConflictError(msg, code="DUPLICATE_NAME") from exc
    write_audit(
        session,
        action="inventory_item.created" if created else "inventory_item.updated",
        entity="inventory_item",
        entity_id=item.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff=data.model_dump(mode="json"),
    )
    await session.commit()
    return (await _items_out(session, [item]))[0]


# ---------- stock & movements ----------


async def stock(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, include_inactive: bool
) -> list[StockRow]:
    await _branch(session, ctx, branch_id, "inventory.view")
    stmt = (
        select(InventoryItem, InventoryStock, InventoryCategory.name, Supplier.name)
        .outerjoin(
            InventoryStock, and_(InventoryStock.item_id == InventoryItem.id, InventoryStock.branch_id == branch_id)
        )
        .outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id)
        .outerjoin(Supplier, Supplier.id == InventoryItem.supplier_id)
        .order_by(func.lower(InventoryItem.name))
    )
    if not include_inactive:
        stmt = stmt.where(InventoryItem.is_active)
    out = []
    for item, st, cat, sup in (await session.execute(stmt)).tuples():
        on_hand = st.on_hand if st else ZERO
        avg = st.avg_cost if st and st.avg_cost > 0 else item.purchase_price
        out.append(
            StockRow(
                item_id=item.id,
                name=item.name,
                sku=item.sku,
                unit=item.unit,
                category_name=cat,
                supplier_id=item.supplier_id,
                supplier_name=sup,
                storage_location=item.storage_location,
                on_hand=on_hand,
                min_stock=item.min_stock,
                reorder_level=item.reorder_level,
                avg_cost=Decimal(avg).quantize(CENT),
                value=(max(on_hand, ZERO) * Decimal(avg)).quantize(CENT),
                state=_state(on_hand, item.reorder_level),  # type: ignore[arg-type]
                is_active=item.is_active,
                tracks_expiry=item.tracks_expiry,
            )
        )
    return out


async def record_movement(session: AsyncSession, ctx: TenantContext, data: MovementIn) -> MovementOut:
    """Opening stock, additions, wastage, damage, returns and count corrections — always with a reason."""
    branch = await _branch(session, ctx, data.branch_id, "inventory.adjust")
    item = await _item(session, data.item_id)
    reason = data.reason.strip()
    cost = data.unit_cost
    if data.type == "opening":
        prior = (
            await session.execute(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.item_id == item.id, InventoryMovement.branch_id == branch.id)
            )
        ).scalar_one()
        if prior:
            raise ConflictError(
                "This item already has stock history here — use a count correction instead.", code="OPENING_EXISTS"
            )
        delta, reason, cost = (
            data.quantity,
            reason or "Opening stock",
            cost if cost is not None else item.purchase_price,
        )
    elif data.type == "addition":
        delta, cost = data.quantity, cost if cost is not None else item.purchase_price
    elif data.type == "adjustment":
        current = (
            await session.execute(
                select(InventoryStock.on_hand).where(
                    InventoryStock.item_id == item.id, InventoryStock.branch_id == branch.id
                )
            )
        ).scalar_one_or_none() or ZERO
        delta = data.quantity - current
        reason = f"Count {_fmt(data.quantity)} {item.unit}: {reason}"
    else:  # wastage, damage, return
        delta = -data.quantity
    if data.expiry_date and delta < 0:
        raise AppError("An expiry date belongs to stock coming in.", code="EXPIRY_ON_OUTBOUND", status_code=422)
    m = await apply(
        session,
        tenant_id=ctx.tenant_id,
        branch_id=branch.id,
        item=item,
        delta=delta,
        type=data.type,
        reason=reason,
        actor_user_id=ctx.user_id,
        unit_cost=cost if delta > 0 else None,
        expiry_date=data.expiry_date,
    )
    await session.flush()
    write_audit(
        session,
        action=f"inventory.{data.type}",
        entity="inventory_item",
        entity_id=item.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"branch_id": str(branch.id), "quantity": str(m.quantity), "balance_after": str(m.balance_after)},
        reason=reason,
    )
    await session.commit()
    await flush_alerts(session)
    await _changed(ctx.tenant_id, branch.id)
    return (await movements_out(session, [m]))[0]


async def movements_out(session: AsyncSession, rows: list[InventoryMovement]) -> list[MovementOut]:
    if not rows:
        return []
    items = {
        i.id: i
        for i in (
            await session.execute(select(InventoryItem).where(InventoryItem.id.in_({r.item_id for r in rows})))
        ).scalars()
    }
    uids = {r.actor_user_id for r in rows if r.actor_user_id}
    users = (
        {u.id: u.full_name for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars()}
        if uids
        else {}
    )
    oids = {r.order_id for r in rows if r.order_id}
    orders = (
        {o.id: o.number for o in (await session.execute(select(Order).where(Order.id.in_(oids)))).scalars()}
        if oids
        else {}
    )
    pids = {r.purchase_id for r in rows if r.purchase_id}
    pos = (
        {
            p.id: p.number
            for p in (await session.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(pids)))).scalars()
        }
        if pids
        else {}
    )
    tids = {r.transfer_id for r in rows if r.transfer_id}
    trs = (
        {
            t.id: t.number
            for t in (await session.execute(select(StockTransfer).where(StockTransfer.id.in_(tids)))).scalars()
        }
        if tids
        else {}
    )
    return [
        MovementOut(
            id=r.id,
            branch_id=r.branch_id,
            item_id=r.item_id,
            item_name=items[r.item_id].name,
            unit=items[r.item_id].unit,
            type=r.type,  # type: ignore[arg-type]
            quantity=r.quantity,
            balance_after=r.balance_after,
            unit_cost=r.unit_cost,
            reason=r.reason,
            actor_name=users.get(r.actor_user_id) if r.actor_user_id else None,
            order_number=orders.get(r.order_id) if r.order_id else None,
            purchase_number=pos.get(r.purchase_id) if r.purchase_id else None,
            transfer_number=trs.get(r.transfer_id) if r.transfer_id else None,
            expiry_date=r.expiry_date,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def list_movements(
    session: AsyncSession,
    ctx: TenantContext,
    branch_id: uuid.UUID,
    *,
    item_id: uuid.UUID | None = None,
    types: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 200,
) -> list[MovementOut]:
    await _branch(session, ctx, branch_id, "inventory.view")
    stmt = select(InventoryMovement).where(InventoryMovement.branch_id == branch_id)
    if item_id:
        stmt = stmt.where(InventoryMovement.item_id == item_id)
    if types:
        stmt = stmt.where(InventoryMovement.type.in_(types))
    if start:
        stmt = stmt.where(InventoryMovement.created_at >= datetime.combine(start, datetime.min.time(), UTC))
    if end:
        stmt = stmt.where(
            InventoryMovement.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
        )
    rows = list(
        (await session.execute(stmt.order_by(InventoryMovement.created_at.desc()).limit(min(limit, 2000)))).scalars()
    )
    return await movements_out(session, rows)


# ---------- transfers ----------


async def _next_seq(session: AsyncSession, model: type[StockTransfer] | type[PurchaseOrder]) -> int:
    return (await session.execute(select(func.coalesce(func.max(model.sequence), 0)))).scalar_one() + 1


async def _transfer_out(session: AsyncSession, transfers: list[StockTransfer]) -> list[TransferOut]:
    if not transfers:
        return []
    names = {b.id: b.name for b in (await session.execute(select(Branch))).scalars()}
    lines: dict[uuid.UUID, list[TransferLineOut]] = {t.id: [] for t in transfers}
    for li, item in (
        await session.execute(
            select(StockTransferItem, InventoryItem)
            .join(InventoryItem, InventoryItem.id == StockTransferItem.item_id)
            .where(StockTransferItem.transfer_id.in_(list(lines)))
        )
    ).tuples():
        lines[li.transfer_id].append(
            TransferLineOut(item_id=item.id, name=item.name, unit=item.unit, quantity=li.quantity)
        )
    return [
        TransferOut(
            id=t.id,
            number=t.number,
            status=t.status,  # type: ignore[arg-type]
            from_branch_id=t.from_branch_id,
            from_branch_name=names.get(t.from_branch_id, ""),
            to_branch_id=t.to_branch_id,
            to_branch_name=names.get(t.to_branch_id, ""),
            items=lines[t.id],
            notes=t.notes,
            created_at=t.created_at,
            received_at=t.received_at,
        )
        for t in transfers
    ]


async def list_transfers(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[TransferOut]:
    await _branch(session, ctx, branch_id, "inventory.view")
    rows = (
        await session.execute(
            select(StockTransfer)
            .where(or_(StockTransfer.from_branch_id == branch_id, StockTransfer.to_branch_id == branch_id))
            .order_by(StockTransfer.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return await _transfer_out(session, list(rows))


async def send_transfer(session: AsyncSession, ctx: TenantContext, data: TransferIn) -> TransferOut:
    """Stock leaves the sending branch now; it arrives only when the other branch receives it."""
    src = await _branch(session, ctx, data.from_branch_id, "inventory.transfer")
    dst = (await session.execute(select(Branch).where(Branch.id == data.to_branch_id))).scalar_one_or_none()
    if dst is None:
        raise NotFoundError("Branch not found.")
    for _attempt in range(5):
        seq = await _next_seq(session, StockTransfer)
        t = StockTransfer(
            tenant_id=ctx.tenant_id,
            from_branch_id=src.id,
            to_branch_id=dst.id,
            sequence=seq,
            number=f"TR-{seq:04d}",
            notes=data.notes.strip(),
            sent_by=ctx.user_id,
        )
        try:
            async with session.begin_nested():
                session.add(t)
                await session.flush()
            break
        except IntegrityError:
            continue
    else:  # pragma: no cover
        raise ConflictError("Busy right now, please try again.", code="BUSY")
    for ln in data.items:
        item = await _item(session, ln.item_id)
        cost = (
            await session.execute(
                select(InventoryStock.avg_cost).where(
                    InventoryStock.item_id == item.id, InventoryStock.branch_id == src.id
                )
            )
        ).scalar_one_or_none() or item.purchase_price
        session.add(
            StockTransferItem(
                tenant_id=ctx.tenant_id, transfer_id=t.id, item_id=item.id, quantity=ln.quantity, unit_cost=cost
            )
        )
        await apply(
            session,
            tenant_id=ctx.tenant_id,
            branch_id=src.id,
            item=item,
            delta=-ln.quantity,
            type="transfer_out",
            reason=f"{t.number} to {dst.name}",
            actor_user_id=ctx.user_id,
            transfer_id=t.id,
        )
    write_audit(
        session,
        action="inventory.transfer_sent",
        entity="stock_transfer",
        entity_id=t.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"to": str(dst.id), "lines": len(data.items)},
    )
    await session.commit()
    await flush_alerts(session)
    await _changed(ctx.tenant_id, src.id, dst.id)
    return (await _transfer_out(session, [t]))[0]


async def _transfer(session: AsyncSession, transfer_id: uuid.UUID) -> StockTransfer:
    t = (
        await session.execute(select(StockTransfer).where(StockTransfer.id == transfer_id).with_for_update())
    ).scalar_one_or_none()
    if t is None:
        raise NotFoundError("Transfer not found.")
    if t.status != "in_transit":
        raise ConflictError(f"This transfer is already {t.status.replace('_', ' ')}.", code="TRANSFER_CLOSED")
    return t


async def finish_transfer(
    session: AsyncSession, ctx: TenantContext, transfer_id: uuid.UUID, receive: bool
) -> TransferOut:
    """Receive at the destination, or cancel (stock goes back to the sender)."""
    t = await _transfer(session, transfer_id)
    branch_id = t.to_branch_id if receive else t.from_branch_id
    await _branch(session, ctx, branch_id, "inventory.transfer")
    names = {b.id: b.name for b in (await session.execute(select(Branch))).scalars()}
    for li in (await session.execute(select(StockTransferItem).where(StockTransferItem.transfer_id == t.id))).scalars():
        item = await _item(session, li.item_id)
        await apply(
            session,
            tenant_id=ctx.tenant_id,
            branch_id=branch_id,
            item=item,
            delta=li.quantity,
            type="transfer_in",
            reason=f"{t.number} from {names.get(t.from_branch_id, '')}" if receive else f"{t.number} cancelled",
            actor_user_id=ctx.user_id,
            unit_cost=li.unit_cost,
            transfer_id=t.id,
        )
    t.status = "received" if receive else "cancelled"
    t.received_by, t.received_at = ctx.user_id, _now()
    write_audit(
        session,
        action="inventory.transfer_received" if receive else "inventory.transfer_cancelled",
        entity="stock_transfer",
        entity_id=t.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    await _changed(ctx.tenant_id, t.from_branch_id, t.to_branch_id)
    return (await _transfer_out(session, [t]))[0]


# ---------- recipes ----------


async def get_recipe(session: AsyncSession, menu_item_id: uuid.UUID) -> RecipeOut:
    if await session.get(MenuItem, menu_item_id) is None:
        raise NotFoundError("Dish not found.")
    lines = []
    cost = ZERO
    for r, item in (
        await session.execute(
            select(RecipeIngredient, InventoryItem)
            .join(InventoryItem, InventoryItem.id == RecipeIngredient.inventory_item_id)
            .where(RecipeIngredient.menu_item_id == menu_item_id)
            .order_by(RecipeIngredient.variant_id.is_(None).desc(), func.lower(InventoryItem.name))
        )
    ).tuples():
        line_cost = (convert(r.quantity, r.unit, item.unit) * item.purchase_price).quantize(CENT)
        if r.variant_id is None:
            cost += line_cost
        lines.append(
            RecipeLineOut(
                inventory_item_id=item.id,
                variant_id=r.variant_id,
                quantity=r.quantity,
                unit=r.unit,  # type: ignore[arg-type]
                name=item.name,
                stock_unit=item.unit,
                cost=line_cost,
            )
        )
    return RecipeOut(menu_item_id=menu_item_id, lines=lines, cost=cost)


async def set_recipe(session: AsyncSession, ctx: TenantContext, menu_item_id: uuid.UUID, data: RecipeIn) -> RecipeOut:
    dish = await session.get(MenuItem, menu_item_id)
    if dish is None:
        raise NotFoundError("Dish not found.")
    variants = set(
        (await session.execute(select(MenuItemVariant.id).where(MenuItemVariant.item_id == dish.id))).scalars()
    )
    for ln in data.lines:
        if ln.variant_id and ln.variant_id not in variants:
            raise AppError("That size does not belong to this dish.", code="INVALID_VARIANT", status_code=422)
        item = await _item(session, ln.inventory_item_id)
        if not compatible(ln.unit, item.unit):
            raise AppError(
                f"{item.name} is stocked in {item.unit}; use {item.unit}"
                + (" or its small unit" if item.unit in ("kg", "l") else "")
                + ".",
                code="UNIT_MISMATCH",
                status_code=422,
            )
    for old in (
        await session.execute(select(RecipeIngredient).where(RecipeIngredient.menu_item_id == dish.id))
    ).scalars():
        await session.delete(old)
    await session.flush()
    for ln in data.lines:
        session.add(
            RecipeIngredient(
                tenant_id=ctx.tenant_id,
                menu_item_id=dish.id,
                variant_id=ln.variant_id,
                inventory_item_id=ln.inventory_item_id,
                quantity=ln.quantity,
                unit=ln.unit,
            )
        )
    write_audit(
        session,
        action="recipe.updated",
        entity="menu_item",
        entity_id=dish.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"lines": len(data.lines)},
    )
    await session.commit()
    return await get_recipe(session, dish.id)


# ---------- order consumption (D22) ----------


@dataclass
class _Need:
    order_item_id: uuid.UUID
    item: InventoryItem
    quantity: Decimal


async def _needs(session: AsyncSession, order: Order) -> list[_Need]:
    lines = list((await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars())
    dish_ids = {ln.menu_item_id for ln in lines if ln.menu_item_id}
    if not dish_ids:
        return []
    recipe: dict[uuid.UUID, list[RecipeIngredient]] = {}
    for r in (
        await session.execute(select(RecipeIngredient).where(RecipeIngredient.menu_item_id.in_(dish_ids)))
    ).scalars():
        recipe.setdefault(r.menu_item_id, []).append(r)
    if not recipe:
        return []
    variants = {
        (v.item_id, v.name): v.id
        for v in (await session.execute(select(MenuItemVariant).where(MenuItemVariant.item_id.in_(dish_ids)))).scalars()
    }
    items = {
        i.id: i
        for i in (
            await session.execute(
                select(InventoryItem).where(
                    InventoryItem.id.in_({r.inventory_item_id for rows in recipe.values() for r in rows})
                )
            )
        ).scalars()
    }
    needs = []
    for ln in lines:
        rows = recipe.get(ln.menu_item_id) if ln.menu_item_id else None
        if not rows:
            continue
        vid = variants.get((ln.menu_item_id, ln.variant_name)) if ln.variant_name else None
        sized = [r for r in rows if vid and r.variant_id == vid]
        use = sized or [r for r in rows if r.variant_id is None]
        for r in use:
            item = items[r.inventory_item_id]
            needs.append(_Need(ln.id, item, _q(convert(r.quantity, r.unit, item.unit) * ln.quantity)))
    return needs


async def _inventory_on(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    from app.api.deps import feature_enabled  # local: avoid import cycle

    return await feature_enabled(session, tenant_id, "inventory")


async def consume_order(session: AsyncSession, order: Order, actor_user_id: uuid.UUID | None) -> int:
    """Kitchen accepted: deduct the recipe of every line, once (caller commits). Returns movements written."""
    if not await _inventory_on(session, order.tenant_id):
        return 0
    done = set(
        (
            await session.execute(
                select(InventoryMovement.order_item_id, InventoryMovement.item_id).where(
                    InventoryMovement.order_id == order.id, InventoryMovement.type == "consumption"
                )
            )
        ).tuples()
    )
    written = 0
    for need in await _needs(session, order):
        if (need.order_item_id, need.item.id) in done or need.quantity <= 0:
            continue
        await apply(
            session,
            tenant_id=order.tenant_id,
            branch_id=order.branch_id,
            item=need.item,
            delta=-need.quantity,
            type="consumption",
            reason=f"Order #{order.number}",
            actor_user_id=actor_user_id,
            allow_negative=True,
            order_id=order.id,
            order_item_id=need.order_item_id,
        )
        done.add((need.order_item_id, need.item.id))
        written += 1
    return written


async def reverse_order(session: AsyncSession, order: Order, actor_user_id: uuid.UUID | None) -> int:
    """Order cancelled after the kitchen accepted: put back every deduction, once (caller commits)."""
    moves = list(
        (await session.execute(select(InventoryMovement).where(InventoryMovement.order_id == order.id))).scalars()
    )
    reversed_ = {(m.order_item_id, m.item_id) for m in moves if m.type == "reversal"}
    written = 0
    for m in moves:
        if m.type != "consumption" or (m.order_item_id, m.item_id) in reversed_:
            continue
        item = await _item(session, m.item_id)
        await apply(
            session,
            tenant_id=order.tenant_id,
            branch_id=m.branch_id,
            item=item,
            delta=-m.quantity,
            type="reversal",
            reason=f"Order #{order.number} cancelled",
            actor_user_id=actor_user_id,
            order_id=order.id,
            order_item_id=m.order_item_id,
        )
        written += 1
    return written


# ---------- alerts ----------


async def alerts(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, days: int = 7) -> AlertsOut:
    rows = await stock(session, ctx, branch_id, include_inactive=False)
    prices = {i.id: i.purchase_price for i in (await session.execute(select(InventoryItem))).scalars()}
    low, out = [], []
    for r in rows:
        if r.state == "ok":
            continue
        target = max(r.reorder_level * 2, r.min_stock, r.reorder_level)
        suggested = _q(max(target - r.on_hand, ZERO)) if target > 0 else ZERO
        a = AlertRow(
            item_id=r.item_id,
            name=r.name,
            unit=r.unit,
            on_hand=r.on_hand,
            reorder_level=r.reorder_level,
            min_stock=r.min_stock,
            state=r.state,  # type: ignore[arg-type]
            suggested_quantity=suggested,
            supplier_id=r.supplier_id,
            supplier_name=r.supplier_name,
            purchase_price=prices.get(r.item_id, ZERO),
        )
        (out if r.state == "out" else low).append(a)
    return AlertsOut(low=low, out=out, expiring=await expiring(session, branch_id, days, {r.item_id: r for r in rows}))


async def expiring(
    session: AsyncSession, branch_id: uuid.UUID, days: int, stock_rows: dict[uuid.UUID, StockRow]
) -> list[ExpiryRow]:
    """Batches received with an expiry date up to `days` ahead (already expired included) while stock remains.
    "Today" is the branch's own date (an Indian branch just after midnight is already a day ahead of UTC)."""
    from zoneinfo import ZoneInfo

    tz = (await session.execute(select(Branch.timezone).where(Branch.id == branch_id))).scalar_one_or_none()
    try:
        today = _now().astimezone(ZoneInfo(tz or "Asia/Kolkata")).date()
    except (KeyError, ValueError):
        today = _now().date()
    rows = (
        await session.execute(
            select(InventoryMovement)
            .where(
                InventoryMovement.branch_id == branch_id,
                InventoryMovement.expiry_date.is_not(None),
                InventoryMovement.quantity > 0,
                InventoryMovement.expiry_date <= today + timedelta(days=days),
                InventoryMovement.expiry_date >= today - timedelta(days=30),
            )
            .order_by(InventoryMovement.expiry_date)
        )
    ).scalars()
    out = []
    for m in rows:
        st = stock_rows.get(m.item_id)
        if st is None or st.on_hand <= 0:
            continue
        out.append(
            ExpiryRow(
                item_id=m.item_id,
                name=st.name,
                unit=st.unit,
                quantity=m.quantity,
                expiry_date=m.expiry_date,  # type: ignore[arg-type]
                days_left=(m.expiry_date - today).days,  # type: ignore[operator]
                on_hand=st.on_hand,
            )
        )
    return out


def ensure_branch_access(ctx: TenantContext, branch_id: uuid.UUID, permission: str) -> None:
    if not ctx.can_act_in_branch(permission, branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")

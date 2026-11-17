"""Food ordering & kitchen (PRD §13), table-session guest access and paid pre-orders (PRD §12).

Rules
- The server prices every order from the live menu (variant/branch price + add-ons, tax per dish);
  whatever the browser shows is only a preview. Lines keep snapshots of names and prices.
- Idempotency: a retried submission with the same `Idempotency-Key` returns the original order.
- Status flow: placed → accepted → preparing → ready (kitchen) → served (waiter: `orders.mark_served`).
- Paid pre-orders wait until the guests arrive (staff "Confirm arrival") before the kitchen starts —
  the 15-minute promise starts at arrival (Phase 8).
- Free bookings cannot pre-order: `PREORDER_NOT_ALLOWED`.
"""

import hmac
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.db import use_system, use_tenant
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import create_table_token, decode_table_token, hash_otp
from app.models import Branch, Tenant, User
from app.models.booking import Reservation
from app.models.menu import (
    MenuAddon,
    MenuAddonGroup,
    MenuCategory,
    MenuItem,
    MenuItemAvailability,
    MenuItemBranchOverride,
    MenuItemVariant,
)
from app.models.orders import ORDER_ACTIVE, Order, OrderItem, OrderStatusHistory
from app.models.tables import RestaurantTable, TableAssignment, TableSession
from app.schemas.orders import (
    OrderAddonOut,
    OrderIn,
    OrderLineIn,
    OrderLineOut,
    OrderOut,
    StaffOrderIn,
    TableJoinIn,
    TableJoinOut,
    TableSessionView,
)
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.notify import notify_guest, user_room
from app.websocket.bus import branch_staff_room, emit

log = logging.getLogger(__name__)
CENT = Decimal("0.01")
GUEST_CANCELLABLE = ("placed",)
STAFF_CANCELLABLE = ("placed", "accepted", "preparing")
# (from, to) → permission needed
TRANSITIONS: dict[tuple[str, str], str] = {
    ("placed", "accepted"): "kitchen.operate",
    ("placed", "preparing"): "kitchen.operate",
    ("accepted", "preparing"): "kitchen.operate",
    ("preparing", "ready"): "kitchen.operate",
    ("ready", "served"): "orders.mark_served",  # Ready ≠ Served (PRD §13)
}


def _now() -> datetime:
    return datetime.now(UTC)


def _money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def table_session_room(tenant_id: uuid.UUID, session_id: uuid.UUID) -> str:
    return f"t:{tenant_id}:s:{session_id}"


async def _changed(o: Order) -> None:
    data = {"branch_id": str(o.branch_id), "order_id": str(o.id), "status": o.status}
    await emit("orders.changed", data, branch_staff_room(o.tenant_id, o.branch_id))
    if o.table_session_id:
        await emit("orders.changed", data, table_session_room(o.tenant_id, o.table_session_id))
    if o.customer_id:
        await emit("orders.changed", data, user_room(o.customer_id))


# ---------- pricing ----------


async def _price(session: AsyncSession, branch: Branch, lines: list[OrderLineIn], at: datetime) -> list[dict]:
    """Validate against the live menu at `at` (branch time zone) and return order-line values."""
    ids = list({ln.menu_item_id for ln in lines})
    items = {
        i.id: i
        for i in (
            await session.execute(
                select(MenuItem)
                .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
                .where(MenuItem.id.in_(ids), MenuItem.archived_at.is_(None), MenuCategory.is_active)
            )
        ).scalars()
    }
    variants = {
        v.id: v
        for v in (await session.execute(select(MenuItemVariant).where(MenuItemVariant.item_id.in_(ids)))).scalars()
    }
    has_variants = {v.item_id for v in variants.values()}
    groups = {
        g.id: g
        for g in (await session.execute(select(MenuAddonGroup).where(MenuAddonGroup.item_id.in_(ids)))).scalars()
    }
    addons = (
        {
            a.id: a
            for a in (await session.execute(select(MenuAddon).where(MenuAddon.group_id.in_(list(groups))))).scalars()
        }
        if groups
        else {}
    )
    windows: dict[uuid.UUID, list[MenuItemAvailability]] = defaultdict(list)
    for w in (
        await session.execute(select(MenuItemAvailability).where(MenuItemAvailability.item_id.in_(ids)))
    ).scalars():
        windows[w.item_id].append(w)
    overrides = {
        o.item_id: o
        for o in (
            await session.execute(
                select(MenuItemBranchOverride).where(
                    MenuItemBranchOverride.item_id.in_(ids), MenuItemBranchOverride.branch_id == branch.id
                )
            )
        ).scalars()
    }
    local = at.astimezone(ZoneInfo(branch.timezone))

    out = []
    for n, ln in enumerate(lines):
        item = items.get(ln.menu_item_id)
        if item is None:
            raise AppError("A dish in your order is no longer on the menu.", code="ITEM_UNAVAILABLE", status_code=409)
        ov = overrides.get(item.id)
        if not item.is_available or (ov is not None and not ov.is_available):
            raise ConflictError(
                f"{item.name} is sold out right now.", code="ITEM_UNAVAILABLE", details={"item": item.name}
            )
        ws = windows.get(item.id)
        if ws and not any(w.weekday == local.weekday() and w.from_time <= local.time() < w.to_time for w in ws):
            raise ConflictError(
                f"{item.name} is not served at this time.", code="ITEM_NOT_AVAILABLE_NOW", details={"item": item.name}
            )
        if item.id in has_variants:
            v = variants.get(ln.variant_id) if ln.variant_id else None
            if v is None or v.item_id != item.id:
                raise AppError(f"Choose a size for {item.name}.", code="VARIANT_REQUIRED", status_code=422)
            base, variant_name = v.price, v.name
        else:
            if ln.variant_id is not None:
                raise AppError(f"{item.name} has no sizes.", code="INVALID_VARIANT", status_code=422)
            base = ov.price_override if ov is not None and ov.price_override is not None else item.base_price
            variant_name = None
        chosen = []
        per_group: dict[uuid.UUID, int] = defaultdict(int)
        for aid in ln.addon_ids:
            a = addons.get(aid)
            g = groups.get(a.group_id) if a else None
            if a is None or g is None or g.item_id != item.id:
                raise AppError(f"An extra for {item.name} is no longer offered.", code="INVALID_ADDON", status_code=422)
            per_group[g.id] += 1
            chosen.append(a)
        for g in groups.values():
            if g.item_id != item.id:
                continue
            k = per_group.get(g.id, 0)
            if k < g.min_select or k > g.max_select:
                need = f"exactly {g.min_select}" if g.min_select == g.max_select else f"{g.min_select}–{g.max_select}"
                raise AppError(
                    f"{item.name}: choose {need} from “{g.name}”.",
                    code="ADDON_RULES",
                    status_code=422,
                    details={"group": g.name},
                )
        unit = _money(base + sum((a.price for a in chosen), Decimal("0")))
        line_total = _money(unit * ln.quantity)
        out.append(
            {
                "menu_item_id": item.id,
                "name": item.name,
                "variant_name": variant_name,
                "addons": [{"name": a.name, "price": str(a.price)} for a in chosen],
                "food_class": item.food_class,
                "unit_price": unit,
                "quantity": ln.quantity,
                "tax_pct": item.tax_pct,
                "line_total": line_total,
                "tax_amount": _money(line_total * item.tax_pct / 100),
                "instructions": ln.instructions.strip(),
                "sort_order": n,
            }
        )
    return out


# ---------- creating ----------


async def _find_idempotent(session: AsyncSession, key: str | None) -> Order | None:
    if not key:
        return None
    return (await session.execute(select(Order).where(Order.idempotency_key == key))).scalar_one_or_none()


async def _create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    branch: Branch,
    data: OrderIn,
    order_type: str,
    source: str,
    at: datetime,
    table_session_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    placed_by: uuid.UUID | None = None,
    idem: str | None = None,
) -> tuple[Order, bool]:
    """Returns (order, created). A repeated idempotency key returns the original order."""
    if (existing := await _find_idempotent(session, idem)) is not None:
        return existing, False
    lines = await _price(session, branch, data.items, at)
    subtotal = sum((ln["line_total"] for ln in lines), Decimal("0"))
    tax = sum((ln["tax_amount"] for ln in lines), Decimal("0"))
    day = _now().astimezone(ZoneInfo(branch.timezone)).date()
    for _attempt in range(5):
        seq = (
            await session.execute(
                select(func.coalesce(func.max(Order.sequence), 0)).where(
                    Order.branch_id == branch.id, Order.service_date == day
                )
            )
        ).scalar_one() + 1
        order = Order(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            branch_id=branch.id,
            table_session_id=table_session_id,
            reservation_id=reservation_id,
            customer_id=customer_id,
            placed_by=placed_by,
            service_date=day,
            sequence=seq,
            number=f"{seq:03d}",
            order_type=order_type,
            source=source,
            status="placed",
            subtotal=_money(subtotal),
            tax_total=_money(tax),
            total=_money(subtotal + tax),
            notes=data.notes.strip(),
            idempotency_key=idem,
        )
        try:
            async with session.begin_nested():
                session.add(order)
                await session.flush()
            break
        except IntegrityError as exc:
            if idem and "uq_orders_idempotency" in str(exc.orig):
                existing = await _find_idempotent(session, idem)
                if existing is not None:
                    return existing, False
            if "uq_orders_branch_day_sequence" not in str(exc.orig):
                raise
    else:  # pragma: no cover - five collisions in a row
        raise ConflictError("Busy right now, please try again.", code="ORDER_NUMBER_BUSY")
    for ln in lines:
        session.add(OrderItem(tenant_id=tenant_id, order_id=order.id, **ln))
    session.add(OrderStatusHistory(tenant_id=tenant_id, order_id=order.id, to_status="placed", by_user_id=placed_by))
    return order, True


def _scoped_key(actor: str, key: str | None) -> str | None:
    """Keys are namespaced by who sent them, so two guests can never collide."""
    if not key:
        return None
    clean = key.strip()[:60]
    if not clean:
        return None
    return f"{actor}:{clean}"[:80]


# ---------- output ----------


async def orders_out(
    session: AsyncSession, orders: list[Order], *, viewer: str = "staff", tenant: Tenant | None = None
) -> list[OrderOut]:
    if not orders:
        return []
    ids = [o.id for o in orders]
    lines: dict[uuid.UUID, list[OrderLineOut]] = defaultdict(list)
    for li in (
        await session.execute(select(OrderItem).where(OrderItem.order_id.in_(ids)).order_by(OrderItem.sort_order))
    ).scalars():
        lines[li.order_id].append(
            OrderLineOut(
                id=li.id,
                menu_item_id=li.menu_item_id,
                name=li.name,
                variant_name=li.variant_name,
                addons=[OrderAddonOut(name=a["name"], price=Decimal(str(a["price"]))) for a in li.addons],
                food_class=li.food_class,
                unit_price=li.unit_price,
                quantity=li.quantity,
                tax_pct=li.tax_pct,
                line_total=li.line_total,
                tax_amount=li.tax_amount,
                instructions=li.instructions,
            )
        )
    sids = {o.table_session_id for o in orders if o.table_session_id}
    sessions = (
        {s.id: s for s in (await session.execute(select(TableSession).where(TableSession.id.in_(sids)))).scalars()}
        if sids
        else {}
    )
    labels: dict[uuid.UUID, list[str]] = defaultdict(list)
    if sids:
        for sid, label in (
            await session.execute(
                select(TableAssignment.table_session_id, RestaurantTable.label)
                .join(RestaurantTable, RestaurantTable.id == TableAssignment.table_id)
                .where(TableAssignment.table_session_id.in_(sids))
                .order_by(TableAssignment.released_at.is_(None).desc(), TableAssignment.assigned_at.desc())
            )
        ).tuples():
            if label not in labels[sid]:
                labels[sid].append(label)
    rids = {o.reservation_id for o in orders if o.reservation_id}
    reservations = (
        {r.id: r for r in (await session.execute(select(Reservation).where(Reservation.id.in_(rids)))).scalars()}
        if rids
        else {}
    )
    out = []
    for o in orders:
        s = sessions.get(o.table_session_id) if o.table_session_id else None
        r = reservations.get(o.reservation_id) if o.reservation_id else None
        cancellable = GUEST_CANCELLABLE if viewer == "guest" else STAFF_CANCELLABLE
        out.append(
            OrderOut(
                id=o.id,
                branch_id=o.branch_id,
                number=o.number,
                order_type=o.order_type,
                source=o.source,
                status=o.status,  # type: ignore[arg-type]
                table_session_id=o.table_session_id,
                session_code=s.public_code if s else None,
                table_labels=labels.get(o.table_session_id, []) if o.table_session_id else [],
                reservation_id=o.reservation_id,
                reservation_code=r.code if r else None,
                reservation_starts_at=r.starts_at if r else None,
                guest_name=(s.guest_name if s else None) or (r.guest_name if r else None),
                items=lines.get(o.id, []),
                subtotal=o.subtotal,
                tax_total=o.tax_total,
                total=o.total,
                notes=o.notes,
                placed_at=o.placed_at,
                accepted_at=o.accepted_at,
                preparing_at=o.preparing_at,
                ready_at=o.ready_at,
                served_at=o.served_at,
                cancelled_at=o.cancelled_at,
                cancel_reason=o.cancel_reason,
                can_cancel=o.status in cancellable,
                restaurant_name=tenant.name if tenant else None,
                restaurant_slug=tenant.slug if tenant else None,
            )
        )
    return out


async def _one(session: AsyncSession, o: Order, **kw) -> OrderOut:  # type: ignore[no-untyped-def]
    return (await orders_out(session, [o], **kw))[0]


# ---------- guests at a table (code + PIN) ----------


async def join_table(session: AsyncSession, tenant: Tenant, data: TableJoinIn, ip: str | None) -> TableJoinOut:
    """Code + PIN → a table token (12 h). Attempts are limited per code and per device IP."""
    await rate_limit.hit(f"table-join:{tenant.id}:{data.code}", limit=5, window_seconds=900)
    if ip:
        await rate_limit.hit(f"table-join-ip:{ip}", limit=30, window_seconds=900)
    s = (
        await session.execute(
            select(TableSession).where(TableSession.public_code == data.code, TableSession.status != "closed")
        )
    ).scalar_one_or_none()
    if s is None or not hmac.compare_digest(s.pin_hash, hash_otp(data.code, data.pin)):
        raise UnauthorizedError("That code and PIN don't match an open table.", code="INVALID_TABLE_PIN")
    token, exp = create_table_token(s.id, tenant.id, s.pin_hash)
    return TableJoinOut(token=token, expires_at=exp, session_id=s.id)


async def table_from_token(session: AsyncSession, token: str | None) -> tuple[TableSession, Tenant]:
    if not token:
        raise UnauthorizedError("Enter your table code and PIN.", code="TABLE_TOKEN_REQUIRED")
    claims = decode_table_token(token)
    await use_tenant(session, claims.tenant_id)
    s = await session.get(TableSession, claims.session_id)
    tenant = await session.get(Tenant, claims.tenant_id)
    if s is None or tenant is None or not s.pin_hash.startswith(claims.pin_version):
        raise UnauthorizedError("Enter your table code and PIN again.", code="TABLE_TOKEN_INVALID")
    return s, tenant


async def _session_orders(session: AsyncSession, s: TableSession) -> list[Order]:
    return list(
        (
            await session.execute(select(Order).where(Order.table_session_id == s.id).order_by(Order.placed_at.desc()))
        ).scalars()
    )


async def table_view(session: AsyncSession, token: str | None) -> TableSessionView:
    s, tenant = await table_from_token(session, token)
    branch = await session.get(Branch, s.branch_id)
    orders = await _session_orders(session, s)
    out = await orders_out(session, orders, viewer="guest")
    live = [o for o in orders if o.status != "cancelled"]
    labels = (
        (
            await session.execute(
                select(RestaurantTable.label)
                .join(TableAssignment, TableAssignment.table_id == RestaurantTable.id)
                .where(TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    from app.api.deps import feature_enabled  # local: avoid import cycle

    return TableSessionView(
        session_id=s.id,
        code=s.public_code,
        status=s.status,
        restaurant_name=tenant.name,
        restaurant_slug=tenant.slug,
        branch_id=s.branch_id,
        branch_name=branch.name if branch else "",
        table_labels=list(labels),
        party_size=s.party_size,
        guest_name=s.guest_name,
        opened_at=s.opened_at,
        orders=out,
        subtotal=sum((o.subtotal for o in live), Decimal("0")),
        tax_total=sum((o.tax_total for o in live), Decimal("0")),
        total=sum((o.total for o in live), Decimal("0")),
        ordering_open=s.status == "open" and await feature_enabled(session, tenant.id, "ordering"),
        server_time=_now(),
    )


async def _require_ordering(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    from app.api.deps import feature_enabled  # local: avoid import cycle

    if not await feature_enabled(session, tenant_id, "ordering"):
        raise AppError("Online ordering is not available here.", code="FEATURE_UNAVAILABLE", status_code=404)


async def guest_order(
    session: AsyncSession, token: str | None, data: OrderIn, idem: str | None, user: User | None
) -> tuple[OrderOut, bool]:
    s, tenant = await table_from_token(session, token)
    await _require_ordering(session, tenant.id)
    if s.status != "open":
        raise ConflictError("This table is closed for new orders.", code="SESSION_CLOSED")
    branch = await session.get(Branch, s.branch_id)
    assert branch is not None
    order, created = await _create(
        session,
        tenant_id=tenant.id,
        branch=branch,
        data=data,
        order_type="booking" if s.source == "reservation" else "walk_in",
        source="guest",
        at=_now(),
        table_session_id=s.id,
        customer_id=user.id if user else None,
        idem=_scoped_key(f"s{s.id}", idem),
    )
    if created:
        await session.commit()
        await _changed(order)
    return await _one(session, order, viewer="guest"), created


async def guest_cancel(session: AsyncSession, token: str | None, order_id: uuid.UUID) -> OrderOut:
    s, _ = await table_from_token(session, token)
    o = (
        await session.execute(
            select(Order).where(Order.id == order_id, Order.table_session_id == s.id).with_for_update()
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError("Order not found.")
    if o.status not in GUEST_CANCELLABLE:
        raise ConflictError("The kitchen has already started on this order — ask your waiter.", code="NOT_CANCELLABLE")
    _set(session, o, "cancelled", None, "guest_cancelled")
    o.cancel_reason = "Cancelled by guest"
    await session.commit()
    await _changed(o)
    return await _one(session, o, viewer="guest")


# ---------- paid pre-orders (signed-in customer) ----------


async def _my_reservation(session: AsyncSession, user: User, reservation_id: uuid.UUID) -> Reservation:
    await use_system(session)
    r = (
        await session.execute(
            select(Reservation).where(Reservation.id == reservation_id, Reservation.customer_id == user.id)
        )
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Booking not found.")
    await use_tenant(session, r.tenant_id)
    return r


async def preorder(
    session: AsyncSession, user: User, reservation_id: uuid.UUID, data: OrderIn, idem: str | None
) -> tuple[OrderOut, bool]:
    r = await _my_reservation(session, user, reservation_id)
    await _require_ordering(session, r.tenant_id)
    if r.type != "paid":
        raise ForbiddenError("Pre-ordering is only available with a paid booking.", code="PREORDER_NOT_ALLOWED")
    if r.status == "pending_payment":
        raise ForbiddenError("Complete the booking payment to pre-order.", code="PREORDER_NOT_ALLOWED")
    if r.status not in ("confirmed", "checked_in"):
        raise ConflictError("This booking is no longer active.", code="RESERVATION_NOT_ACTIVE")
    branch = await session.get(Branch, r.branch_id)
    tenant = await session.get(Tenant, r.tenant_id)
    assert branch is not None and tenant is not None
    arrived = r.status == "checked_in" and r.table_session_id is not None
    order, created = await _create(
        session,
        tenant_id=r.tenant_id,
        branch=branch,
        data=data,
        order_type="booking" if arrived else "paid_preorder",
        source="guest",
        at=_now() if arrived else r.starts_at,  # dishes must be served at the booking time
        table_session_id=r.table_session_id if arrived else None,
        reservation_id=r.id,
        customer_id=user.id,
        idem=_scoped_key(f"u{user.id}", idem),
    )
    if created:
        await session.commit()
        await _changed(order)
    return await _one(session, order, viewer="guest", tenant=tenant), created


async def reservation_orders(session: AsyncSession, user: User, reservation_id: uuid.UUID) -> list[OrderOut]:
    r = await _my_reservation(session, user, reservation_id)
    tenant = await session.get(Tenant, r.tenant_id)
    orders = (
        (await session.execute(select(Order).where(Order.reservation_id == r.id).order_by(Order.placed_at)))
        .scalars()
        .all()
    )
    return await orders_out(session, list(orders), viewer="guest", tenant=tenant)


async def my_orders(session: AsyncSession, user: User) -> list[OrderOut]:
    await use_system(session)
    orders = (
        (
            await session.execute(
                select(Order).where(Order.customer_id == user.id).order_by(Order.placed_at.desc()).limit(50)
            )
        )
        .scalars()
        .all()
    )
    tenants = (
        {
            t.id: t
            for t in (
                await session.execute(select(Tenant).where(Tenant.id.in_({o.tenant_id for o in orders})))
            ).scalars()
        }
        if orders
        else {}
    )
    out: list[OrderOut] = []
    for o in orders:
        out.extend(await orders_out(session, [o], viewer="guest", tenant=tenants.get(o.tenant_id)))
    return out


async def cancel_mine(session: AsyncSession, user: User, order_id: uuid.UUID) -> OrderOut:
    await use_system(session)
    o = (
        await session.execute(select(Order).where(Order.id == order_id, Order.customer_id == user.id).with_for_update())
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError("Order not found.")
    if o.status not in GUEST_CANCELLABLE:
        raise ConflictError("The kitchen has already started on this order.", code="NOT_CANCELLABLE")
    _set(session, o, "cancelled", user.id, "guest_cancelled")
    o.cancel_reason = "Cancelled by guest"
    await session.commit()
    await _changed(o)
    return await _one(session, o, viewer="guest", tenant=await session.get(Tenant, o.tenant_id))


async def attach_preorders(session: AsyncSession, reservation_id: uuid.UUID, table_session_id: uuid.UUID) -> int:
    """Confirm Arrival: the paid pre-orders join the guests' table session (caller commits)."""
    res = await session.execute(
        update(Order)
        .where(Order.reservation_id == reservation_id, Order.table_session_id.is_(None))
        .values(table_session_id=table_session_id)
    )
    return res.rowcount or 0


# ---------- staff ----------


async def staff_order(
    session: AsyncSession, ctx: TenantContext, data: StaffOrderIn, idem: str | None
) -> tuple[OrderOut, bool]:
    s = await session.get(TableSession, data.table_session_id)
    if s is None:
        raise NotFoundError("Table session not found.")
    if not ctx.can_act_in_branch("orders.create", s.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    if s.status != "open":
        raise ConflictError("This table is closed for new orders.", code="SESSION_CLOSED")
    branch = await session.get(Branch, s.branch_id)
    assert branch is not None
    order, created = await _create(
        session,
        tenant_id=ctx.tenant_id,
        branch=branch,
        data=data,
        order_type="staff",
        source="staff",
        at=_now(),
        table_session_id=s.id,
        placed_by=ctx.user_id,
        idem=_scoped_key(f"m{ctx.user_id}", idem),
    )
    if created:
        await session.commit()
        await _changed(order)
    return await _one(session, order), created


async def list_orders(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, *, active: bool, day: str | None = None
) -> list[OrderOut]:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise NotFoundError("Branch not found.")
    if not (ctx.can_act_in_branch("orders.view", branch_id) or ctx.can_act_in_branch("kitchen.operate", branch_id)):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    stmt = select(Order).where(Order.branch_id == branch_id)
    if active:
        stmt = stmt.where(Order.status.in_(ORDER_ACTIVE)).order_by(Order.placed_at)
    else:
        from datetime import date as _date

        d = _date.fromisoformat(day) if day else _now().astimezone(ZoneInfo(branch.timezone)).date()
        stmt = stmt.where(Order.service_date == d).order_by(Order.placed_at.desc())
    return await orders_out(session, list((await session.execute(stmt)).scalars()))


def _set(session: AsyncSession, o: Order, to: str, by: uuid.UUID | None, note: str | None = None) -> None:
    now = _now()
    session.add(
        OrderStatusHistory(
            tenant_id=o.tenant_id, order_id=o.id, from_status=o.status, to_status=to, by_user_id=by, note=note
        )
    )
    o.status = to
    if to == "accepted":
        o.accepted_at = now
    elif to == "preparing":
        o.preparing_at = now
        o.accepted_at = o.accepted_at or now
    elif to == "ready":
        o.ready_at = now
    elif to == "served":
        o.served_at, o.served_by = now, by
    elif to == "cancelled":
        o.cancelled_at, o.cancelled_by = now, by


async def _staff_get(session: AsyncSession, order_id: uuid.UUID) -> Order:
    o = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if o is None:
        raise NotFoundError("Order not found.")
    return o


async def set_status(session: AsyncSession, ctx: TenantContext, order_id: uuid.UUID, to: str) -> OrderOut:
    o = await _staff_get(session, order_id)
    perm = TRANSITIONS.get((o.status, to))
    if perm is None:
        raise ConflictError(
            f"An order that is {o.status} cannot become {to}.",
            code="INVALID_TRANSITION",
            details={"from": o.status, "to": to},
        )
    if not ctx.can_act_in_branch(perm, o.branch_id):
        msg = (
            "Only waiters/managers can mark orders as served."
            if to == "served"
            else "You cannot update kitchen orders."
        )
        raise ForbiddenError(msg, code="PERMISSION_DENIED", details={"permission": perm})
    if o.order_type == "paid_preorder" and o.table_session_id is None and to in ("accepted", "preparing"):
        raise ConflictError(
            "This is a pre-order — start it when the guests arrive (Confirm arrival).", code="PREORDER_NOT_ARRIVED"
        )
    _set(session, o, to, ctx.user_id)
    await session.commit()
    await _changed(o)
    if to == "ready" and o.customer_id:
        await notify_guest(
            user_id=o.customer_id,
            phone=None,
            event="order.ready",
            title=f"Order #{o.number} is ready",
            body="It will be at your table in a moment.",
        )
    return await _one(session, o)


async def staff_cancel(session: AsyncSession, ctx: TenantContext, order_id: uuid.UUID, reason: str) -> OrderOut:
    o = await _staff_get(session, order_id)
    if not ctx.can_act_in_branch("orders.cancel", o.branch_id):
        raise ForbiddenError("You cannot cancel orders.", code="PERMISSION_DENIED")
    if o.status not in STAFF_CANCELLABLE:
        raise ConflictError(f"An order that is {o.status} cannot be cancelled.", code="NOT_CANCELLABLE")
    _set(session, o, "cancelled", ctx.user_id, reason or None)
    o.cancel_reason = reason.strip() or "Cancelled by the restaurant"
    write_audit(
        session,
        action="order.cancelled",
        entity="order",
        entity_id=o.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"reason": o.cancel_reason},
    )
    await session.commit()
    await _changed(o)
    return await _one(session, o)


async def today_counts(session: AsyncSession, branch_id: uuid.UUID | None, day) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """(orders placed today, orders in progress) for the dashboard. RLS scopes to the tenant."""
    stmt = select(Order.status, func.count()).where(Order.service_date == day)
    if branch_id:
        stmt = stmt.where(Order.branch_id == branch_id)
    rows = (await session.execute(stmt.group_by(Order.status))).tuples().all()
    total = sum(n for st, n in rows if st != "cancelled")
    active = sum(n for st, n in rows if st in ORDER_ACTIVE)
    return total, active

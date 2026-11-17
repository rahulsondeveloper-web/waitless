"""Reservations (PRD §12): free and paid bookings, arrival confirmation, expiry, refunds.

- Slots come from the branch's opening hours, the booking policy and the tables that are free.
- Each booking holds one table over [start, start + dining time). The database refuses overlapping
  holds (GiST exclusion constraint), so double-booking is impossible even under races.
- Paid bookings are confirmed only by a verified payment webhook (never by the browser).
- The expiry job never touches a checked-in reservation (PRD §12 "Never release a checked-in table").
"""

import logging
import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import use_system, use_tenant
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.integrations.payments.gateway import PaymentEvent, get_gateway
from app.models import Branch, Tenant, User
from app.models.booking import (
    RESERVATION_ACTIVE,
    Reservation,
    ReservationPayment,
    ReservationPolicy,
    ReservationTable,
)
from app.models.profile import BusinessHours
from app.models.tables import RestaurantTable
from app.schemas.booking import (
    Availability,
    BookingOptions,
    BookingResult,
    CheckoutOut,
    PolicyIn,
    PolicyOut,
    ReservationIn,
    ReservationOut,
    Slot,
    StaffReservationIn,
)
from app.schemas.tables import SeatedOut, SeatIn
from app.services import tables as tables_svc
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.notify import notify_guest
from app.services.queue import policy_for
from app.websocket.bus import branch_staff_room, emit

log = logging.getLogger(__name__)
RESERVE_TABLE_MINUTES_BEFORE = 30  # table turns "reserved" on the board this long before the booking


def _now() -> datetime:
    return datetime.now(UTC)


def snapshot(p: ReservationPolicy) -> dict:
    return {
        "grace_minutes": p.grace_minutes,
        "dining_minutes": p.dining_minutes,
        "free_cancel_hours": p.free_cancel_hours,
        "refund_on_no_show": p.refund_on_no_show,
        "booking_fee": str(p.booking_fee),
    }


async def _changed(tenant_id: uuid.UUID, branch_id: uuid.UUID) -> None:
    await emit("reservations.changed", {"branch_id": str(branch_id)}, branch_staff_room(tenant_id, branch_id))
    await emit("tables.changed", {"branch_id": str(branch_id)}, branch_staff_room(tenant_id, branch_id))


# ---------- policy ----------


def _policy_out(p: ReservationPolicy) -> PolicyOut:
    return PolicyOut(
        branch_id=p.branch_id,
        **{k: getattr(p, k) if getattr(p, k) is not None else v.default for k, v in PolicyIn.model_fields.items()},
    )


async def get_policy(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> PolicyOut:
    branch = await tables_svc._branch(session, ctx, branch_id, "reservations.view")
    return _policy_out(await policy_for(session, branch))


async def set_policy(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, data: PolicyIn) -> PolicyOut:
    branch = await tables_svc._branch(session, ctx, branch_id, "reservations.policy.manage")
    if data.paid_enabled:
        from app.api.deps import feature_enabled  # local: avoid import cycle

        if not await feature_enabled(session, ctx.tenant_id, "reservations.paid"):
            raise AppError("Your plan does not include paid bookings.", code="PLAN_FEATURE_REQUIRED", status_code=402)
    p = await session.get(ReservationPolicy, branch.id)
    if p is None:
        p = ReservationPolicy(branch_id=branch.id, tenant_id=ctx.tenant_id)
        session.add(p)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    write_audit(
        session,
        action="reservation_policy.updated",
        entity="branch",
        entity_id=branch.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff=data.model_dump(mode="json"),
    )
    await session.commit()
    return _policy_out(p)


# ---------- availability ----------


def _windows_for(day: date, tz: ZoneInfo, hours: list[BusinessHours]) -> list[tuple[datetime, datetime]]:
    by_day = {h.weekday: h for h in hours}
    h = by_day.get(day.weekday())
    if h is None or h.is_closed or h.opens_at is None or h.closes_at is None:
        return []
    start = datetime.combine(day, h.opens_at, tz)
    end_day = day + timedelta(days=1) if h.closes_at <= h.opens_at else day
    end = datetime.combine(end_day, h.closes_at, tz)
    if h.closes_at == time(23, 59):
        end += timedelta(minutes=1)
    return [(start, end)]


async def _holds(session: AsyncSession, table_ids: list[uuid.UUID], start: datetime, end: datetime) -> dict:
    rows = (
        (
            await session.execute(
                select(ReservationTable.table_id, ReservationTable.slot).where(
                    ReservationTable.table_id.in_(table_ids),
                    ReservationTable.active,
                    ReservationTable.slot.overlaps(Range(start, end)),
                )
            )
        )
        .tuples()
        .all()
    )
    out: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
    for tid, rng in rows:
        out.setdefault(tid, []).append((rng.lower, rng.upper))
    return out


def _free(holds: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    return all(not (s < end and start < e) for s, e in holds)


async def _suitable_tables(session: AsyncSession, branch_id: uuid.UUID, party: int) -> list[RestaurantTable]:
    return list(
        (
            await session.execute(
                select(RestaurantTable)
                .where(
                    RestaurantTable.branch_id == branch_id, RestaurantTable.is_active, RestaurantTable.capacity >= party
                )
                .order_by(RestaurantTable.capacity, RestaurantTable.sort_order)
            )
        ).scalars()
    )


async def availability(session: AsyncSession, tenant: Tenant, branch: Branch, day: date, party: int) -> Availability:
    p = await policy_for(session, branch)
    tz = ZoneInfo(branch.timezone)
    base = dict(
        branch_id=branch.id,
        date=day,
        timezone=branch.timezone,
        party_size=party,
        free_enabled=p.free_enabled,
        paid_enabled=p.paid_enabled,
        booking_fee=p.booking_fee,
        currency=str((tenant.settings or {}).get("currency", "INR")),
        grace_minutes=p.grace_minutes,
        free_cancel_hours=p.free_cancel_hours,
    )
    if not p.accepts_reservations:
        return Availability(**base, slots=[], message="This branch is not taking reservations online.")
    if not (p.min_party <= party <= p.max_party):
        return Availability(**base, slots=[], message=f"Online bookings are for {p.min_party}–{p.max_party} guests.")
    today_local = _now().astimezone(tz).date()
    if day < today_local or day > today_local + timedelta(days=p.max_advance_days):
        return Availability(**base, slots=[], message=f"Book up to {p.max_advance_days} days ahead.")
    hours = list((await session.execute(select(BusinessHours).where(BusinessHours.branch_id == branch.id))).scalars())
    windows = _windows_for(day, tz, hours)
    if not windows:
        return Availability(**base, slots=[], message="Closed on this day.")
    tables = await _suitable_tables(session, branch.id, party)
    if not tables:
        return Availability(**base, slots=[], message="No table here seats that many guests.")

    dining = timedelta(minutes=p.dining_minutes)
    earliest = _now() + timedelta(minutes=p.min_lead_minutes)
    slots: list[Slot] = []
    for open_at, close_at in windows:
        last_start = close_at - min(dining, timedelta(minutes=60))
        holds = await _holds(session, [t.id for t in tables], open_at, close_at + dining)
        t = open_at
        while t <= last_start:
            if t >= earliest:
                ok = any(_free(holds.get(tb.id, []), t, t + dining) for tb in tables)
                slots.append(Slot(starts_at=t.astimezone(UTC), label=t.strftime("%H:%M"), available=ok))
            t += timedelta(minutes=p.slot_minutes)
    return Availability(**base, slots=slots, message=None if slots else "No more times today.")


async def options(session: AsyncSession, tenant: Tenant) -> list[BookingOptions]:
    branches = (
        await session.execute(select(Branch).where(Branch.is_active).order_by(Branch.is_primary.desc()))
    ).scalars()
    out = []
    for b in branches:
        p = await policy_for(session, b)
        out.append(
            BookingOptions(
                branch_id=b.id,
                branch_name=b.name,
                accepts_reservations=p.accepts_reservations,
                accepts_queue=p.accepts_queue,
                free_enabled=p.free_enabled,
                paid_enabled=p.paid_enabled,
                booking_fee=p.booking_fee,
                currency=str((tenant.settings or {}).get("currency", "INR")),
                min_party=p.min_party,
                max_party=p.max_party,
                max_advance_days=p.max_advance_days,
                grace_minutes=p.grace_minutes,
                free_cancel_hours=p.free_cancel_hours,
            )
        )
    return out


# ---------- output ----------


async def reservation_out(session: AsyncSession, r: Reservation, *, tenant: Tenant | None = None) -> ReservationOut:
    labels = (
        (
            await session.execute(
                select(RestaurantTable.label)
                .join(ReservationTable, ReservationTable.table_id == RestaurantTable.id)
                .where(ReservationTable.reservation_id == r.id)
                .order_by(ReservationTable.active.desc())
            )
        )
        .scalars()
        .all()
    )
    pay = (
        await session.execute(
            select(ReservationPayment)
            .where(ReservationPayment.reservation_id == r.id)
            .order_by(ReservationPayment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    branch = await session.get(Branch, r.branch_id)
    now = _now()
    return ReservationOut(
        id=r.id,
        code=r.code,
        branch_id=r.branch_id,
        branch_name=branch.name if branch else None,
        restaurant_name=tenant.name if tenant else None,
        restaurant_slug=tenant.slug if tenant else None,
        guest_name=r.guest_name,
        phone=r.phone,
        party_size=r.party_size,
        type=r.type,  # type: ignore[arg-type]
        status=r.status,
        starts_at=r.starts_at,
        ends_at=r.ends_at,
        arrival_deadline=r.arrival_deadline,
        payment_due_at=r.payment_due_at,
        booking_fee=r.booking_fee,
        notes=r.notes,
        table_labels=list(dict.fromkeys(labels)),
        staff_confirmed_at=r.staff_confirmed_at,
        ended_at=r.ended_at,
        end_reason=r.end_reason,
        payment_status=pay.status if pay else None,
        refunded_amount=pay.refunded_amount if pay else None,
        can_cancel=r.status in ("pending_payment", "confirmed") and now < r.starts_at,
        can_preorder=r.type == "paid" and r.status in ("confirmed", "checked_in"),
    )


# ---------- creating ----------


def _code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "R" + "".join(secrets.choice(alphabet) for _ in range(6))


async def _hold_table(session: AsyncSession, r: Reservation, tables: list[RestaurantTable]) -> RestaurantTable:
    """Smallest free table first; the exclusion constraint decides races."""
    for t in tables:
        try:
            async with session.begin_nested():
                session.add(
                    ReservationTable(
                        tenant_id=r.tenant_id, reservation_id=r.id, table_id=t.id, slot=Range(r.starts_at, r.ends_at)
                    )
                )
            return t
        except IntegrityError:
            continue
    raise ConflictError("That time was just taken. Please choose another time.", code="SLOT_TAKEN")


async def _validate_slot(
    session: AsyncSession, tenant: Tenant, branch: Branch, data: ReservationIn
) -> tuple[ReservationPolicy, list[RestaurantTable]]:
    p = await policy_for(session, branch)
    if not p.accepts_reservations:
        raise ConflictError("This branch is not taking reservations online.", code="RESERVATIONS_CLOSED")
    if data.type == "free" and not p.free_enabled:
        raise ConflictError("Free bookings are not offered here.", code="BOOKING_TYPE_UNAVAILABLE")
    if data.type == "paid" and not p.paid_enabled:
        raise ConflictError("Paid bookings are not offered here.", code="BOOKING_TYPE_UNAVAILABLE")
    local_day = data.starts_at.astimezone(ZoneInfo(branch.timezone)).date()
    slots = await availability(session, tenant, branch, local_day, data.party_size)
    wanted = data.starts_at.astimezone(UTC)
    slot = next((s for s in slots.slots if s.starts_at == wanted), None)
    if slot is None:
        raise AppError(slots.message or "Choose one of the offered times.", code="INVALID_SLOT", status_code=422)
    if not slot.available:
        raise ConflictError("That time is fully booked. Please choose another time.", code="SLOT_TAKEN")
    return p, await _suitable_tables(session, branch.id, data.party_size)


async def _create(
    session: AsyncSession,
    *,
    tenant: Tenant,
    branch: Branch,
    data: ReservationIn,
    customer: User | None,
    guest_name: str,
    phone: str | None,
    source: str,
) -> BookingResult:
    p, tables = await _validate_slot(session, tenant, branch, data)
    starts = data.starts_at.astimezone(UTC)
    if customer is not None:
        clash = await session.execute(
            select(Reservation.id).where(
                Reservation.customer_id == customer.id,
                Reservation.branch_id == branch.id,
                Reservation.status.in_(RESERVATION_ACTIVE),
                Reservation.starts_at < starts + timedelta(minutes=p.dining_minutes),
                Reservation.ends_at > starts,
            )
        )
        if clash.first():
            raise ConflictError("You already have a booking here around that time.", code="DUPLICATE_BOOKING")
    r = Reservation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        branch_id=branch.id,
        code=_code(),
        customer_id=customer.id if customer else None,
        guest_name=guest_name,
        phone=phone,
        party_size=data.party_size,
        type=data.type,
        status="pending_payment" if data.type == "paid" else "confirmed",
        starts_at=starts,
        ends_at=starts + timedelta(minutes=p.dining_minutes),
        arrival_deadline=starts + timedelta(minutes=p.grace_minutes),
        payment_due_at=_now() + timedelta(minutes=get_settings().payment_hold_minutes) if data.type == "paid" else None,
        booking_fee=p.booking_fee if data.type == "paid" else Decimal("0"),
        notes=data.notes.strip(),
        policy_snapshot=snapshot(p),
        source=source,
    )
    session.add(r)
    await session.flush()
    await _hold_table(session, r, tables)

    checkout = None
    if data.type == "paid":
        gateway = get_gateway()
        order = await gateway.create_order(
            r.booking_fee, "INR", receipt=r.code, notes={"kind": "reservation", "reservation_id": str(r.id)}
        )
        session.add(
            ReservationPayment(
                tenant_id=tenant.id,
                reservation_id=r.id,
                provider=order.provider,
                provider_order_id=order.order_id,
                amount=order.amount,
                currency=order.currency,
            )
        )
        checkout = CheckoutOut(
            provider=order.provider,
            order_id=order.order_id,
            amount=order.amount,
            currency=order.currency,
            checkout=order.checkout,
        )
    await session.commit()
    await _changed(tenant.id, branch.id)
    if r.status == "confirmed":
        await _notify_confirmed(r, tenant)
    return BookingResult(reservation=await reservation_out(session, r, tenant=tenant), payment=checkout)


async def _notify_confirmed(r: Reservation, tenant: Tenant) -> None:
    local = r.starts_at.astimezone(ZoneInfo("Asia/Kolkata"))
    await notify_guest(
        user_id=r.customer_id,
        phone=r.phone,
        event="reservation.confirmed",
        title=f"Table booked at {tenant.name}",
        body=f"{local:%a %d %b, %H:%M} · {r.party_size} guests · ref {r.code}",
        link=f"/r/{tenant.slug}/reservations",
    )


async def book(session: AsyncSession, tenant: Tenant, user: User, data: ReservationIn) -> BookingResult:
    """Guest booking (session scoped to the tenant)."""
    if not user.phone:
        raise AppError("Add a verified mobile number to book a table.", code="PHONE_REQUIRED", status_code=422)
    branch = (
        await session.execute(select(Branch).where(Branch.id == data.branch_id, Branch.is_active))
    ).scalar_one_or_none()
    if branch is None:
        raise NotFoundError("Branch not found.")
    name = (data.guest_name or user.full_name or "Guest").strip()[:80]
    return await _create(
        session,
        tenant=tenant,
        branch=branch,
        data=data,
        customer=user,
        guest_name=name,
        phone=user.phone,
        source="online",
    )


async def staff_book(session: AsyncSession, ctx: TenantContext, data: StaffReservationIn) -> BookingResult:
    branch = await tables_svc._branch(session, ctx, data.branch_id, "reservations.manage")
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    return await _create(
        session,
        tenant=tenant,
        branch=branch,
        data=data,
        customer=None,
        guest_name=data.guest_name.strip(),
        phone=data.phone,
        source="staff",
    )


# ---------- payments ----------


async def _release(session: AsyncSession, r: Reservation) -> None:
    held = (
        (
            await session.execute(
                select(ReservationTable.table_id).where(
                    ReservationTable.reservation_id == r.id, ReservationTable.active
                )
            )
        )
        .scalars()
        .all()
    )
    await session.execute(update(ReservationTable).where(ReservationTable.reservation_id == r.id).values(active=False))
    if held and r.status != "checked_in":
        # A table shown as reserved for this booking becomes available again (never an occupied one).
        await session.execute(
            update(RestaurantTable)
            .where(RestaurantTable.id.in_(held), RestaurantTable.status == "reserved")
            .values(status="available")
        )


async def _refund(session: AsyncSession, r: Reservation, *, full: bool) -> Decimal:
    pay = (
        await session.execute(
            select(ReservationPayment)
            .where(ReservationPayment.reservation_id == r.id, ReservationPayment.status == "captured")
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pay is None or not full:
        return Decimal("0")
    amount = pay.amount - pay.refunded_amount
    if amount <= 0:
        return Decimal("0")
    await get_gateway(pay.provider).refund(pay.provider_payment_id or "", amount)
    pay.refunded_amount += amount
    pay.status = "refunded"
    return amount


async def process_payment_event(session: AsyncSession, provider: str, event: PaymentEvent) -> str:
    """Verified webhook → confirm the booking. Idempotent: repeated events change nothing."""
    await use_system(session)
    pay = (
        await session.execute(
            select(ReservationPayment)
            .where(ReservationPayment.provider == provider, ReservationPayment.provider_order_id == event.order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pay is None:
        return "unknown_order"
    if pay.status != "created":
        return "already_processed"
    await use_tenant(session, pay.tenant_id)
    r = (
        await session.execute(select(Reservation).where(Reservation.id == pay.reservation_id).with_for_update())
    ).scalar_one()
    tenant = await session.get(Tenant, pay.tenant_id)
    if event.type == "payment.failed":
        pay.status = "failed"
        await session.commit()
        return "failed"
    if event.amount != pay.amount:
        log.warning("payment amount mismatch for %s: %s != %s", pay.provider_order_id, event.amount, pay.amount)
        pay.status = "failed"
        await session.commit()
        return "amount_mismatch"
    pay.status, pay.provider_payment_id, pay.captured_at = "captured", event.payment_id, _now()
    if r.status == "pending_payment":
        r.status = "confirmed"
        r.payment_due_at = None
        result = "confirmed"
    else:
        # Paid too late (expired/cancelled meanwhile): give the money back automatically.
        await _refund(session, r, full=True)
        result = "refunded_late_payment"
    write_audit(
        session,
        action=f"reservation.payment_{result}",
        entity="reservation",
        entity_id=r.id,
        tenant_id=r.tenant_id,
        diff={"order_id": pay.provider_order_id, "amount": str(pay.amount)},
    )
    await session.commit()
    await _changed(r.tenant_id, r.branch_id)
    if result == "confirmed" and tenant:
        await _notify_confirmed(r, tenant)
    return result


async def retry_payment(session: AsyncSession, user: User, reservation_id: uuid.UUID) -> CheckoutOut:
    r = await _mine(session, user, reservation_id, lock=True)
    if r.status != "pending_payment":
        raise ConflictError("This booking does not need a payment.", code="NOT_PAYABLE")
    order = await get_gateway().create_order(
        r.booking_fee, "INR", receipt=r.code, notes={"kind": "reservation", "reservation_id": str(r.id)}
    )
    session.add(
        ReservationPayment(
            tenant_id=r.tenant_id,
            reservation_id=r.id,
            provider=order.provider,
            provider_order_id=order.order_id,
            amount=order.amount,
            currency=order.currency,
        )
    )
    await session.commit()
    return CheckoutOut(
        provider=order.provider,
        order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        checkout=order.checkout,
    )


# ---------- guest actions ----------


async def _mine(session: AsyncSession, user: User, reservation_id: uuid.UUID, *, lock: bool = False) -> Reservation:
    await use_system(session)
    stmt = select(Reservation).where(Reservation.id == reservation_id, Reservation.customer_id == user.id)
    if lock:
        stmt = stmt.with_for_update()
    r = (await session.execute(stmt)).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Booking not found.")
    return r


async def my_reservation(session: AsyncSession, user: User, reservation_id: uuid.UUID) -> ReservationOut:
    r = await _mine(session, user, reservation_id)
    return await reservation_out(session, r, tenant=await session.get(Tenant, r.tenant_id))


async def my_reservations(session: AsyncSession, user: User) -> list[ReservationOut]:
    await use_system(session)
    since = _now() - timedelta(days=60)
    rows = (
        (
            await session.execute(
                select(Reservation)
                .where(Reservation.customer_id == user.id, Reservation.starts_at >= since)
                .order_by(Reservation.starts_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await reservation_out(session, r, tenant=await session.get(Tenant, r.tenant_id)) for r in rows]


async def cancel_by_guest(session: AsyncSession, user: User, reservation_id: uuid.UUID) -> ReservationOut:
    r = await _mine(session, user, reservation_id, lock=True)
    if r.status not in ("pending_payment", "confirmed") or _now() >= r.starts_at:
        raise ConflictError("This booking can no longer be cancelled online.", code="NOT_CANCELLABLE")
    hours = int((r.policy_snapshot or {}).get("free_cancel_hours", 2))
    refundable = _now() <= r.starts_at - timedelta(hours=hours)
    await _end(session, r, "cancelled", "guest_cancelled")
    refunded = await _refund(session, r, full=refundable)
    write_audit(
        session,
        action="reservation.cancelled_by_guest",
        entity="reservation",
        entity_id=r.id,
        tenant_id=r.tenant_id,
        actor_user_id=user.id,
        diff={"refunded": str(refunded)},
    )
    await session.commit()
    await _changed(r.tenant_id, r.branch_id)
    return await reservation_out(session, r, tenant=await session.get(Tenant, r.tenant_id))


async def _end(session: AsyncSession, r: Reservation, status: str, reason: str) -> None:
    await _release(session, r)
    r.status, r.ended_at, r.end_reason = status, _now(), reason


# ---------- staff actions ----------


async def staff_list(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, day: date | None
) -> list[ReservationOut]:
    branch = await tables_svc._branch(session, ctx, branch_id, "reservations.view")
    tz = ZoneInfo(branch.timezone)
    d = day or _now().astimezone(tz).date()
    start = datetime.combine(d, time.min, tz)
    rows = (
        (
            await session.execute(
                select(Reservation)
                .where(
                    Reservation.branch_id == branch.id,
                    Reservation.starts_at >= start,
                    Reservation.starts_at < start + timedelta(days=1),
                )
                .order_by(Reservation.starts_at)
            )
        )
        .scalars()
        .all()
    )
    return [await reservation_out(session, r) for r in rows]


async def _staff_res(session: AsyncSession, ctx: TenantContext, reservation_id: uuid.UUID) -> Reservation:
    r = (
        await session.execute(select(Reservation).where(Reservation.id == reservation_id).with_for_update())
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Booking not found.")
    if not ctx.can_act_in_branch("reservations.manage", r.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return r


async def arrive(
    session: AsyncSession, ctx: TenantContext, reservation_id: uuid.UUID, table_id: uuid.UUID | None
) -> SeatedOut:
    """Staff verify the guests at the door → Confirm Arrival (PRD §12).

    Server time is the SLA start for paid pre-orders.
    """
    r = await _staff_res(session, ctx, reservation_id)
    if r.status != "confirmed":
        raise ConflictError(
            f"This booking is {r.status.replace('_', ' ')}.", code="NOT_ARRIVABLE", details={"status": r.status}
        )
    held = (
        await session.execute(
            select(ReservationTable).where(ReservationTable.reservation_id == r.id, ReservationTable.active)
        )
    ).scalar_one_or_none()
    target = table_id or (held.table_id if held else None)
    if target is None:
        raise AppError("Choose a table for the guests.", code="TABLE_REQUIRED", status_code=422)
    seated = await tables_svc.seat(
        session, ctx, SeatIn(table_id=target, party_size=r.party_size, guest_name=r.guest_name), source="reservation"
    )
    r = await _staff_res(session, ctx, reservation_id)
    r.status = "checked_in"
    r.staff_confirmed_at = _now()
    r.table_session_id = seated.session.id
    if held and held.table_id != target:
        held.active = False  # seated elsewhere; free the originally held table for other bookings
    from app.services.orders import attach_preorders  # local: orders imports reservation models only

    await attach_preorders(session, r.id, seated.session.id)
    write_audit(
        session,
        action="reservation.arrived",
        entity="reservation",
        entity_id=r.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"table_id": str(target)},
    )
    await session.commit()
    await _changed(ctx.tenant_id, r.branch_id)
    return seated


async def staff_cancel(session: AsyncSession, ctx: TenantContext, reservation_id: uuid.UUID) -> ReservationOut:
    r = await _staff_res(session, ctx, reservation_id)
    if r.status not in ("pending_payment", "confirmed"):
        raise ConflictError("This booking cannot be cancelled.", code="NOT_CANCELLABLE")
    await _end(session, r, "cancelled", "restaurant_cancelled")
    refunded = await _refund(session, r, full=True)  # restaurant cancels → full refund
    write_audit(
        session,
        action="reservation.cancelled_by_restaurant",
        entity="reservation",
        entity_id=r.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"refunded": str(refunded)},
    )
    await session.commit()
    await _changed(ctx.tenant_id, r.branch_id)
    await notify_guest(
        user_id=r.customer_id,
        phone=r.phone,
        event="reservation.cancelled",
        title="Your booking was cancelled by the restaurant",
        body=f"Ref {r.code}" + (" · your booking fee is refunded" if refunded else ""),
    )
    return await reservation_out(session, r)


async def no_show(session: AsyncSession, ctx: TenantContext, reservation_id: uuid.UUID) -> ReservationOut:
    r = await _staff_res(session, ctx, reservation_id)
    if r.status != "confirmed" or _now() < r.starts_at:
        raise ConflictError("Only confirmed bookings that have started can be marked as no-show.", code="NOT_NO_SHOW")
    await _end(session, r, "no_show", "marked_no_show")
    await _refund(session, r, full=bool((r.policy_snapshot or {}).get("refund_on_no_show")))
    await session.commit()
    await _changed(ctx.tenant_id, r.branch_id)
    return await reservation_out(session, r)


async def complete_for_session(session: AsyncSession, table_session_id: uuid.UUID) -> None:
    """Called when a reservation's table session closes (guests left)."""
    r = (
        await session.execute(select(Reservation).where(Reservation.table_session_id == table_session_id))
    ).scalar_one_or_none()
    if r is not None and r.status == "checked_in":
        await session.execute(
            update(ReservationTable).where(ReservationTable.reservation_id == r.id).values(active=False)
        )
        r.status, r.ended_at, r.end_reason = "completed", _now(), "guests_left"


# ---------- background job (worker) ----------


async def tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Runs every minute in the worker (and directly in tests). Never touches checked-in bookings."""
    now = now or _now()
    await use_system(session)
    counts = {"payment_expired": 0, "no_arrival_expired": 0, "tables_reserved": 0}

    stale = (
        (
            await session.execute(
                select(Reservation)
                .where(Reservation.status == "pending_payment", Reservation.payment_due_at < now)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for r in stale:
        await _end(session, r, "expired", "payment_timeout")
        counts["payment_expired"] += 1

    late = (
        (
            await session.execute(
                select(Reservation)
                .where(Reservation.status == "confirmed", Reservation.arrival_deadline < now)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for r in late:
        await _end(session, r, "expired", "no_arrival")
        await _refund(session, r, full=bool((r.policy_snapshot or {}).get("refund_on_no_show")))
        counts["no_arrival_expired"] += 1

    upcoming = (
        (
            await session.execute(
                select(ReservationTable.table_id)
                .join(Reservation, Reservation.id == ReservationTable.reservation_id)
                .where(
                    ReservationTable.active,
                    Reservation.status == "confirmed",
                    Reservation.starts_at <= now + timedelta(minutes=RESERVE_TABLE_MINUTES_BEFORE),
                    Reservation.arrival_deadline >= now,
                )
            )
        )
        .scalars()
        .all()
    )
    if upcoming:
        res = await session.execute(
            update(RestaurantTable)
            .where(RestaurantTable.id.in_(upcoming), RestaurantTable.status == "available", RestaurantTable.is_active)
            .values(status="reserved")
        )
        counts["tables_reserved"] = res.rowcount or 0
    await session.commit()

    touched = {(r.tenant_id, r.branch_id) for r in [*stale, *late]}
    if counts["tables_reserved"]:
        touched |= set(
            (
                await session.execute(
                    select(RestaurantTable.tenant_id, RestaurantTable.branch_id).where(RestaurantTable.id.in_(upcoming))
                )
            ).tuples()
        )
    for tenant_id, branch_id in touched:
        await _changed(tenant_id, branch_id)
    for r in late:
        await notify_guest(
            user_id=r.customer_id,
            phone=r.phone,
            event="reservation.expired",
            title="Your booking has expired",
            body=f"Ref {r.code} · we held your table until the grace time.",
        )
    return counts


async def public_branch(session: AsyncSession, branch_id: uuid.UUID) -> Branch:
    b = (await session.execute(select(Branch).where(Branch.id == branch_id, Branch.is_active))).scalar_one_or_none()
    if b is None:
        raise NotFoundError("Branch not found.")
    return b

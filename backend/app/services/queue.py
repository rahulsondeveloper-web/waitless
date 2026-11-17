"""Digital queue (PRD §10) and wait-time estimates (decision D23).

Guests join from the storefront (or the QR code at the door) after verifying their mobile; staff add
walk-ins, call guests when a table is free, seat them (→ table session with code + PIN), reorder,
skip, mark no-shows. Every change is pushed live to the branch's staff and to guests in the line.
"""

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Branch, Tenant, User
from app.models.booking import QUEUE_ACTIVE, QueueEntry, ReservationPolicy
from app.models.tables import RestaurantTable, TableSession
from app.schemas.booking import QueueEntryOut, QueueJoinIn, StaffQueueIn, WaitTime
from app.schemas.tables import SeatedOut, SeatIn
from app.services import tables as tables_svc
from app.services.access import TenantContext
from app.services.notify import notify_guest
from app.websocket.bus import branch_queue_room, branch_staff_room, emit

DEFAULT_TURN_MINUTES = 45


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


async def policy_for(session: AsyncSession, branch: Branch) -> ReservationPolicy:
    p = await session.get(ReservationPolicy, branch.id)
    if p is not None:
        return p
    from app.schemas.booking import PolicyIn

    defaults = PolicyIn().model_dump()  # one source of truth for defaults; not persisted
    return ReservationPolicy(branch_id=branch.id, tenant_id=branch.tenant_id, **defaults)


async def _changed(tenant_id: uuid.UUID, branch_id: uuid.UUID) -> None:
    data = {"branch_id": str(branch_id)}
    await emit("queue.changed", data, branch_staff_room(tenant_id, branch_id))
    await emit("queue.changed", data, branch_queue_room(tenant_id, branch_id))


# ---------- estimates ----------


async def average_turn_minutes(session: AsyncSession, branch_id: uuid.UUID) -> int:
    """Average time a party keeps a table, from closed sessions of the last 14 days."""
    since = datetime.now(UTC) - timedelta(days=14)
    avg, n = (
        await session.execute(
            select(
                func.avg(func.extract("epoch", TableSession.closed_at - TableSession.opened_at) / 60),
                func.count(),
            ).where(
                TableSession.branch_id == branch_id,
                TableSession.status == "closed",
                TableSession.closed_at.is_not(None),
                TableSession.opened_at >= since,
            )
        )
    ).one()
    if not n or n < 5 or avg is None:
        return DEFAULT_TURN_MINUTES
    return int(min(180, max(20, float(avg))))


async def _tables_for(session: AsyncSession, branch_id: uuid.UUID, party: int) -> tuple[int, int]:
    suitable, free = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(RestaurantTable.status == "available"),
            ).where(
                RestaurantTable.branch_id == branch_id,
                RestaurantTable.is_active,
                RestaurantTable.capacity >= party,
            )
        )
    ).one()
    return int(suitable), int(free)


async def estimate_minutes(session: AsyncSession, branch_id: uuid.UUID, position: int, party: int) -> int | None:
    suitable, free = await _tables_for(session, branch_id, party)
    if suitable == 0:
        return None  # no table big enough: staff will arrange
    if position <= free:
        return 5
    turns = math.ceil((position - free) / suitable)
    return turns * await average_turn_minutes(session, branch_id)


# ---------- reading ----------


async def _active(session: AsyncSession, branch_id: uuid.UUID) -> list[QueueEntry]:
    return list(
        (
            await session.execute(
                select(QueueEntry)
                .where(QueueEntry.branch_id == branch_id, QueueEntry.status.in_(QUEUE_ACTIVE))
                .order_by(QueueEntry.position, QueueEntry.joined_at)
            )
        ).scalars()
    )


async def entry_out(
    session: AsyncSession, e: QueueEntry, *, active: list[QueueEntry] | None = None, tenant: Tenant | None = None
) -> QueueEntryOut:
    if active is None:
        active = await _active(session, e.branch_id)
    ids = [x.id for x in active]
    position = ids.index(e.id) + 1 if e.id in ids else 0
    eta = await estimate_minutes(session, e.branch_id, position, e.party_size) if position else None
    if e.status == "notified":
        eta = 0
    table_label = None
    if e.notified_table_id:
        t = await session.get(RestaurantTable, e.notified_table_id)
        table_label = t.label if t else None
    return QueueEntryOut(
        id=e.id,
        branch_id=e.branch_id,
        token=e.token,
        party_size=e.party_size,
        guest_name=e.guest_name,
        phone=e.phone,
        source=e.source,
        status=e.status,
        position=position,
        ahead=max(0, position - 1),
        estimated_wait_minutes=eta,
        joined_at=e.joined_at,
        notified_at=e.notified_at,
        ended_at=e.ended_at,
        notified_table_label=table_label,
        restaurant_name=tenant.name if tenant else None,
        restaurant_slug=tenant.slug if tenant else None,
    )


async def wait_time(session: AsyncSession, branch: Branch, party: int = 2) -> WaitTime:
    policy = await policy_for(session, branch)
    active = await _active(session, branch.id)
    _, free = await _tables_for(session, branch.id, party)
    eta = await estimate_minutes(session, branch.id, len(active) + 1, party) if policy.accepts_queue else None
    return WaitTime(
        branch_id=branch.id,
        accepting=policy.accepts_queue,
        waiting=len(active),
        estimated_wait_minutes=eta,
        free_tables=free,
    )


# ---------- joining ----------


async def _add(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    branch: Branch,
    party: int,
    name: str,
    phone: str | None,
    customer_id: uuid.UUID | None,
    source: str,
) -> QueueEntry:
    today = local_today(branch.timezone)
    for _ in range(5):  # sequence numbers are unique per branch per day; retry on a race
        seq, pos = (
            await session.execute(
                select(
                    func.coalesce(func.max(QueueEntry.sequence), 0),
                    func.coalesce(func.max(QueueEntry.position), 0),
                ).where(QueueEntry.branch_id == branch.id, QueueEntry.service_date == today)
            )
        ).one()
        entry = QueueEntry(
            tenant_id=tenant_id,
            branch_id=branch.id,
            service_date=today,
            sequence=seq + 1,
            token=f"A-{seq + 1:03d}",
            position=pos + 1,
            party_size=party,
            guest_name=name,
            phone=phone,
            customer_id=customer_id,
            source=source,
        )
        try:
            async with session.begin_nested():
                session.add(entry)
            return entry
        except IntegrityError as exc:
            if "one_active_per_customer" in str(exc.orig):
                raise ConflictError("You are already in the queue here.", code="ALREADY_IN_QUEUE") from exc
    raise AppError("The queue is busy. Please try again.", code="QUEUE_BUSY", status_code=503)


async def join(session: AsyncSession, tenant: Tenant, user: User, data: QueueJoinIn) -> QueueEntryOut:
    """Customer joins (session already scoped to the tenant)."""
    branch = (
        await session.execute(select(Branch).where(Branch.id == data.branch_id, Branch.is_active))
    ).scalar_one_or_none()
    if branch is None:
        raise NotFoundError("Branch not found.")
    policy = await policy_for(session, branch)
    if not policy.accepts_queue:
        raise ConflictError("This branch is not taking online queue entries right now.", code="QUEUE_CLOSED")
    if not user.phone:
        raise AppError("Add a verified mobile number to join the queue.", code="PHONE_REQUIRED", status_code=422)
    suitable, _ = await _tables_for(session, branch.id, data.party_size)
    if suitable == 0:
        raise ConflictError("No table here seats that many guests. Please call the restaurant.", code="PARTY_TOO_LARGE")
    entry = await _add(
        session,
        tenant_id=tenant.id,
        branch=branch,
        party=data.party_size,
        name=(data.guest_name or user.full_name or "Guest").strip()[:80],
        phone=user.phone,
        customer_id=user.id,
        source="online",
    )
    await session.commit()
    await _changed(tenant.id, branch.id)
    out = await entry_out(session, entry, tenant=tenant)
    await notify_guest(
        user_id=user.id,
        phone=user.phone,
        event="queue.token",
        title=f"You're in line at {tenant.name}",
        body=f"Token {entry.token} · about {out.estimated_wait_minutes or 5} min",
    )
    return out


async def staff_add(session: AsyncSession, ctx: TenantContext, data: StaffQueueIn) -> QueueEntryOut:
    branch = await tables_svc._branch(session, ctx, data.branch_id, "queue.manage")
    entry = await _add(
        session,
        tenant_id=ctx.tenant_id,
        branch=branch,
        party=data.party_size,
        name=data.guest_name.strip(),
        phone=data.phone,
        customer_id=None,
        source="staff",
    )
    await session.commit()
    await _changed(ctx.tenant_id, branch.id)
    return await entry_out(session, entry)


# ---------- staff actions ----------


async def staff_list(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, history: bool
) -> list[QueueEntryOut]:
    branch = await tables_svc._branch(session, ctx, branch_id, "queue.manage")
    active = await _active(session, branch.id)
    entries = active
    if history:
        entries = list(
            (
                await session.execute(
                    select(QueueEntry)
                    .where(
                        QueueEntry.branch_id == branch.id,
                        QueueEntry.service_date == local_today(branch.timezone),
                        QueueEntry.status.not_in(QUEUE_ACTIVE),
                    )
                    .order_by(QueueEntry.ended_at.desc())
                )
            ).scalars()
        )
    return [await entry_out(session, e, active=active) for e in entries]


async def _entry(session: AsyncSession, ctx: TenantContext, entry_id: uuid.UUID, *, lock: bool = True) -> QueueEntry:
    stmt = select(QueueEntry).where(QueueEntry.id == entry_id)
    if lock:
        stmt = stmt.with_for_update()
    e = (await session.execute(stmt)).scalar_one_or_none()
    if e is None:
        raise NotFoundError("Queue entry not found.")
    if not ctx.can_act_in_branch("queue.manage", e.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return e


def _require_active(e: QueueEntry) -> None:
    if e.status not in QUEUE_ACTIVE:
        raise ConflictError(f"This guest is already {e.status.replace('_', ' ')}.", code="QUEUE_ENTRY_CLOSED")


async def _free_reserved_table(session: AsyncSession, e: QueueEntry) -> None:
    if e.notified_table_id:
        t = await session.get(RestaurantTable, e.notified_table_id, with_for_update=True)
        if t is not None and t.status == "reserved":
            t.status = "available"


async def notify(
    session: AsyncSession, ctx: TenantContext, entry_id: uuid.UUID, table_id: uuid.UUID | None
) -> QueueEntryOut:
    """'Your table is ready' — optionally holding a specific table (it turns yellow on the board)."""
    e = await _entry(session, ctx, entry_id)
    _require_active(e)
    if table_id is not None:
        table = await tables_svc._table(session, ctx, table_id, "tables.operate", lock=True)
        if table.branch_id != e.branch_id or table.status != "available":
            raise ConflictError(f"Table {table.label} is not free.", code="TABLE_ALREADY_ASSIGNED")
        await _free_reserved_table(session, e)
        table.status = "reserved"
        e.notified_table_id = table.id
    e.status, e.notified_at = "notified", datetime.now(UTC)
    await session.commit()
    await tables_svc._changed(ctx, e.branch_id)
    await _changed(ctx.tenant_id, e.branch_id)
    out = await entry_out(session, e)
    await notify_guest(
        user_id=e.customer_id,
        phone=e.phone,
        event="queue.table_ready",
        title="Your table is ready!",
        body=f"Token {e.token}"
        + (f" · table {out.notified_table_label}" if out.notified_table_label else "")
        + " · please come to the host stand.",
    )
    return out


async def seat(session: AsyncSession, ctx: TenantContext, entry_id: uuid.UUID, table_id: uuid.UUID) -> SeatedOut:
    e = await _entry(session, ctx, entry_id)
    _require_active(e)
    if e.notified_table_id and e.notified_table_id != table_id:
        await _free_reserved_table(session, e)
    seated = await tables_svc.seat(
        session, ctx, SeatIn(table_id=table_id, party_size=e.party_size, guest_name=e.guest_name), source="queue"
    )
    e = await _entry(session, ctx, entry_id)
    e.status, e.ended_at, e.table_session_id = "seated", datetime.now(UTC), seated.session.id
    await session.commit()
    await _changed(ctx.tenant_id, e.branch_id)
    return seated


async def end(session: AsyncSession, ctx: TenantContext, entry_id: uuid.UUID, status: str) -> QueueEntryOut:
    e = await _entry(session, ctx, entry_id)
    _require_active(e)
    await _free_reserved_table(session, e)
    e.status, e.ended_at = status, datetime.now(UTC)
    await session.commit()
    await tables_svc._changed(ctx, e.branch_id)
    await _changed(ctx.tenant_id, e.branch_id)
    if status == "cancelled":
        await notify_guest(
            user_id=e.customer_id,
            phone=e.phone,
            event="queue.cancelled",
            title="Your queue spot was cancelled",
            body=f"Token {e.token}",
        )
    return await entry_out(session, e)


async def move(session: AsyncSession, ctx: TenantContext, entry_id: uuid.UUID, direction: str) -> list[QueueEntryOut]:
    e = await _entry(session, ctx, entry_id)
    _require_active(e)
    active = await _active(session, e.branch_id)
    i = next(i for i, x in enumerate(active) if x.id == e.id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(active):
        other = active[j]
        e.position, other.position = other.position, e.position
        await session.commit()
        await _changed(ctx.tenant_id, e.branch_id)
    return await staff_list(session, ctx, e.branch_id, history=False)


# ---------- customer side ----------


async def my_entry(session: AsyncSession, user: User, entry_id: uuid.UUID) -> QueueEntryOut:
    await use_system(session)  # cross-tenant read of the guest's own row, filtered explicitly
    e = (
        await session.execute(select(QueueEntry).where(QueueEntry.id == entry_id, QueueEntry.customer_id == user.id))
    ).scalar_one_or_none()
    if e is None:
        raise NotFoundError("Queue entry not found.")
    tenant = await session.get(Tenant, e.tenant_id)
    return await entry_out(session, e, tenant=tenant)


async def leave(session: AsyncSession, user: User, entry_id: uuid.UUID) -> QueueEntryOut:
    await use_system(session)
    e = (
        await session.execute(
            select(QueueEntry).where(QueueEntry.id == entry_id, QueueEntry.customer_id == user.id).with_for_update()
        )
    ).scalar_one_or_none()
    if e is None:
        raise NotFoundError("Queue entry not found.")
    _require_active(e)
    await _free_reserved_table(session, e)
    e.status, e.ended_at = "cancelled", datetime.now(UTC)
    await session.commit()
    await _changed(e.tenant_id, e.branch_id)
    tenant = await session.get(Tenant, e.tenant_id)
    return await entry_out(session, e, tenant=tenant)


async def my_entries(session: AsyncSession, user: User) -> list[QueueEntryOut]:
    await use_system(session)
    since = datetime.now(UTC) - timedelta(days=2)
    rows = (
        (
            await session.execute(
                select(QueueEntry)
                .where(QueueEntry.customer_id == user.id, QueueEntry.joined_at >= since)
                .order_by(QueueEntry.joined_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for e in rows:
        out.append(await entry_out(session, e, tenant=await session.get(Tenant, e.tenant_id)))
    return out

"""Table management (PRD §11) and table sessions (PRD §13 "order ID" flow, decision D8).

Concurrency: seating/transfer lock the table rows (SELECT … FOR UPDATE) and the partial unique index
`uq_table_assignments_open_per_table` is the last line of defence — two waiters seating the same table
at the same moment get one success and one 409 TABLE_ALREADY_ASSIGNED.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_otp
from app.models import Branch, Membership
from app.models.menu import MenuCategory, MenuItem
from app.models.tables import RestaurantTable, TableAssignment, TableSection, TableSession
from app.schemas.tables import (
    BoardBooking,
    BoardOut,
    BoardSession,
    BoardTable,
    DashboardOut,
    SeatedOut,
    SeatIn,
    SectionIn,
    SectionOut,
    SectionPatch,
    SessionOut,
    TableIn,
    TableOut,
    TablePatch,
)
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.limits import enforce_limit
from app.websocket.bus import branch_staff_room, emit

# Manual status changes allowed from the board (occupied is only reached by seating guests).
MANUAL_TRANSITIONS = {
    "available": {"reserved", "cleaning"},
    "reserved": {"available"},
    "cleaning": {"available"},
}


# ---------- helpers ----------


async def _branch(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, permission: str) -> Branch:
    branch = (await session.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if branch is None:
        raise NotFoundError("Branch not found.")
    if not ctx.can_act_in_branch(permission, branch.id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return branch


async def _table(
    session: AsyncSession, ctx: TenantContext, table_id: uuid.UUID, permission: str, *, lock: bool = False
) -> RestaurantTable:
    stmt = select(RestaurantTable).where(RestaurantTable.id == table_id)
    if lock:
        stmt = stmt.with_for_update()
    table = (await session.execute(stmt)).scalar_one_or_none()
    if table is None:
        raise NotFoundError("Table not found.")
    if not ctx.can_act_in_branch(permission, table.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return table


async def _changed(ctx: TenantContext, branch_id: uuid.UUID) -> None:
    await emit("tables.changed", {"branch_id": str(branch_id)}, branch_staff_room(ctx.tenant_id, branch_id))


async def _section(session: AsyncSession, section_id: uuid.UUID, branch_id: uuid.UUID) -> TableSection:
    sec = (await session.execute(select(TableSection).where(TableSection.id == section_id))).scalar_one_or_none()
    if sec is None or sec.branch_id != branch_id:
        raise AppError("That section is not in this branch.", code="SECTION_MISMATCH", status_code=422)
    return sec


# ---------- sections ----------


async def list_sections(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[SectionOut]:
    await _branch(session, ctx, branch_id, "tables.operate")
    rows = (
        await session.execute(
            select(TableSection)
            .where(TableSection.branch_id == branch_id)
            .order_by(TableSection.sort_order, TableSection.name)
        )
    ).scalars()
    return [SectionOut.model_validate(s) for s in rows]


async def create_section(session: AsyncSession, ctx: TenantContext, data: SectionIn) -> SectionOut:
    await _branch(session, ctx, data.branch_id, "tables.configure")
    dup = await session.execute(
        select(TableSection.id).where(
            TableSection.branch_id == data.branch_id, func.lower(TableSection.name) == data.name.strip().lower()
        )
    )
    if dup.first():
        raise ConflictError("This section already exists.", code="DUPLICATE_NAME")
    top = (
        await session.execute(
            select(func.coalesce(func.max(TableSection.sort_order), -1)).where(TableSection.branch_id == data.branch_id)
        )
    ).scalar_one()
    sec = TableSection(tenant_id=ctx.tenant_id, branch_id=data.branch_id, name=data.name.strip(), sort_order=top + 1)
    session.add(sec)
    await session.commit()
    await _changed(ctx, data.branch_id)
    return SectionOut.model_validate(sec)


async def update_section(
    session: AsyncSession, ctx: TenantContext, section_id: uuid.UUID, data: SectionPatch
) -> SectionOut:
    sec = (await session.execute(select(TableSection).where(TableSection.id == section_id))).scalar_one_or_none()
    if sec is None:
        raise NotFoundError("Section not found.")
    await _branch(session, ctx, sec.branch_id, "tables.configure")
    if data.name is not None:
        sec.name = data.name.strip()
    if data.sort_order is not None:
        sec.sort_order = data.sort_order
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("This section already exists.", code="DUPLICATE_NAME") from exc
    await _changed(ctx, sec.branch_id)
    return SectionOut.model_validate(sec)


async def delete_section(session: AsyncSession, ctx: TenantContext, section_id: uuid.UUID) -> None:
    sec = (await session.execute(select(TableSection).where(TableSection.id == section_id))).scalar_one_or_none()
    if sec is None:
        raise NotFoundError("Section not found.")
    branch_id = sec.branch_id
    await _branch(session, ctx, branch_id, "tables.configure")
    await session.delete(sec)  # tables keep existing without a section (FK SET NULL)
    await session.commit()
    await _changed(ctx, branch_id)


# ---------- tables ----------


async def list_tables(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[TableOut]:
    await _branch(session, ctx, branch_id, "tables.operate")
    rows = (
        await session.execute(
            select(RestaurantTable)
            .where(RestaurantTable.branch_id == branch_id)
            .order_by(RestaurantTable.sort_order, RestaurantTable.label)
        )
    ).scalars()
    return [TableOut.model_validate(t) for t in rows]


async def create_table(session: AsyncSession, ctx: TenantContext, data: TableIn) -> TableOut:
    await _branch(session, ctx, data.branch_id, "tables.configure")
    if data.section_id:
        await _section(session, data.section_id, data.branch_id)
    count = (
        await session.execute(
            select(func.count())
            .select_from(RestaurantTable)
            .where(RestaurantTable.branch_id == data.branch_id, RestaurantTable.is_active)
        )
    ).scalar_one()
    await enforce_limit(session, ctx.tenant_id, "max_tables_per_branch", count, "tables per branch")
    dup = await session.execute(
        select(RestaurantTable.id).where(
            RestaurantTable.branch_id == data.branch_id,
            func.lower(RestaurantTable.label) == data.label.strip().lower(),
        )
    )
    if dup.first():
        raise ConflictError(f'Table "{data.label.strip()}" already exists in this branch.', code="DUPLICATE_LABEL")
    top = (
        await session.execute(
            select(func.coalesce(func.max(RestaurantTable.sort_order), -1)).where(
                RestaurantTable.branch_id == data.branch_id
            )
        )
    ).scalar_one()
    table = RestaurantTable(
        tenant_id=ctx.tenant_id,
        branch_id=data.branch_id,
        section_id=data.section_id,
        label=data.label.strip(),
        capacity=data.capacity,
        sort_order=top + 1,
    )
    session.add(table)
    await session.commit()
    await _changed(ctx, data.branch_id)
    return TableOut.model_validate(table)


async def update_table(session: AsyncSession, ctx: TenantContext, table_id: uuid.UUID, data: TablePatch) -> TableOut:
    table = await _table(session, ctx, table_id, "tables.configure", lock=True)
    changes = data.model_dump(exclude_unset=True)
    if "section_id" in changes and changes["section_id"] is not None:
        await _section(session, changes["section_id"], table.branch_id)
    if changes.get("is_active") is False and table.status == "occupied":
        raise ConflictError("Guests are seated at this table.", code="TABLE_OCCUPIED")
    if changes.get("is_active") is True and not table.is_active:
        count = (
            await session.execute(
                select(func.count())
                .select_from(RestaurantTable)
                .where(RestaurantTable.branch_id == table.branch_id, RestaurantTable.is_active)
            )
        ).scalar_one()
        await enforce_limit(session, ctx.tenant_id, "max_tables_per_branch", count, "tables per branch")
    for key, value in changes.items():
        if key == "label" and value is not None:
            value = value.strip()
        if value is None and key != "section_id":
            continue
        setattr(table, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Another table already has this name.", code="DUPLICATE_LABEL") from exc
    await _changed(ctx, table.branch_id)
    return TableOut.model_validate(table)


async def set_status(session: AsyncSession, ctx: TenantContext, table_id: uuid.UUID, status: str) -> TableOut:
    table = await _table(session, ctx, table_id, "tables.operate", lock=True)
    if status != table.status:
        if status not in MANUAL_TRANSITIONS.get(table.status, set()):
            raise ConflictError(
                f"A table that is {table.status} cannot be marked {status}.",
                code="INVALID_TABLE_STATUS",
                details={"from": table.status, "to": status},
            )
        table.status = status
        await session.commit()
        await _changed(ctx, table.branch_id)
    return TableOut.model_validate(table)


# ---------- board ----------


async def _next_bookings(session: AsyncSession, table_ids: list[uuid.UUID]) -> dict[uuid.UUID, BoardBooking]:
    """Upcoming reservation per table (Phase 6), so staff see "Booked 19:30" before the table turns reserved."""
    from app.models.booking import Reservation, ReservationTable  # local: keeps model imports one-way

    if not table_ids:
        return {}
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(ReservationTable.table_id, Reservation)
                .join(Reservation, Reservation.id == ReservationTable.reservation_id)
                .where(
                    ReservationTable.table_id.in_(table_ids),
                    ReservationTable.active,
                    Reservation.status.in_(("confirmed", "pending_payment")),
                    Reservation.arrival_deadline >= now,
                    Reservation.starts_at <= now + timedelta(hours=48),
                )
                .order_by(Reservation.starts_at)
            )
        )
        .tuples()
        .all()
    )
    out: dict[uuid.UUID, BoardBooking] = {}
    for table_id, r in rows:
        out.setdefault(
            table_id,
            BoardBooking(
                reservation_id=r.id,
                code=r.code,
                starts_at=r.starts_at,
                guest_name=r.guest_name,
                party_size=r.party_size,
                status=r.status,
            ),
        )
    return out


async def board(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> BoardOut:
    await _branch(session, ctx, branch_id, "tables.operate")
    sections = (
        (
            await session.execute(
                select(TableSection)
                .where(TableSection.branch_id == branch_id)
                .order_by(TableSection.sort_order, TableSection.name)
            )
        )
        .scalars()
        .all()
    )
    section_names = {s.id: s.name for s in sections}
    tables = (
        (
            await session.execute(
                select(RestaurantTable)
                .where(RestaurantTable.branch_id == branch_id, RestaurantTable.is_active)
                .order_by(RestaurantTable.sort_order, RestaurantTable.label)
            )
        )
        .scalars()
        .all()
    )
    open_rows = (
        (
            await session.execute(
                select(TableAssignment.table_id, TableSession)
                .join(TableSession, TableSession.id == TableAssignment.table_session_id)
                .where(TableAssignment.released_at.is_(None), TableSession.branch_id == branch_id)
            )
        )
        .tuples()
        .all()
    )
    by_table = {tid: s for tid, s in open_rows}
    next_booking = await _next_bookings(session, [t.id for t in tables])
    counts = {s: 0 for s in ("available", "reserved", "occupied", "cleaning")}
    out = []
    for t in tables:
        counts[t.status] = counts.get(t.status, 0) + 1
        s = by_table.get(t.id)
        out.append(
            BoardTable(
                **TableOut.model_validate(t).model_dump(),
                section_name=section_names.get(t.section_id) if t.section_id else None,
                session=BoardSession(
                    id=s.id,
                    public_code=s.public_code,
                    party_size=s.party_size,
                    guest_name=s.guest_name,
                    opened_at=s.opened_at,
                    source=s.source,
                )
                if s
                else None,
                next_booking=next_booking.get(t.id),
            )
        )
    return BoardOut(
        branch_id=branch_id,
        tables=out,
        sections=[SectionOut.model_validate(s) for s in sections],
        counts=counts,
        server_time=datetime.now(UTC),
    )


# ---------- sessions ----------


def _prefix(slug: str) -> str:
    parts = [p for p in slug.split("-") if p]
    letters = "".join(p[0] for p in parts[:2]) if len(parts) >= 2 else slug[:2]
    return (letters or "WL").upper()


async def _new_code(session: AsyncSession, ctx: TenantContext) -> str:
    prefix = _prefix(ctx.tenant_slug)
    for _ in range(20):
        code = f"{prefix}-{secrets.randbelow(9000) + 1000}"
        taken = await session.execute(
            select(TableSession.id).where(TableSession.public_code == code, TableSession.status != "closed")
        )
        if not taken.first():
            return code
    raise AppError("Could not generate a free order code. Try again.", code="CODE_EXHAUSTED", status_code=503)


async def _session_out(session: AsyncSession, s: TableSession) -> SessionOut:
    table_ids = (
        (
            await session.execute(
                select(TableAssignment.table_id).where(
                    TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return SessionOut(
        id=s.id,
        branch_id=s.branch_id,
        public_code=s.public_code,
        status=s.status,
        source=s.source,
        party_size=s.party_size,
        guest_name=s.guest_name,
        table_ids=list(table_ids),
        opened_at=s.opened_at,
        closed_at=s.closed_at,
    )


async def seat(session: AsyncSession, ctx: TenantContext, data: SeatIn, *, source: str = "walk_in") -> SeatedOut:
    """Open a table session for walk-in guests: table becomes occupied; code + PIN returned once."""
    table = await _table(session, ctx, data.table_id, "tables.operate", lock=True)
    if not table.is_active:
        raise ConflictError("This table is not in use.", code="TABLE_INACTIVE")
    if table.status in ("occupied", "cleaning"):
        raise ConflictError(
            f"Table {table.label} is {table.status}.", code="TABLE_ALREADY_ASSIGNED", details={"status": table.status}
        )
    code = await _new_code(session, ctx)
    pin = f"{secrets.randbelow(10000):04d}"
    s = TableSession(
        tenant_id=ctx.tenant_id,
        branch_id=table.branch_id,
        public_code=code,
        pin_hash=hash_otp(code, pin),
        source=source,
        party_size=data.party_size,
        guest_name=(data.guest_name or "").strip() or None,
        opened_by=ctx.user_id,
    )
    session.add(s)
    await session.flush()
    session.add(TableAssignment(tenant_id=ctx.tenant_id, table_id=table.id, table_session_id=s.id))
    table.status = "occupied"
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race with another waiter
        await session.rollback()
        raise ConflictError(f"Table {table.label} was just taken.", code="TABLE_ALREADY_ASSIGNED") from exc
    await _changed(ctx, table.branch_id)
    return SeatedOut(session=await _session_out(session, s), pin=pin)


async def _open_session(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID) -> TableSession:
    s = (
        await session.execute(select(TableSession).where(TableSession.id == session_id).with_for_update())
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError("Table session not found.")
    if not ctx.can_act_in_branch("tables.operate", s.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    if s.status == "closed":
        raise ConflictError("This table session is already closed.", code="SESSION_CLOSED")
    return s


async def transfer(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID, table_id: uuid.UUID) -> SessionOut:
    s = await _open_session(session, ctx, session_id)
    target = await _table(session, ctx, table_id, "tables.operate", lock=True)
    if target.branch_id != s.branch_id:
        raise AppError("Guests can only move within the same branch.", code="BRANCH_MISMATCH", status_code=422)
    if not target.is_active or target.status not in ("available", "reserved"):
        raise ConflictError(f"Table {target.label} is not free.", code="TABLE_ALREADY_ASSIGNED")
    current = (
        (
            await session.execute(
                select(TableAssignment).where(
                    TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for a in current:
        a.released_at = now
        old = await session.get(RestaurantTable, a.table_id, with_for_update=True)
        if old is not None:
            old.status = "cleaning"
    await session.flush()
    session.add(TableAssignment(tenant_id=ctx.tenant_id, table_id=target.id, table_session_id=s.id))
    target.status = "occupied"
    write_audit(
        session,
        action="table_session.transferred",
        entity="table_session",
        entity_id=s.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"to_table": str(target.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"Table {target.label} was just taken.", code="TABLE_ALREADY_ASSIGNED") from exc
    await _changed(ctx, s.branch_id)
    return await _session_out(session, s)


async def close(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID) -> SessionOut:
    """Guests left: release tables (→ cleaning). Billing checks join this in Phase 10."""
    s = await _open_session(session, ctx, session_id)
    now = datetime.now(UTC)
    tables = (
        (
            await session.execute(
                select(TableAssignment.table_id).where(
                    TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    await session.execute(
        update(TableAssignment)
        .where(TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None))
        .values(released_at=now)
    )
    if tables:
        await session.execute(update(RestaurantTable).where(RestaurantTable.id.in_(tables)).values(status="cleaning"))
    s.status, s.closed_at, s.closed_by = "closed", now, ctx.user_id
    if s.source == "reservation":
        from app.services.reservations import complete_for_session  # local: reservations imports this module

        await complete_for_session(session, s.id)
    await session.commit()
    await _changed(ctx, s.branch_id)
    return await _session_out(session, s)


async def new_pin(session: AsyncSession, ctx: TenantContext, session_id: uuid.UUID) -> SeatedOut:
    s = await _open_session(session, ctx, session_id)
    pin = f"{secrets.randbelow(10000):04d}"
    s.pin_hash = hash_otp(s.public_code, pin)
    write_audit(
        session,
        action="table_session.pin_reset",
        entity="table_session",
        entity_id=s.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    return SeatedOut(session=await _session_out(session, s), pin=pin)


# ---------- dashboard ----------


async def dashboard(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID | None) -> DashboardOut:
    if branch_id is not None:
        await _branch(session, ctx, branch_id, "tables.operate")
    allowed = None if (ctx.all_branches or ctx.permissions.get("tables.operate") == "all") else ctx.branch_ids

    def scoped(stmt, column):  # type: ignore[no-untyped-def]
        if branch_id is not None:
            return stmt.where(column == branch_id)
        if allowed is not None:
            return stmt.where(column.in_(allowed))
        return stmt

    status_rows = (
        (
            await session.execute(
                scoped(
                    select(RestaurantTable.status, func.count())
                    .where(RestaurantTable.is_active)
                    .group_by(RestaurantTable.status),
                    RestaurantTable.branch_id,
                )
            )
        )
        .tuples()
        .all()
    )
    by_status = {s: 0 for s in ("available", "reserved", "occupied", "cleaning")} | dict(status_rows)
    open_q = scoped(
        select(func.count(), func.coalesce(func.sum(TableSession.party_size), 0)).where(
            TableSession.status != "closed"
        ),
        TableSession.branch_id,
    )
    open_sessions, guests = (await session.execute(open_q)).one()
    branches_active = (
        await session.execute(select(func.count()).select_from(Branch).where(Branch.is_active))
    ).scalar_one()
    staff_active = (
        await session.execute(select(func.count()).select_from(Membership).where(Membership.status == "active"))
    ).scalar_one()
    dishes = (
        await session.execute(
            select(func.count())
            .select_from(MenuItem)
            .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
            .where(MenuItem.archived_at.is_(None), MenuCategory.is_active)
        )
    ).scalar_one()
    return DashboardOut(
        branch_id=branch_id,
        tables_total=sum(by_status.values()),
        tables_by_status=by_status,
        open_sessions=open_sessions,
        guests_seated=int(guests),
        branches_active=branches_active,
        staff_active=staff_active,
        dishes_live=dishes,
    )


async def tables_ready(session: AsyncSession) -> bool:
    """Publish checklist: at least one active table."""
    n = (
        await session.execute(select(func.count()).select_from(RestaurantTable).where(RestaurantTable.is_active))
    ).scalar_one()
    return n > 0

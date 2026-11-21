"""Floor Agent: pairing, the events it reports, and telling the right waiter.

The agent only says "T2: guests seated" or "T2: guests left". It never decides who gets told. WaitLess looks up the
waiter in charge of that table *at that moment* (`restaurant_tables.waiter_user_id`), so moving a table to another
waiter takes effect straight away without touching the laptop.

Who is told:
- guests seated  → the table's waiter (no waiter, or one who is disabled → every waiter of the branch)
- guests left    → the table's waiter; if the table is still open in the app (bill not settled), the branch's
                   owner and managers are told as well ("left without paying?")
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system, use_tenant
from app.core.errors import AppError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import hash_token
from app.models import Branch, FloorAgent, FloorAlert, RestaurantTable, TableAssignment, TableOccupancy, User
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.notify import user_room
from app.services.tables import _branch_staff
from app.websocket.bus import branch_staff_room, emit

PAIRING_VALID = timedelta(minutes=15)
ONLINE_WITHIN = timedelta(seconds=90)
STALE_AFTER = timedelta(minutes=10)  # an event older than this is recorded but does not ping anyone
MAX_BATCH = 50
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to mix up when typing
ALERT_WINDOW = timedelta(hours=12)


def _now() -> datetime:
    return datetime.now(UTC)


def _code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _norm_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _agent_out(a: FloorAgent) -> dict[str, Any]:
    seen = a.last_seen_at
    return {
        "id": str(a.id),
        "branch_id": str(a.branch_id),
        "name": a.name,
        "status": "revoked" if a.revoked_at else ("paired" if a.paired_at else "waiting"),
        "online": bool(seen and _now() - seen <= ONLINE_WITHIN and not a.revoked_at),
        "last_seen_at": seen.isoformat() if seen else None,
        "created_at": a.created_at.isoformat(),
    }


# ---------- owner: manage agents ----------


async def _check_branch(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> None:
    if (await session.get(Branch, branch_id)) is None:
        raise NotFoundError("Branch not found.")
    if not ctx.can_act_in_branch("tables.configure", branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")


async def create_agent(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, name: str) -> dict[str, Any]:
    await _check_branch(session, ctx, branch_id)
    code = _code()
    agent = FloorAgent(
        tenant_id=ctx.tenant_id,
        branch_id=branch_id,
        name=name.strip()[:60] or "Floor agent",
        pairing_hash=hash_token(_norm_code(code)),
        pairing_expires_at=_now() + PAIRING_VALID,
        created_by=ctx.user_id,
    )
    session.add(agent)
    await session.flush()
    write_audit(
        session,
        action="floor_agent.created",
        entity="floor_agent",
        entity_id=agent.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    return {**_agent_out(agent), "pairing_code": code, "expires_at": agent.pairing_expires_at.isoformat()}


async def list_agents(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[dict[str, Any]]:
    await _check_branch(session, ctx, branch_id)
    rows = (
        await session.execute(
            select(FloorAgent)
            .where(FloorAgent.branch_id == branch_id, FloorAgent.revoked_at.is_(None))
            .order_by(FloorAgent.created_at)
        )
    ).scalars()
    return [_agent_out(a) for a in rows]


async def revoke_agent(session: AsyncSession, ctx: TenantContext, agent_id: uuid.UUID) -> None:
    agent = await session.get(FloorAgent, agent_id)
    if agent is None:
        raise NotFoundError("Agent not found.")
    await _check_branch(session, ctx, agent.branch_id)
    agent.revoked_at, agent.key_hash, agent.pairing_hash = _now(), None, None
    write_audit(
        session,
        action="floor_agent.revoked",
        entity="floor_agent",
        entity_id=agent.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()


# ---------- the agent itself ----------


async def _branch_tables(session: AsyncSession, branch_id: uuid.UUID) -> list[dict[str, Any]]:
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
    ids = {t.waiter_user_id for t in tables if t.waiter_user_id}
    names = (
        dict((await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).tuples().all())
        if ids
        else {}
    )
    return [
        {
            "label": t.label,
            "capacity": t.capacity,
            "waiter_name": names.get(t.waiter_user_id) if t.waiter_user_id else None,
        }
        for t in tables
    ]


async def pair(session: AsyncSession, code: str) -> dict[str, Any]:
    """Swap the one-time pairing code for the agent's key. The key is shown once; only its hash is stored."""
    await use_system(session)  # the agent has no restaurant yet: find it by the code
    agent = (
        await session.execute(
            select(FloorAgent).where(FloorAgent.pairing_hash == hash_token(_norm_code(code))).with_for_update()
        )
    ).scalar_one_or_none()
    if (
        agent is None
        or agent.revoked_at is not None
        or agent.key_hash is not None
        or agent.pairing_expires_at is None
        or agent.pairing_expires_at < _now()
    ):
        raise AppError("This pairing code is wrong or has expired.", code="PAIRING_CODE_INVALID", status_code=400)
    key = "wla_" + secrets.token_urlsafe(32)
    agent.key_hash, agent.pairing_hash, agent.pairing_expires_at = hash_token(key), None, None
    agent.paired_at = agent.last_seen_at = _now()
    await session.commit()
    await use_tenant(session, agent.tenant_id)
    return {
        "agent_key": key,
        "agent": _agent_out(agent),
        "tables": await _branch_tables(session, agent.branch_id),
    }


async def agent_from_key(session: AsyncSession, key: str | None) -> FloorAgent:
    if not key:
        raise UnauthorizedError("Missing agent key.", code="AGENT_KEY_INVALID")
    await use_system(session)
    agent = (
        await session.execute(select(FloorAgent).where(FloorAgent.key_hash == hash_token(key)))
    ).scalar_one_or_none()
    if agent is None or agent.revoked_at is not None:
        raise UnauthorizedError("This agent is not allowed. Pair it again.", code="AGENT_KEY_INVALID")
    await use_tenant(session, agent.tenant_id)  # from here on only this restaurant's rows are visible
    if agent.last_seen_at is None or _now() - agent.last_seen_at > timedelta(seconds=20):
        await session.execute(update(FloorAgent).where(FloorAgent.id == agent.id).values(last_seen_at=_now()))
        await session.commit()
    return agent


async def agent_tables(session: AsyncSession, agent: FloorAgent) -> list[dict[str, Any]]:
    return await _branch_tables(session, agent.branch_id)


# ---------- events from the agent ----------


async def _in_charge(session: AsyncSession, table: RestaurantTable) -> uuid.UUID | None:
    """The table's waiter, if they can still work this branch; otherwise nobody in particular."""
    if table.waiter_user_id is None:
        return None
    staff = await _branch_staff(session, table.branch_id)
    ok = any(u.id == table.waiter_user_id and m.status == "active" for u, _, m in staff)
    return table.waiter_user_id if ok else None


async def _managers(session: AsyncSession, branch_id: uuid.UUID) -> list[uuid.UUID]:
    staff = await _branch_staff(session, branch_id)
    return [u.id for u, r, m in staff if r.key in ("owner", "manager") and m.status == "active"]


def _alert_out(a: FloorAlert) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "branch_id": str(a.branch_id),
        "table_id": str(a.table_id),
        "table_label": a.table_label,
        "kind": a.kind,
        "message": a.message,
        "user_id": str(a.user_id) if a.user_id else None,
        "created_at": a.created_at.isoformat(),
        "acked_at": a.acked_at.isoformat() if a.acked_at else None,
    }


async def _emit_alert(a: FloorAlert) -> None:
    room = user_room(a.user_id) if a.user_id else branch_staff_room(a.tenant_id, a.branch_id)
    await emit("floor.alert", _alert_out(a), room)


async def process_events(
    session: AsyncSession, agent: FloorAgent, events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(events) > MAX_BATCH:
        raise AppError(f"Send at most {MAX_BATCH} events at a time.", code="BATCH_TOO_LARGE", status_code=422)
    results: list[dict[str, Any]] = []
    to_emit: list[FloorAlert] = []
    for ev in events:
        results.append(await _one_event(session, agent, ev, to_emit))
    await session.commit()  # save first, tell people after ("persist before broadcasting")
    for a in to_emit:
        await session.refresh(a)
        await _emit_alert(a)
    return results


async def _one_event(
    session: AsyncSession, agent: FloorAgent, ev: dict[str, Any], to_emit: list[FloorAlert]
) -> dict[str, Any]:
    event_id = ev["event_id"]
    base = {"event_id": str(event_id)}
    table = (
        await session.execute(
            select(RestaurantTable)
            .where(
                RestaurantTable.branch_id == agent.branch_id,
                RestaurantTable.is_active,
                func.lower(RestaurantTable.label) == ev["table"].strip().lower(),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if table is None:
        return {**base, "status": "unknown_table"}
    at: datetime = ev["at"]
    late = _now() - at > STALE_AFTER
    open_row = (
        await session.execute(
            select(TableOccupancy).where(TableOccupancy.table_id == table.id, TableOccupancy.left_at.is_(None))
        )
    ).scalar_one_or_none()

    if ev["kind"] == "seated":
        if (await session.execute(select(TableOccupancy.id).where(TableOccupancy.event_id == event_id))).first():
            return {**base, "status": "duplicate"}
        if open_row is not None:  # already sitting: just remember the larger party
            open_row.guests = max(open_row.guests, ev["guests"])
            return {**base, "status": "updated"}
        session.add(
            TableOccupancy(
                tenant_id=agent.tenant_id,
                branch_id=agent.branch_id,
                table_id=table.id,
                agent_id=agent.id,
                event_id=event_id,
                guests=ev["guests"],
                seated_at=at,
            )
        )
        if late:
            return {**base, "status": "recorded_late"}
        opened = (
            await session.execute(
                select(TableAssignment.id).where(
                    TableAssignment.table_id == table.id, TableAssignment.released_at.is_(None)
                )
            )
        ).first()
        who = await _in_charge(session, table)
        kind, text = (
            ("seated", f"Guests seated at {table.label}")
            if opened
            else ("seated_unchecked", f"Guests at {table.label} — not checked in yet")
        )
        alert = _add_alert(session, agent, table, kind, text, who)
        to_emit.append(alert)
        return {**base, "status": "ok", "notified": str(who) if who else "all_waiters"}

    # guests left
    if open_row is None:
        return {**base, "status": "ignored"}  # nobody was recorded there (or this is a repeat)
    open_row.left_at = at
    if late:
        return {**base, "status": "recorded_late"}
    who = await _in_charge(session, table)
    still_open = (
        await session.execute(
            select(TableAssignment.id).where(
                TableAssignment.table_id == table.id, TableAssignment.released_at.is_(None)
            )
        )
    ).first()
    if still_open:  # the camera says empty, the app says the table is still in use: the bill may be unsettled
        to_emit.append(
            _add_alert(
                session, agent, table, "left_open", f"Guests left {table.label} — check the bill, table still open", who
            )
        )
        for manager in await _managers(session, table.branch_id):
            if manager != who:
                to_emit.append(
                    _add_alert(
                        session,
                        agent,
                        table,
                        "left_open",
                        f"Guests left {table.label} but it is still open — bill unpaid?",
                        manager,
                    )
                )
    else:
        to_emit.append(_add_alert(session, agent, table, "left", f"{table.label} is empty — mark it for cleaning", who))
    return {**base, "status": "ok", "notified": str(who) if who else "all_waiters"}


def _add_alert(
    session: AsyncSession, agent: FloorAgent, table: RestaurantTable, kind: str, message: str, user_id: uuid.UUID | None
) -> FloorAlert:
    alert = FloorAlert(
        tenant_id=agent.tenant_id,
        branch_id=agent.branch_id,
        table_id=table.id,
        table_label=table.label,
        user_id=user_id,
        kind=kind,
        message=message[:160],
    )
    session.add(alert)
    return alert


# ---------- the waiter's side ----------


async def my_alerts(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[dict[str, Any]]:
    """Open alerts for me: the ones addressed to me and the ones for the whole branch."""
    if not ctx.can_act_in_branch("tables.operate", branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    rows = (
        await session.execute(
            select(FloorAlert)
            .where(
                FloorAlert.branch_id == branch_id,
                FloorAlert.acked_at.is_(None),
                FloorAlert.created_at > _now() - ALERT_WINDOW,
                (FloorAlert.user_id == ctx.user_id) | FloorAlert.user_id.is_(None),
            )
            .order_by(FloorAlert.created_at)
        )
    ).scalars()
    return [_alert_out(a) for a in rows]


async def ack_alert(session: AsyncSession, ctx: TenantContext, alert_id: uuid.UUID) -> dict[str, Any]:
    a = (
        await session.execute(select(FloorAlert).where(FloorAlert.id == alert_id).with_for_update())
    ).scalar_one_or_none()
    # An alert addressed to someone else is not yours to clear (and not visible: same answer as "not found").
    if a is None or (a.user_id is not None and a.user_id != ctx.user_id):
        raise NotFoundError("Alert not found.")
    if not ctx.can_act_in_branch("tables.operate", a.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    if a.acked_at is None:
        a.acked_at, a.acked_by = _now(), ctx.user_id
        await session.commit()
        await session.refresh(a)
    room = user_room(a.user_id) if a.user_id else branch_staff_room(a.tenant_id, a.branch_id)
    await emit("floor.alert.ack", {"id": str(a.id)}, room)
    return _alert_out(a)

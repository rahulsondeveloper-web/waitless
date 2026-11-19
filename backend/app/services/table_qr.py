"""Table QR codes: a code stuck on every table opens that table's menu on the guest's phone.

- The QR holds only a random token (`/r/{slug}/t/{token}`), never ids; staff can regenerate it.
- Free table: the guest can start ordering themselves ("self-seating", on by default — the restaurant can turn
  it off in Tables → QR codes). The table becomes occupied and the guest gets the order ID + PIN to share with
  friends at the table.
- Occupied table: the guest enters the PIN (from whoever started the table, or the waiter).
- Rate limited per table and per device IP, so a photographed QR cannot be abused from home.
"""

import hmac
import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.errors import AppError, ConflictError, NotFoundError, UnauthorizedError
from app.core.security import create_table_token, hash_otp
from app.models import Branch, Tenant
from app.models.tables import RestaurantTable, TableAssignment, TableSession
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.tables import _branch, _prefix
from app.websocket.bus import branch_staff_room, emit


def _token() -> str:
    return secrets.token_urlsafe(12)[:16]


def self_seating(tenant: Tenant) -> bool:
    return bool((tenant.settings or {}).get("qr_self_seating", True))


# ---------- staff ----------


async def qr_codes(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> dict[str, Any]:
    branch = await _branch(session, ctx, branch_id, "tables.configure")
    tables = list(
        (
            await session.execute(
                select(RestaurantTable)
                .where(RestaurantTable.branch_id == branch.id, RestaurantTable.is_active)
                .order_by(RestaurantTable.sort_order, RestaurantTable.label)
            )
        ).scalars()
    )
    changed = False
    for t in tables:
        if not t.qr_token:
            t.qr_token = _token()
            changed = True
    if changed:
        await session.commit()
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    return {
        "branch_id": branch.id,
        "branch_name": branch.name,
        "restaurant_name": tenant.name,
        "slug": tenant.slug,
        "self_seating": self_seating(tenant),
        "tables": [
            {"table_id": t.id, "label": t.label, "capacity": t.capacity, "path": f"/r/{tenant.slug}/t/{t.qr_token}"}
            for t in tables
        ],
    }


async def rotate(session: AsyncSession, ctx: TenantContext, table_id: uuid.UUID) -> dict[str, Any]:
    """A new code for one table (the old sticker stops working)."""
    t = await session.get(RestaurantTable, table_id)
    if t is None:
        raise NotFoundError("Table not found.")
    await _branch(session, ctx, t.branch_id, "tables.configure")
    t.qr_token = _token()
    write_audit(
        session,
        action="table.qr_rotated",
        entity="table",
        entity_id=t.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    return await qr_codes(session, ctx, t.branch_id)


async def set_self_seating(session: AsyncSession, ctx: TenantContext, enabled: bool) -> bool:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    tenant.settings = {**(tenant.settings or {}), "qr_self_seating": enabled}
    write_audit(
        session,
        action="table.qr_self_seating",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=ctx.user_id,
        diff={"enabled": enabled},
    )
    await session.commit()
    return enabled


# ---------- guests (public) ----------


async def _table(session: AsyncSession, tenant: Tenant, token: str, lock: bool = False) -> RestaurantTable:
    stmt = select(RestaurantTable).where(RestaurantTable.qr_token == token, RestaurantTable.is_active)
    if lock:
        stmt = stmt.with_for_update()
    t = (await session.execute(stmt)).scalar_one_or_none()
    if t is None:
        raise NotFoundError("This table code is not valid any more — ask the staff.")
    return t


async def _open_session(session: AsyncSession, table: RestaurantTable) -> TableSession | None:
    return (
        await session.execute(
            select(TableSession)
            .join(TableAssignment, TableAssignment.table_session_id == TableSession.id)
            .where(
                TableAssignment.table_id == table.id,
                TableAssignment.released_at.is_(None),
                TableSession.status != "closed",
            )
        )
    ).scalar_one_or_none()


async def lookup(session: AsyncSession, tenant: Tenant, token: str) -> dict[str, Any]:
    t = await _table(session, tenant, token)
    branch = await session.get(Branch, t.branch_id)
    s = await _open_session(session, t)
    from app.api.deps import feature_enabled

    return {
        "table_label": t.label,
        "capacity": t.capacity,
        "branch_id": t.branch_id,
        "branch_name": branch.name if branch else "",
        "state": "occupied" if s else ("free" if t.status in ("available", "reserved") else t.status),
        "session_open": s is not None and s.status == "open",
        "self_seating": self_seating(tenant) and t.status == "available",
        "ordering_enabled": await feature_enabled(session, tenant.id, "ordering"),
    }


async def start(
    session: AsyncSession, tenant: Tenant, token: str, guest_name: str, party_size: int, ip: str | None
) -> dict[str, Any]:
    """Self-seating at a free table: the guest opens the table and gets its order ID + PIN."""
    await rate_limit.hit(f"qr-start:{token}", limit=5, window_seconds=900)
    if ip:
        await rate_limit.hit(f"qr-start-ip:{ip}", limit=10, window_seconds=3600)
    if not self_seating(tenant):
        raise ConflictError("Please ask the staff to seat you.", code="SELF_SEATING_OFF")
    t = await _table(session, tenant, token, lock=True)
    if t.status != "available" or await _open_session(session, t):
        raise ConflictError("Someone is already at this table — enter their PIN.", code="TABLE_OCCUPIED")
    if not 1 <= party_size <= max(t.capacity * 2, 2):
        raise AppError("Check the number of guests.", code="INVALID_PARTY", status_code=422)
    name = guest_name.strip()[:60]
    if not name:
        raise AppError("Tell us your name.", code="NAME_REQUIRED", status_code=422)
    s, code, pin = await open_visit(
        session, tenant, t, name, party_size, source="walk_in", audit_action="table.self_seated", ip=ip
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Someone just took this table — enter their PIN.", code="TABLE_OCCUPIED") from exc
    await emit("tables.changed", {"branch_id": str(t.branch_id)}, branch_staff_room(tenant.id, t.branch_id))
    jwt, exp = create_table_token(s.id, tenant.id, s.pin_hash)
    return {"token": jwt, "expires_at": exp, "session_id": s.id, "code": code, "pin": pin, "table_label": t.label}


async def open_visit(
    session: AsyncSession,
    tenant: Tenant,
    t: RestaurantTable,
    name: str,
    party_size: int,
    *,
    source: str,
    audit_action: str,
    ip: str | None,
) -> tuple[TableSession, str, str]:
    """Open a guest visit at a free (locked) table: order ID + PIN, table occupied. Caller commits."""
    prefix = _prefix(tenant.slug)
    code = ""
    for _ in range(20):
        code = f"{prefix}-{secrets.randbelow(9000) + 1000}"
        taken = await session.execute(
            select(TableSession.id).where(TableSession.public_code == code, TableSession.status != "closed")
        )
        if not taken.first():
            break
    pin = f"{secrets.randbelow(10000):04d}"
    s = TableSession(
        tenant_id=tenant.id,
        branch_id=t.branch_id,
        public_code=code,
        pin_hash=hash_otp(code, pin),
        source=source,
        party_size=party_size,
        guest_name=name,
    )
    session.add(s)
    await session.flush()
    session.add(TableAssignment(tenant_id=tenant.id, table_id=t.id, table_session_id=s.id))
    t.status = "occupied"
    write_audit(
        session,
        action=audit_action,
        entity="table",
        entity_id=t.id,
        tenant_id=tenant.id,
        diff={"guest": name, "party": party_size},
        ip=ip,
    )
    return s, code, pin


async def join(session: AsyncSession, tenant: Tenant, token: str, pin: str, ip: str | None) -> dict[str, Any]:
    """Occupied table: join with the PIN of the people already seated (no order ID to type)."""
    await rate_limit.hit(f"qr-join:{token}", limit=8, window_seconds=900)
    if ip:
        await rate_limit.hit(f"table-join-ip:{ip}", limit=30, window_seconds=900)
    t = await _table(session, tenant, token)
    s = await _open_session(session, t)
    if s is None:
        raise ConflictError("Nobody is seated at this table yet.", code="TABLE_FREE")
    if not hmac.compare_digest(s.pin_hash, hash_otp(s.public_code, pin)):
        raise UnauthorizedError("That PIN is not right for this table.", code="INVALID_TABLE_PIN")
    jwt, exp = create_table_token(s.id, tenant.id, s.pin_hash)
    return {
        "token": jwt,
        "expires_at": exp,
        "session_id": s.id,
        "code": s.public_code,
        "pin": None,
        "table_label": t.label,
    }


async def public_tenant(session: AsyncSession, slug: str) -> Tenant:
    from app.services.profile import _public_tenant

    return await _public_tenant(session, slug)

"""Guest service at the table (post-launch additions).

- Call the waiter: Water / Tissue paper / Bill / Help from the guest's phone (table token, no order ID
  re-entry). One call per visit every 2 minutes. Waiters and managers of the branch get a live alert and
  mark it done when they reach the table.
- Restaurant Wi-Fi: the owner sets name + password; only guests of an open visit can read it.
- Reviews: 1–5 stars and a comment once the visit is paid; shown on the restaurant page (owner can hide).
- Signed-in guests are linked to the visit they join, so its invoices appear under "My orders".
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_tenant
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Bill, BillItem, RestaurantTable, TableAssignment, TableSession, Tenant, User
from app.models.guest_service import REQUEST_KINDS, Review, ServiceRequest, TableSessionGuest
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.websocket.bus import branch_staff_room, emit

COOLDOWN = timedelta(minutes=2)
KIND_LABEL = {"water": "Water", "tissue": "Tissue paper", "bill": "The bill", "help": "Help"}


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- signed-in guests of a visit ----------


async def link_token(session: AsyncSession, token: str | None, user: User | None) -> None:
    """After a join or when a signed-in guest opens their table: link them to that visit and commit."""
    if user is None or not token:
        return
    from app.services.orders import table_from_token

    try:
        s, _ = await table_from_token(session, token)
    except AppError:
        return
    await link_guest(session, s, user)
    await session.commit()


async def link_guest(session: AsyncSession, s: TableSession, user: User | None) -> None:
    """Remember that this signed-in customer was at the visit (idempotent). Caller commits."""
    if user is None:
        return
    await session.execute(
        insert(TableSessionGuest)
        .values(tenant_id=s.tenant_id, table_session_id=s.id, user_id=user.id)
        .on_conflict_do_nothing()
    )


# ---------- call the waiter ----------


async def _labels(session: AsyncSession, s: TableSession) -> list[str]:
    return list(
        (
            await session.execute(
                select(RestaurantTable.label)
                .join(TableAssignment, TableAssignment.table_id == RestaurantTable.id)
                .where(TableAssignment.table_session_id == s.id, TableAssignment.released_at.is_(None))
                .order_by(RestaurantTable.label)
            )
        ).scalars()
    )


def request_out(r: ServiceRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "branch_id": r.branch_id,
        "table_session_id": r.table_session_id,
        "kind": r.kind,
        "label": KIND_LABEL[r.kind],
        "table_labels": r.table_labels,
        "guest_name": r.guest_name,
        "status": r.status,
        "created_at": r.created_at,
        "done_at": r.done_at,
    }


async def _last_call(session: AsyncSession, session_id: uuid.UUID) -> ServiceRequest | None:
    return (
        await session.execute(
            select(ServiceRequest)
            .where(ServiceRequest.table_session_id == session_id)
            .order_by(ServiceRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _cooldown_until(last: ServiceRequest | None) -> datetime | None:
    if last is None:
        return None
    until = last.created_at + COOLDOWN
    return until if until > _now() else None


async def guest_calls(session: AsyncSession, token: str | None) -> dict[str, Any]:
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    last = await _last_call(session, s.id)
    open_calls = (
        await session.execute(
            select(ServiceRequest)
            .where(ServiceRequest.table_session_id == s.id, ServiceRequest.status == "open")
            .order_by(ServiceRequest.created_at)
        )
    ).scalars()
    return {
        "can_call": s.status != "closed",
        "cooldown_until": _cooldown_until(last),
        "open": [request_out(r) for r in open_calls],
        "server_time": _now(),
    }


async def call_waiter(session: AsyncSession, token: str | None, kind: str, guest_name: str) -> dict[str, Any]:
    from app.services.orders import table_from_token

    if kind not in REQUEST_KINDS:
        raise AppError("Choose water, tissue paper, the bill or help.", code="INVALID_KIND", status_code=422)
    s, _ = await table_from_token(session, token)
    s = (await session.execute(select(TableSession).where(TableSession.id == s.id).with_for_update())).scalar_one()
    if s.status == "closed":
        raise ConflictError("Your table is closed.", code="SESSION_CLOSED")
    until = _cooldown_until(await _last_call(session, s.id))
    if until:
        seconds = max(1, int((until - _now()).total_seconds()))
        raise AppError(
            "The waiter is on the way — you can call again in a moment.",
            code="CALL_COOLDOWN",
            status_code=429,
            details={"retry_after": seconds, "cooldown_until": until.isoformat()},
        )
    r = ServiceRequest(
        tenant_id=s.tenant_id,
        branch_id=s.branch_id,
        table_session_id=s.id,
        kind=kind,
        table_labels=", ".join(await _labels(session, s))[:80],
        guest_name=(guest_name or "").strip()[:60] or s.guest_name,
    )
    session.add(r)
    await session.commit()
    await session.refresh(r)
    out = request_out(r)
    await emit("service.requested", _event(out), branch_staff_room(s.tenant_id, s.branch_id))
    return {"request": out, "cooldown_until": r.created_at + COOLDOWN, "server_time": _now()}


def _event(out: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID | datetime) else v) for k, v in out.items()}


async def open_calls(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> list[dict[str, Any]]:
    if not ctx.can_act_in_branch("tables.operate", branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    rows = (
        await session.execute(
            select(ServiceRequest)
            .where(ServiceRequest.branch_id == branch_id, ServiceRequest.status == "open")
            .order_by(ServiceRequest.created_at)
        )
    ).scalars()
    return [request_out(r) for r in rows]


async def call_done(session: AsyncSession, ctx: TenantContext, request_id: uuid.UUID) -> dict[str, Any]:
    r = (
        await session.execute(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Call not found.")
    if not ctx.can_act_in_branch("tables.operate", r.branch_id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    if r.status == "open":
        r.status, r.done_at, r.done_by = "done", _now(), ctx.user_id
        await session.commit()
        await session.refresh(r)
    out = request_out(r)
    await emit("service.done", _event(out), branch_staff_room(r.tenant_id, r.branch_id))
    from app.services.orders import table_session_room

    await emit("service.done", {"id": str(r.id)}, table_session_room(r.tenant_id, r.table_session_id))
    return out


# ---------- restaurant Wi-Fi ----------


def wifi_of(tenant: Tenant) -> dict[str, str]:
    w = (tenant.settings or {}).get("guest_wifi") or {}
    return {"name": str(w.get("name") or ""), "password": str(w.get("password") or "")}


async def get_wifi(session: AsyncSession, ctx: TenantContext) -> dict[str, str]:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    return wifi_of(tenant)


async def set_wifi(session: AsyncSession, ctx: TenantContext, name: str, password: str) -> dict[str, str]:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    tenant.settings = {**(tenant.settings or {}), "guest_wifi": {"name": name.strip(), "password": password}}
    write_audit(
        session,
        action="restaurant.guest_wifi",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=ctx.user_id,
        diff={"name": name.strip(), "password_set": bool(password)},  # never the password itself
    )
    await session.commit()
    return wifi_of(tenant)


async def guest_wifi(session: AsyncSession, token: str | None) -> dict[str, str] | None:
    """Only for guests of an open visit; None when the restaurant has not set it up."""
    from app.services.orders import table_from_token

    s, tenant = await table_from_token(session, token)
    if s.status == "closed":
        raise ConflictError("Your table is closed.", code="SESSION_CLOSED")
    w = wifi_of(tenant)
    return w if w["name"] or w["password"] else None


# ---------- reviews ----------


def review_out(r: Review) -> dict[str, Any]:
    return {
        "id": r.id,
        "rating": r.rating,
        "comment": r.comment,
        "guest_name": r.guest_name or "Guest",
        "created_at": r.created_at,
        "hidden": r.hidden,
    }


async def _paid(session: AsyncSession, s: TableSession) -> bool:
    """At least one paid bill and none still open with dishes."""
    paid = (
        await session.execute(
            select(func.count()).select_from(Bill).where(Bill.table_session_id == s.id, Bill.status == "paid")
        )
    ).scalar_one()
    still_open = (
        await session.execute(
            select(func.count())
            .select_from(Bill)
            .where(Bill.table_session_id == s.id, Bill.status == "open", Bill.id.in_(select(BillItem.bill_id)))
        )
    ).scalar_one()
    return bool(paid) and not still_open


async def my_review(session: AsyncSession, token: str | None) -> dict[str, Any]:
    from app.services.orders import table_from_token

    s, _ = await table_from_token(session, token)
    r = (await session.execute(select(Review).where(Review.table_session_id == s.id))).scalar_one_or_none()
    return {"can_review": r is None and await _paid(session, s), "review": review_out(r) if r else None}


async def submit_review(
    session: AsyncSession, token: str | None, rating: int, comment: str, guest_name: str, user: User | None
) -> dict[str, Any]:
    from app.services.orders import table_from_token
    from app.services.storefront_cache import invalidate_storefront

    s, tenant = await table_from_token(session, token)
    if not await _paid(session, s):
        raise ConflictError("You can review once your bill is paid.", code="NOT_PAID")
    exists = (await session.execute(select(Review.id).where(Review.table_session_id == s.id))).scalar_one_or_none()
    if exists:
        raise ConflictError("This visit already has a review — thank you!", code="ALREADY_REVIEWED")
    name = (guest_name or "").strip()[:60] or (user.full_name if user else "") or (s.guest_name or "")
    r = Review(
        tenant_id=s.tenant_id,
        branch_id=s.branch_id,
        table_session_id=s.id,
        user_id=user.id if user else None,
        guest_name=name[:60],
        rating=rating,
        comment=comment.strip()[:1000],
    )
    session.add(r)
    await session.commit()
    await session.refresh(r)
    await invalidate_storefront(tenant.slug)
    return review_out(r)


async def public_reviews(session: AsyncSession, slug: str, limit: int = 20) -> dict[str, Any]:
    from app.services.profile import _public_tenant

    tenant = await _public_tenant(session, slug)
    await use_tenant(session, tenant.id)
    visible = Review.tenant_id == tenant.id, Review.hidden.is_(False)
    count, avg = (await session.execute(select(func.count(), func.avg(Review.rating)).where(*visible))).one()
    rows = (
        await session.execute(select(Review).where(*visible).order_by(Review.created_at.desc()).limit(limit))
    ).scalars()
    return {
        "count": int(count or 0),
        "average": round(float(avg), 1) if avg is not None else None,
        "reviews": [{k: v for k, v in review_out(r).items() if k != "hidden"} for r in rows],
    }


async def staff_reviews(session: AsyncSession, ctx: TenantContext) -> dict[str, Any]:
    count, avg = (
        await session.execute(
            select(func.count(), func.avg(Review.rating)).where(
                Review.tenant_id == ctx.tenant_id, Review.hidden.is_(False)
            )
        )
    ).one()
    rows = (
        await session.execute(
            select(Review).where(Review.tenant_id == ctx.tenant_id).order_by(Review.created_at.desc()).limit(200)
        )
    ).scalars()
    return {
        "count": int(count or 0),
        "average": round(float(avg), 1) if avg is not None else None,
        "reviews": [review_out(r) for r in rows],
    }


async def set_review_hidden(
    session: AsyncSession, ctx: TenantContext, review_id: uuid.UUID, hidden: bool
) -> dict[str, Any]:
    from app.services.storefront_cache import invalidate_storefront

    r = (await session.execute(select(Review).where(Review.id == review_id))).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Review not found.")
    r.hidden = hidden
    write_audit(
        session,
        action="review.hidden" if hidden else "review.shown",
        entity="review",
        entity_id=r.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return review_out(r)

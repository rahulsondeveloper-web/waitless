"""Super Admin: restaurant list/detail and lifecycle (PRD §16). Every change is audited."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.core.errors import AppError, NotFoundError
from app.core.events import record_event
from app.models import Branch, Membership, Role, Tenant, User
from app.schemas.common import Page
from app.schemas.tenancy import OwnerOut, RestaurantAdminRow, StatusAction
from app.services.access import live_subscription, subscription_out
from app.services.audit import write_audit

# action -> (allowed current statuses, new status, reason required)
TRANSITIONS: dict[str, tuple[tuple[str, ...], str, bool]] = {
    "approve": (("pending",), "active", False),
    "reject": (("pending",), "rejected", True),
    "activate": (("suspended", "deactivated", "rejected"), "active", False),
    "suspend": (("active",), "suspended", True),
    "deactivate": (("pending", "active", "suspended"), "deactivated", True),
}


async def _row(session: AsyncSession, tenant: Tenant) -> RestaurantAdminRow:
    owner = (
        await session.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .join(Role, Role.id == Membership.role_id)
            .where(Membership.tenant_id == tenant.id, Role.key == "owner")
            .order_by(Membership.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    city = (
        await session.execute(select(Branch.city).where(Branch.tenant_id == tenant.id, Branch.is_primary))
    ).scalar_one_or_none()
    live = await live_subscription(session, tenant.id)
    return RestaurantAdminRow(
        **{k: getattr(tenant, k) for k in RestaurantAdminRow.model_fields if hasattr(tenant, k)},
        owner=OwnerOut.model_validate(owner) if owner else None,
        city=city,
        subscription=subscription_out(*live) if live else None,
    )


async def list_restaurants(
    session: AsyncSession, *, status: str | None, q: str | None, page: int, page_size: int
) -> Page[RestaurantAdminRow]:
    await use_system(session)
    stmt = select(Tenant)
    if status:
        stmt = stmt.where(Tenant.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Tenant.name.ilike(like), Tenant.slug.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    tenants = (
        (await session.execute(stmt.order_by(Tenant.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
        .scalars()
        .all()
    )
    return Page(items=[await _row(session, t) for t in tenants], page=page, page_size=page_size, total=total)


async def get_restaurant(session: AsyncSession, tenant_id: uuid.UUID) -> RestaurantAdminRow:
    await use_system(session)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Restaurant not found.")
    return await _row(session, tenant)


async def change_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    action: StatusAction,
    reason: str | None,
    *,
    actor_user_id: uuid.UUID,
    ip: str | None,
) -> RestaurantAdminRow:
    await use_system(session)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Restaurant not found.")

    allowed_from, new_status, reason_required = TRANSITIONS[action]
    if tenant.status not in allowed_from:
        raise AppError(
            f"Cannot {action} a restaurant that is {tenant.status}.",
            code="INVALID_STATUS_TRANSITION",
            status_code=409,
            details={"current_status": tenant.status, "action": action},
        )
    reason = (reason or "").strip() or None
    if reason_required and not reason:
        raise AppError("Please give a reason.", code="REASON_REQUIRED", status_code=422)

    old = tenant.status
    tenant.status = new_status
    tenant.status_reason = reason
    if action == "approve":
        tenant.approved_at = datetime.now(UTC)
        tenant.approved_by = actor_user_id

    write_audit(
        session,
        action=f"restaurant.{action}",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=actor_user_id,
        diff={"status": [old, new_status]},
        reason=reason,
        ip=ip,
    )
    record_event(
        session,
        "restaurant.status_changed",
        {"tenant_id": str(tenant.id), "status": new_status, "previous": old},
        tenant_id=tenant.id,
        room="platform:admin",
    )
    await session.commit()
    # Suspending/deactivating must take the storefront offline immediately, not after the cache expires.
    from app.services.profile import invalidate_storefront  # local import: profile imports access → no cycle here

    await invalidate_storefront(tenant.slug)
    return await _row(session, tenant)

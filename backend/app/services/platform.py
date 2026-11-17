# ruff: noqa: E501  (website copy is long text)
"""Platform content (WaitLess website), support desk, audit log viewer and notification templates (PRD §16)."""

import time as _time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, use_system
from app.core.errors import AppError, NotFoundError
from app.models import Tenant, User
from app.models.platform import AuditLog
from app.models.platform_admin import NotificationTemplate, PlatformContent, SupportNote
from app.models.support import SupportTicket
from app.services.audit import write_audit

# ---------- website content ----------

CONTENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "home": {
        "eyebrow": "Restaurant technology platform",
        "title": "Skip the wait.",
        "title_script": "Dine delightfully.",
        "lead": "Find a restaurant, book or queue from your phone, and get your food within 15 minutes — or a discount that grows while you wait.",
    },
    "how_it_works": {
        "title": "From kitchen to your table",
        "steps": [
            {"icon": "search", "title": "Discover", "text": "Find restaurants near you and see if they are open right now."},
            {"icon": "event_available", "title": "Book or queue", "text": "Reserve a table or join the digital queue from your phone."},
            {"icon": "restaurant_menu", "title": "Order", "text": "Browse the menu and order — even before you arrive with a paid booking."},
            {"icon": "timer", "title": "Served in 15", "text": "Late food? Your discount grows automatically, every 5 minutes."},
        ],
    },
    "features": {
        "title": "Everything a restaurant runs on",
        "items": [
            {"icon": "storefront", "title": "Branded storefront", "text": "Your logo, colours and photos — your own app."},
            {"icon": "groups", "title": "Digital queue", "text": "QR check-in, live position and table-ready alerts."},
            {"icon": "event_seat", "title": "Reservations", "text": "Free or paid bookings with pre-orders."},
            {"icon": "table_restaurant", "title": "Table management", "text": "Live floor map with colour-coded status."},
            {"icon": "menu_book", "title": "Digital menu", "text": "Meal types, categories, variants and add-ons."},
            {"icon": "soup_kitchen", "title": "Kitchen display", "text": "Tickets from accepted to served, in real time."},
            {"icon": "inventory_2", "title": "Inventory", "text": "Recipes, stock movements and low-stock alerts."},
            {"icon": "point_of_sale", "title": "Billing & POS", "text": "Split bills, UPI, cards and instant receipts."},
        ],
    },
    "for_restaurants": {
        "title": "Your brand, your app",
        "benefits": [
            "Turn tables faster with live queue and table status",
            "Fewer no-shows thanks to paid bookings with pre-orders",
            "A promise guests love: served in 15 minutes or it gets cheaper",
            "One dashboard for menu, kitchen, inventory and billing",
            "Your brand front and centre — guests feel they use your own app",
        ],
        "cta": "Start your 14-day free trial",
    },
    "about": {
        "title": "Less waiting.",
        "title_script": "More dining.",
        "lead": "WaitLess helps restaurants digitise their operations and helps guests avoid unnecessary waiting — from finding a table to the moment the bill is paid.",
        "vision": "Every meal out should start on time. No guessing at the door, no wondering where the food is.",
        "mission": "Give every restaurant — from a single café to a chain — its own branded app and the tools to serve faster.",
    },
    "contact": {
        "email": "hello@waitless.app",
        "phone": "",
        "address": "",
        "hours": "Monday–Saturday, 10:00–19:00",
    },
    "branding": {"tagline": "Skip the Wait. Dine Delightfully!", "announcement": ""},
    "terms": {
        "title": "Terms of use",
        "updated": "",
        "body": "These terms govern your use of WaitLess. Restaurants are responsible for their menus, prices and service. "
        "Guests agree to the booking and cancellation policy shown by each restaurant.\n\n"
        "Replace this text from Super Admin → Content.",
    },
    "privacy": {
        "title": "Privacy policy",
        "updated": "",
        "body": "WaitLess stores the details needed to run your bookings, queue places, orders and bills. Restaurants see "
        "only the data of their own guests. We never sell personal data.\n\nReplace this text from Super Admin → Content.",
    },
}
_MAX_CONTENT_CHARS = 30_000


async def content_all(session: AsyncSession) -> dict[str, Any]:
    await use_system(session)
    saved = {c.key: c.data for c in (await session.execute(select(PlatformContent))).scalars()}
    return {k: {**v, **saved.get(k, {})} for k, v in CONTENT_DEFAULTS.items()}


async def save_content(session: AsyncSession, key: str, data: dict[str, Any], actor: uuid.UUID) -> dict[str, Any]:
    if key not in CONTENT_DEFAULTS:
        raise NotFoundError("Unknown section.")
    import json

    if len(json.dumps(data)) > _MAX_CONTENT_CHARS:
        raise AppError("This section is too long.", code="CONTENT_TOO_LONG", status_code=422)
    allowed = set(CONTENT_DEFAULTS[key])
    unknown = set(data) - allowed
    if unknown:
        raise AppError(f"Unknown fields: {', '.join(sorted(unknown))}.", code="UNKNOWN_FIELDS", status_code=422)
    for k, v in data.items():
        if type(v) is not type(CONTENT_DEFAULTS[key][k]):
            raise AppError(f"{k} has the wrong type.", code="INVALID_FIELD", status_code=422)
    await use_system(session)
    row = await session.get(PlatformContent, key)
    if row is None:
        session.add(PlatformContent(key=key, data=data, updated_by=actor))
    else:
        row.data, row.updated_by = data, actor
    write_audit(
        session, action="platform.content_updated", entity="platform_content", entity_id=key, actor_user_id=actor
    )
    await session.commit()
    _content_cache.clear()
    return (await content_all(session))[key]


_content_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def public_content(session: AsyncSession) -> dict[str, Any]:
    """The website reads this on every page; cached for 60 s (cleared on save)."""
    hit = _content_cache.get("all")
    if hit and hit[0] > _time.monotonic():
        return hit[1]
    data = await content_all(session)
    from app.services.saas import platform_settings

    settings = await platform_settings(session)
    data["platform"] = {
        "support_email": settings["support_email"],
        "support_phone": settings["support_phone"],
        "maintenance_banner": settings["maintenance_banner"],
        "allow_registration": settings["allow_registration"],
    }
    _content_cache["all"] = (_time.monotonic() + 60, data)
    return data


def clear_cache() -> None:
    _content_cache.clear()


# ---------- support desk ----------


def _ticket(
    t: SupportTicket, tenant: Tenant | None, assignee: User | None, notes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "source": t.source,
        "topic": t.topic,
        "name": t.name,
        "email": t.email,
        "phone": t.phone,
        "message": t.message,
        "status": t.status,
        "priority": t.priority,
        "assigned_to_id": t.assigned_to_id,
        "assigned_to_name": assignee.full_name if assignee else None,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "resolved_at": t.resolved_at,
        "notes": notes,
    }


async def tickets(
    session: AsyncSession, status: str | None, q: str | None, tenant_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    await use_system(session)
    stmt = select(SupportTicket).order_by(
        (SupportTicket.status.in_(("open", "in_progress"))).desc(),
        func.array_position(["urgent", "high", "normal", "low"], SupportTicket.priority),
        SupportTicket.created_at.desc(),
    )
    if status == "active":
        stmt = stmt.where(SupportTicket.status.in_(("open", "in_progress")))
    elif status:
        stmt = stmt.where(SupportTicket.status == status)
    if tenant_id:
        stmt = stmt.where(SupportTicket.tenant_id == tenant_id)
    if q:
        stmt = stmt.where(
            or_(
                SupportTicket.name.ilike(f"%{q}%"),
                SupportTicket.email.ilike(f"%{q}%"),
                SupportTicket.message.ilike(f"%{q}%"),
            )
        )
    rows = list((await session.execute(stmt.limit(300))).scalars())
    tenants = (
        {
            t.id: t
            for t in (
                await session.execute(select(Tenant).where(Tenant.id.in_({r.tenant_id for r in rows if r.tenant_id})))
            ).scalars()
        }
        if rows
        else {}
    )
    users = (
        {
            u.id: u
            for u in (
                await session.execute(
                    select(User).where(User.id.in_({r.assigned_to_id for r in rows if r.assigned_to_id}))
                )
            ).scalars()
        }
        if rows
        else {}
    )
    return [
        _ticket(
            r,
            tenants.get(r.tenant_id) if r.tenant_id else None,
            users.get(r.assigned_to_id) if r.assigned_to_id else None,
        )
        for r in rows
    ]


async def ticket(session: AsyncSession, ticket_id: uuid.UUID) -> dict[str, Any]:
    await use_system(session)
    t = await session.get(SupportTicket, ticket_id, populate_existing=True)
    if t is None:
        raise NotFoundError("Ticket not found.")
    notes = []
    for n, u in (
        await session.execute(
            select(SupportNote, User)
            .outerjoin(User, User.id == SupportNote.author_id)
            .where(SupportNote.ticket_id == t.id)
            .order_by(SupportNote.created_at)
        )
    ).tuples():
        notes.append({"id": n.id, "body": n.body, "author": u.full_name if u else None, "created_at": n.created_at})
    tenant = await session.get(Tenant, t.tenant_id) if t.tenant_id else None
    assignee = await session.get(User, t.assigned_to_id) if t.assigned_to_id else None
    return _ticket(t, tenant, assignee, notes)


async def update_ticket(
    session: AsyncSession, ticket_id: uuid.UUID, data: dict[str, Any], actor: uuid.UUID
) -> dict[str, Any]:
    await use_system(session)
    t = await session.get(SupportTicket, ticket_id)
    if t is None:
        raise NotFoundError("Ticket not found.")
    if "status" in data:
        if data["status"] not in ("open", "in_progress", "resolved", "closed"):
            raise AppError("Unknown status.", code="INVALID_STATUS", status_code=422)
        t.status = data["status"]
        t.resolved_at = datetime.now(UTC) if t.status in ("resolved", "closed") else None
    if "priority" in data:
        if data["priority"] not in ("low", "normal", "high", "urgent"):
            raise AppError("Unknown priority.", code="INVALID_PRIORITY", status_code=422)
        t.priority = data["priority"]
    if "assigned_to_id" in data:
        aid = data["assigned_to_id"]
        if aid:
            u = await session.get(User, uuid.UUID(str(aid)))
            if u is None or not u.is_super_admin:
                raise AppError("Assign to a WaitLess administrator.", code="INVALID_ASSIGNEE", status_code=422)
        t.assigned_to_id = uuid.UUID(str(aid)) if aid else None
    write_audit(
        session,
        action="support.ticket_updated",
        entity="support_ticket",
        entity_id=t.id,
        tenant_id=t.tenant_id,
        actor_user_id=actor,
        diff=data,
    )
    await session.commit()
    return await ticket(session, t.id)


async def add_note(session: AsyncSession, ticket_id: uuid.UUID, body: str, actor: uuid.UUID) -> dict[str, Any]:
    await use_system(session)
    if await session.get(SupportTicket, ticket_id) is None:
        raise NotFoundError("Ticket not found.")
    if not body.strip():
        raise AppError("Write a note.", code="NOTE_REQUIRED", status_code=422)
    session.add(SupportNote(ticket_id=ticket_id, author_id=actor, body=body.strip()[:4000]))
    await session.commit()
    return await ticket(session, ticket_id)


async def restaurant_ticket(
    session: AsyncSession, tenant_id: uuid.UUID, user: User, topic: str, message: str
) -> dict[str, Any]:
    """A restaurant asks WaitLess for help (Settings → Help)."""
    await use_system(session)
    if topic not in ("general", "billing", "technical", "complaint", "other"):
        raise AppError("Choose a topic.", code="INVALID_TOPIC", status_code=422)
    if not 10 <= len(message.strip()) <= 4000:
        raise AppError("Describe the problem in 10–4000 characters.", code="INVALID_MESSAGE", status_code=422)
    t = SupportTicket(
        tenant_id=tenant_id,
        source="restaurant",
        topic=topic,
        name=user.full_name,
        email=user.email or "",
        phone=user.phone,
        message=message.strip(),
        created_by_id=user.id,
        priority="high" if topic in ("complaint", "technical") else "normal",
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _ticket(t, None, None)


async def restaurant_tickets(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await tickets(session, None, None, tenant_id)
    return [{k: v for k, v in r.items() if k not in ("assigned_to_id",)} for r in rows]


# ---------- audit log ----------


async def audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    admins_only: bool,
    action: str | None,
    start: date | None,
    end: date | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    await use_system(session)
    stmt = select(AuditLog)
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_id)
    if admins_only:
        stmt = stmt.where(AuditLog.actor_user_id.in_(select(User.id).where(User.is_super_admin)))
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if start:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start, datetime.min.time(), UTC))
    if end:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars()
    )
    users = (
        {
            u.id: u
            for u in (
                await session.execute(
                    select(User).where(User.id.in_({r.actor_user_id for r in rows if r.actor_user_id}))
                )
            ).scalars()
        }
        if rows
        else {}
    )
    tenants = (
        {
            t.id: t
            for t in (
                await session.execute(select(Tenant).where(Tenant.id.in_({r.tenant_id for r in rows if r.tenant_id})))
            ).scalars()
        }
        if rows
        else {}
    )
    return {
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "action": r.action,
                "entity": r.entity,
                "entity_id": r.entity_id,
                "tenant_id": r.tenant_id,
                "tenant_name": tenants[r.tenant_id].name if r.tenant_id in tenants else None,
                "actor_user_id": r.actor_user_id,
                "actor_name": users[r.actor_user_id].full_name if r.actor_user_id in users else None,
                "actor_is_admin": bool(r.actor_user_id in users and users[r.actor_user_id].is_super_admin),
                "diff": r.diff,
                "reason": r.reason,
                "ip": str(r.ip) if r.ip else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def admins(session: AsyncSession) -> list[dict[str, Any]]:
    await use_system(session)
    return [
        {"id": u.id, "name": u.full_name, "email": u.email}
        for u in (await session.execute(select(User).where(User.is_super_admin).order_by(User.full_name))).scalars()
    ]


# ---------- notification templates ----------

TEMPLATE_EVENTS: dict[str, str] = {
    "queue.token": "Guest joined the queue",
    "queue.table_ready": "Queue: your table is ready",
    "queue.cancelled": "Queue place cancelled",
    "reservation.confirmed": "Booking confirmed",
    "reservation.cancelled": "Booking cancelled",
    "reservation.expired": "Booking expired (no-show)",
    "order.ready": "Order ready",
    "inventory.low_stock": "Stock low (to staff)",
}
_tpl_cache: dict[str, Any] = {"at": 0.0, "rows": {}}


async def templates(session: AsyncSession) -> list[dict[str, Any]]:
    await use_system(session)
    saved = {(t.event, t.channel): t for t in (await session.execute(select(NotificationTemplate))).scalars()}
    out = []
    for event, label in TEMPLATE_EVENTS.items():
        t = saved.get((event, "in_app"))
        out.append(
            {
                "event": event,
                "label": label,
                "channel": "in_app",
                "title": t.title if t else "{title}",
                "body": t.body if t else "{body}",
                "enabled": t.enabled if t else True,
                "customised": t is not None,
            }
        )
    return out


async def save_template(
    session: AsyncSession, event: str, title: str, body: str, enabled: bool, actor: uuid.UUID
) -> list[dict[str, Any]]:
    if event not in TEMPLATE_EVENTS:
        raise NotFoundError("Unknown event.")
    if not title.strip() or len(title) > 120 or not body.strip() or len(body) > 500:
        raise AppError("Title up to 120 and text up to 500 characters.", code="INVALID_TEMPLATE", status_code=422)
    for text in (title, body):
        try:
            text.format_map(_Blank())
        except (ValueError, IndexError) as exc:
            raise AppError("Check the {placeholders}.", code="INVALID_TEMPLATE", status_code=422) from exc
    await use_system(session)
    row = (
        await session.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.event == event, NotificationTemplate.channel == "in_app"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            NotificationTemplate(event=event, channel="in_app", title=title.strip(), body=body.strip(), enabled=enabled)
        )
    else:
        row.title, row.body, row.enabled = title.strip(), body.strip(), enabled
    write_audit(
        session,
        action="platform.template_updated",
        entity="notification_template",
        entity_id=event,
        actor_user_id=actor,
    )
    await session.commit()
    _tpl_cache["at"] = 0.0
    return await templates(session)


class _Blank(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return ""


async def render(event: str, title: str, body: str, params: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """Apply the Super Admin's wording; None = this notification is switched off. Cached 60 s."""
    if _tpl_cache["at"] < _time.monotonic():
        try:
            async with get_sessionmaker()() as s:
                await use_system(s)
                _tpl_cache["rows"] = {
                    t.event: t
                    for t in (
                        await s.execute(select(NotificationTemplate).where(NotificationTemplate.channel == "in_app"))
                    ).scalars()
                }
                _tpl_cache["at"] = _time.monotonic() + 60
        except Exception:  # pragma: no cover - notifications must never break the caller
            return title, body
    t = _tpl_cache["rows"].get(event)
    if t is None:
        return title, body
    if not t.enabled:
        return None
    values = _Blank({**(params or {}), "title": title, "body": body})
    return t.title.format_map(values), t.body.format_map(values)

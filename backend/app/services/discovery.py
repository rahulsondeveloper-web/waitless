"""Restaurant discovery (PRD §2.1) and the public contact form.

Discovery reads across tenants, so it runs with an explicit platform context and an explicit
`status = 'active' AND is_published` filter — the same rule the tenants RLS policy enforces for
anonymous reads. Only public storefront fields are returned.
"""

import math
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.models import Branch, Tenant
from app.models.profile import BusinessHours, MediaFile, RestaurantBranding, RestaurantProfile
from app.models.support import SupportTicket
from app.schemas.discovery import ContactRequest, ContactResponse, DiscoveryCard, DiscoveryFilters, DiscoveryPage
from app.services.hours import open_status
from app.services.media import media_url

MAX_CANDIDATES = 500  # filtered/sorted in memory; move to SQL (PostGIS / earthdistance) when the platform grows


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _visible():  # type: ignore[no-untyped-def]
    return (Tenant.status == "active") & Tenant.is_published


async def discover(
    session: AsyncSession,
    *,
    q: str | None,
    city: str | None,
    cuisine: str | None,
    restaurant_type: str | None,
    open_now: bool,
    lat: float | None,
    lng: float | None,
    radius_km: float | None,
    page: int,
    page_size: int,
) -> DiscoveryPage:
    await use_system(session)
    stmt = (
        select(Tenant, RestaurantProfile, RestaurantBranding, Branch)
        .join(RestaurantProfile, RestaurantProfile.tenant_id == Tenant.id)
        .join(RestaurantBranding, RestaurantBranding.tenant_id == Tenant.id)
        .outerjoin(Branch, (Branch.tenant_id == Tenant.id) & Branch.is_primary)
        .where(_visible())
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Tenant.name.ilike(like),
                RestaurantProfile.short_description.ilike(like),
                func.array_to_string(Tenant.cuisines, " ").ilike(like),
                Branch.city.ilike(like),
            )
        )
    if city:
        stmt = stmt.where(Branch.city.ilike(city.strip()))
    if cuisine:
        stmt = stmt.where(func.lower(func.array_to_string(Tenant.cuisines, "|")).contains(cuisine.strip().lower()))
    if restaurant_type:
        stmt = stmt.where(Tenant.restaurant_type == restaurant_type)
    rows = (await session.execute(stmt.order_by(Tenant.name).limit(MAX_CANDIDATES))).tuples().all()

    branch_ids = [b.id for *_, b in rows if b is not None]
    hours: dict = defaultdict(list)
    if branch_ids:
        for h in (
            await session.execute(select(BusinessHours).where(BusinessHours.branch_id.in_(branch_ids)))
        ).scalars():
            hours[h.branch_id].append(h)
    media_ids = {m for _, p, br, _ in rows for m in (p.cover_media_id, br.logo_media_id) if m}
    media = (
        {m.id: m for m in (await session.execute(select(MediaFile).where(MediaFile.id.in_(media_ids)))).scalars()}
        if media_ids
        else {}
    )

    cards: list[DiscoveryCard] = []
    for tenant, profile, branding, branch in rows:
        status = open_status(hours.get(branch.id, []) if branch else [], branch.timezone if branch else "Asia/Kolkata")
        if open_now and not status.is_open:
            continue
        distance = None
        if (
            lat is not None
            and lng is not None
            and branch is not None
            and branch.lat is not None
            and branch.lng is not None
        ):
            distance = round(haversine_km(lat, lng, float(branch.lat), float(branch.lng)), 1)
            if radius_km is not None and distance > radius_km:
                continue
        elif lat is not None and lng is not None and radius_km is not None:
            continue  # no location → cannot be "within X km"
        cards.append(
            DiscoveryCard(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                short_description=profile.short_description,
                restaurant_type=tenant.restaurant_type,
                cuisines=tenant.cuisines,
                city=branch.city if branch else None,
                address=branch.address_line if branch else None,
                lat=branch.lat if branch else None,
                lng=branch.lng if branch else None,
                logo_url=media_url(media.get(branding.logo_media_id)) if branding.logo_media_id else None,
                cover_url=media_url(media.get(profile.cover_media_id)) if profile.cover_media_id else None,
                primary_color=(branding.tokens or {}).get("primary"),
                open_now=status.is_open,
                today_hours=status.today,
                distance_km=distance,
            )
        )
    if lat is not None and lng is not None:
        cards.sort(key=lambda c: (c.distance_km is None, c.distance_km or 0, c.name))
    start = (page - 1) * page_size
    return DiscoveryPage(items=cards[start : start + page_size], page=page, page_size=page_size, total=len(cards))


async def filters(session: AsyncSession) -> DiscoveryFilters:
    await use_system(session)
    cities = (
        (
            await session.execute(
                select(Branch.city)
                .join(Tenant, Tenant.id == Branch.tenant_id)
                .where(_visible(), Branch.is_active)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    tenants = (await session.execute(select(Tenant.cuisines, Tenant.restaurant_type).where(_visible()))).tuples().all()
    cuisines = sorted({c for cs, _ in tenants for c in cs}, key=str.lower)
    types = sorted({t for _, t in tenants})
    return DiscoveryFilters(cities=sorted(set(cities), key=str.lower), cuisines=cuisines, restaurant_types=types)


async def submit_contact(session: AsyncSession, data: ContactRequest) -> ContactResponse:
    ok = ContactResponse(
        received=True, message="Thanks! The WaitLess team will get back to you within one working day."
    )
    if data.website:  # honeypot filled → silently accept and drop
        return ok
    await use_system(session)
    session.add(
        SupportTicket(
            source="contact_form",
            topic=data.topic,
            name=data.name.strip(),
            email=str(data.email).lower(),
            phone=data.phone,
            message=data.message.strip(),
        )
    )
    await session.commit()
    return ok

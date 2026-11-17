"""Restaurant registration (PRD §4): tenant, primary branch, owner account, role, slug, settings, trial."""

import copy
import re
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import use_system
from app.core.errors import AppError, ConflictError
from app.core.events import record_event
from app.core.security import hash_password_async
from app.models import Branch, Membership, Plan, RestaurantBranding, RestaurantProfile, Role, Subscription, Tenant, User
from app.schemas.tenancy import RestaurantRegistration
from app.seeds.menu_seed import seed_menu_taxonomy
from app.seeds.reference import DEFAULT_TENANT_SETTINGS
from app.services.audit import write_audit

# Slugs that would collide with routes or look official.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "about",
        "auth",
        "customer",
        "help",
        "login",
        "logout",
        "media",
        "new",
        "r",
        "register",
        "restaurant",
        "restaurant-admin",
        "restaurants",
        "settings",
        "status",
        "super-admin",
        "support",
        "waitless",
        "www",
    }
)
SLUG_MAX = 60


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:SLUG_MAX].strip("-")


async def _slug_taken(session: AsyncSession, slug: str) -> bool:
    if slug in RESERVED_SLUGS:
        return True
    return (await session.execute(select(func.count()).select_from(Tenant).where(Tenant.slug == slug))).scalar_one() > 0


async def suggest_slug(session: AsyncSession, name: str, city: str | None = None) -> str:
    await use_system(session)
    base = slugify(name) or "restaurant"
    candidates = [base]
    if city:
        candidates.append(f"{base}-{slugify(city)}"[:SLUG_MAX].strip("-"))
    for candidate in candidates:
        if not await _slug_taken(session, candidate):
            return candidate
    n = 2
    while await _slug_taken(session, f"{base}-{n}"):
        n += 1
    return f"{base}-{n}"


async def check_slug(session: AsyncSession, slug: str) -> tuple[str, bool]:
    await use_system(session)
    clean = slugify(slug)
    return clean, bool(clean) and len(clean) >= 3 and not await _slug_taken(session, clean)


async def register_restaurant(
    session: AsyncSession,
    data: RestaurantRegistration,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> tuple[Tenant, User]:
    """Runs in one transaction; either everything is created or nothing is."""
    settings = get_settings()
    await use_system(session)

    if (await session.execute(select(User.id).where(User.email == str(data.email)))).first():
        raise ConflictError("An account with this email already exists. Please sign in.", code="EMAIL_TAKEN")
    if (await session.execute(select(User.id).where(User.phone == data.mobile))).first():
        raise ConflictError("An account with this mobile number already exists. Please sign in.", code="PHONE_TAKEN")

    # 5. Unique slug
    if data.preferred_slug:
        slug, available = await check_slug(session, data.preferred_slug)
        if not available:
            raise ConflictError("That web address is not available.", code="SLUG_TAKEN", details={"slug": slug})
    else:
        slug = await suggest_slug(session, data.restaurant_name, data.city)

    # 1. Tenant (+ 6. default settings)
    tenant = Tenant(
        name=data.restaurant_name.strip(),
        slug=slug,
        status="pending",
        restaurant_type=data.restaurant_type,
        cuisines=data.cuisines,
        declared_branch_count=data.number_of_branches,
        settings=copy.deepcopy(DEFAULT_TENANT_SETTINGS),
    )
    session.add(tenant)
    await session.flush()
    # Empty profile + default (Remelle) branding — completed by the owner in the dashboard (PRD §4 step 7).
    session.add(RestaurantProfile(tenant_id=tenant.id))
    session.add(RestaurantBranding(tenant_id=tenant.id, tokens={}))
    await seed_menu_taxonomy(session, tenant.id)  # PRD §7 default structure, editable by the owner

    # 2. Primary branch
    session.add(
        Branch(
            tenant_id=tenant.id,
            name=f"{tenant.name} - {data.city}",
            address_line=data.address,
            city=data.city,
            state=data.state,
            country=data.country,
            phone=data.mobile,
            is_primary=True,
        )
    )

    # 3. Owner account
    owner = User(
        email=str(data.email).lower(),
        phone=data.mobile,
        full_name=data.owner_name.strip(),
        password_hash=await hash_password_async(data.password),
    )
    session.add(owner)
    await session.flush()

    # 4. Restaurant Admin (Owner) role, all branches
    owner_role = (
        await session.execute(select(Role).where(Role.tenant_id.is_(None), Role.key == "owner"))
    ).scalar_one_or_none()
    if owner_role is None:
        raise AppError("Reference data missing. Run `python -m app.cli seed`.", code="SEED_MISSING", status_code=500)
    session.add(Membership(tenant_id=tenant.id, user_id=owner.id, role_id=owner_role.id, all_branches=True))

    # Trial subscription (decision D18)
    plan = (await session.execute(select(Plan).where(Plan.code == settings.trial_plan_code))).scalar_one_or_none()
    if plan is not None:
        now = datetime.now(UTC)
        trial_end = now + timedelta(days=plan.trial_days)
        session.add(
            Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status="trialing",
                trial_ends_at=trial_end,
                current_period_start=now,
                current_period_end=trial_end,
            )
        )

    write_audit(
        session,
        action="restaurant.registered",
        entity="tenant",
        entity_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=actor_user_id or owner.id,
        diff={"name": tenant.name, "slug": slug, "by_super_admin": actor_user_id is not None},
        ip=ip,
    )
    record_event(
        session,
        "restaurant.registered",
        {"tenant_id": str(tenant.id), "name": tenant.name, "slug": slug},
        tenant_id=tenant.id,
        room="platform:admin",
    )
    await session.commit()
    return tenant, owner

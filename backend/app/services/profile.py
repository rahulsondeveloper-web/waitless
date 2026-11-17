"""Restaurant profile & branding management (PRD §5) and the public storefront read model (PRD §6).

Every function receives a TenantContext whose tenant is already applied to the session (RLS), so
queries never need — and never trust — a tenant id from the request.
"""

import json
import uuid

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import use_tenant
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Branch, Tenant
from app.models.profile import (
    BusinessHours,
    GalleryImage,
    MediaFile,
    RestaurantBranding,
    RestaurantProfile,
    SocialLink,
)
from app.schemas.menu import PublicMenu
from app.schemas.profile import (
    BranchLocationUpdate,
    BrandingOut,
    BrandingUpdate,
    ChecklistItem,
    GalleryItemOut,
    GalleryOut,
    HoursDay,
    HoursOut,
    HoursUpdate,
    ProfileOut,
    ProfileUpdate,
    PublicBranch,
    PublishChecklist,
    SocialLinkOut,
    SocialLinksUpdate,
    StorefrontOut,
)
from app.schemas.tenancy import BranchOut
from app.services.access import TenantContext, live_subscription
from app.services.audit import write_audit
from app.services.hours import open_status
from app.services.media import delete_files, media_url, store_image
from app.services.storefront_cache import cache_get as _cache_get
from app.services.storefront_cache import (
    cache_key,
    invalidate_storefront,  # noqa: F401  (re-exported for other services)
)
from app.services.storefront_cache import cache_set as _cache_set

# ---------- helpers ----------


async def _tenant(session: AsyncSession, ctx: TenantContext) -> Tenant:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None  # RLS + context guarantee it
    return tenant


async def ensure_profile_rows(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[RestaurantProfile, RestaurantBranding]:
    profile = await session.get(RestaurantProfile, tenant_id)
    if profile is None:
        profile = RestaurantProfile(tenant_id=tenant_id)
        session.add(profile)
    branding = await session.get(RestaurantBranding, tenant_id)
    if branding is None:
        branding = RestaurantBranding(tenant_id=tenant_id, tokens={})
        session.add(branding)
    await session.flush()
    return profile, branding


async def _media(session: AsyncSession, media_id: uuid.UUID | None) -> MediaFile | None:
    return await session.get(MediaFile, media_id) if media_id else None


async def _branding_out(session: AsyncSession, branding: RestaurantBranding) -> BrandingOut:
    tokens = {k: v for k, v in (branding.tokens or {}).items() if isinstance(v, str)}
    return BrandingOut(
        logo_url=media_url(await _media(session, branding.logo_media_id)),
        tokens=tokens,
        button_style=branding.button_style,  # type: ignore[arg-type]
        mode=branding.mode,  # type: ignore[arg-type]
        version=branding.version,
        is_default=not tokens and branding.button_style == "pill" and branding.mode == "light",
    )


async def _branch(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, permission: str) -> Branch:
    branch = (await session.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if branch is None:  # other tenants' branches are invisible (RLS) → same answer as "does not exist"
        raise NotFoundError("Branch not found.")
    if not ctx.can_act_in_branch(permission, branch.id):
        raise ForbiddenError("You do not have access to this branch.", code="BRANCH_FORBIDDEN")
    return branch


# ---------- profile ----------


async def get_profile(session: AsyncSession, ctx: TenantContext) -> ProfileOut:
    tenant = await _tenant(session, ctx)
    profile, _ = await ensure_profile_rows(session, ctx.tenant_id)
    return ProfileOut(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        is_published=tenant.is_published,
        restaurant_type=tenant.restaurant_type,
        cuisines=tenant.cuisines,
        short_description=profile.short_description,
        description=profile.description,
        about_us=profile.about_us,
        contact_phone=profile.contact_phone,
        contact_email=profile.contact_email,
        website=profile.website,
        cover_url=media_url(await _media(session, profile.cover_media_id)),
    )


async def update_profile(session: AsyncSession, ctx: TenantContext, data: ProfileUpdate) -> ProfileOut:
    tenant = await _tenant(session, ctx)
    profile, _ = await ensure_profile_rows(session, ctx.tenant_id)
    tenant.name = data.name.strip()
    tenant.restaurant_type = data.restaurant_type
    tenant.cuisines = data.cuisines
    profile.short_description = data.short_description.strip()
    profile.description = data.description.strip()
    profile.about_us = data.about_us.strip()
    profile.contact_phone = data.contact_phone
    profile.contact_email = str(data.contact_email).lower() if data.contact_email else None
    profile.website = str(data.website) if data.website else None
    await session.commit()
    await invalidate_storefront(tenant.slug)
    return await get_profile(session, ctx)


async def set_cover(session: AsyncSession, ctx: TenantContext, upload: UploadFile) -> ProfileOut:
    profile, _ = await ensure_profile_rows(session, ctx.tenant_id)
    media = await store_image(session, tenant_id=ctx.tenant_id, kind="cover", upload=upload, actor_user_id=ctx.user_id)
    old = await _media(session, profile.cover_media_id)
    profile.cover_media_id = media.id
    old_keys = [old.storage_key] if old else []
    if old:
        await session.delete(old)
    await session.commit()
    await delete_files(old_keys)
    await invalidate_storefront(ctx.tenant_slug)
    return await get_profile(session, ctx)


async def remove_cover(session: AsyncSession, ctx: TenantContext) -> ProfileOut:
    profile, _ = await ensure_profile_rows(session, ctx.tenant_id)
    old = await _media(session, profile.cover_media_id)
    if old:
        profile.cover_media_id = None
        await session.delete(old)
        await session.commit()
        await delete_files([old.storage_key])
        await invalidate_storefront(ctx.tenant_slug)
    return await get_profile(session, ctx)


# ---------- branding ----------


async def get_branding(session: AsyncSession, ctx: TenantContext) -> BrandingOut:
    _, branding = await ensure_profile_rows(session, ctx.tenant_id)
    return await _branding_out(session, branding)


async def update_branding(session: AsyncSession, ctx: TenantContext, data: BrandingUpdate) -> BrandingOut:
    _, branding = await ensure_profile_rows(session, ctx.tenant_id)
    branding.tokens = {k: v.lower() for k, v in data.tokens.model_dump(exclude_none=True).items()}
    branding.button_style = data.button_style
    branding.mode = data.mode
    branding.version += 1
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await _branding_out(session, branding)


async def reset_branding(session: AsyncSession, ctx: TenantContext) -> BrandingOut:
    """Back to the default (Restaurant Remelle) theme. The logo is kept — it is content, not theme."""
    _, branding = await ensure_profile_rows(session, ctx.tenant_id)
    previous = {"tokens": branding.tokens, "button_style": branding.button_style, "mode": branding.mode}
    branding.tokens = {}
    branding.button_style = "pill"
    branding.mode = "light"
    branding.version += 1
    write_audit(
        session,
        action="branding.reset",
        entity="restaurant_branding",
        entity_id=ctx.tenant_id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"before": previous},
    )
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await _branding_out(session, branding)


async def set_logo(session: AsyncSession, ctx: TenantContext, upload: UploadFile) -> BrandingOut:
    _, branding = await ensure_profile_rows(session, ctx.tenant_id)
    media = await store_image(session, tenant_id=ctx.tenant_id, kind="logo", upload=upload, actor_user_id=ctx.user_id)
    old = await _media(session, branding.logo_media_id)
    branding.logo_media_id = media.id
    branding.version += 1
    old_keys = [old.storage_key] if old else []
    if old:
        await session.delete(old)
    await session.commit()
    await delete_files(old_keys)
    await invalidate_storefront(ctx.tenant_slug)
    return await _branding_out(session, branding)


async def remove_logo(session: AsyncSession, ctx: TenantContext) -> BrandingOut:
    _, branding = await ensure_profile_rows(session, ctx.tenant_id)
    old = await _media(session, branding.logo_media_id)
    if old:
        branding.logo_media_id = None
        branding.version += 1
        await session.delete(old)
        await session.commit()
        await delete_files([old.storage_key])
        await invalidate_storefront(ctx.tenant_slug)
    return await _branding_out(session, branding)


# ---------- gallery (max 5, PRD §5.3) ----------


async def _gallery_items(session: AsyncSession) -> list[GalleryItemOut]:
    rows = await session.execute(
        select(GalleryImage, MediaFile)
        .join(MediaFile, MediaFile.id == GalleryImage.media_id)
        .order_by(GalleryImage.position)
    )
    return [
        GalleryItemOut(
            id=g.id, url=media_url(m) or "", width=m.width, height=m.height, position=g.position, caption=g.caption
        )
        for g, m in rows.tuples()
    ]


async def get_gallery(session: AsyncSession, ctx: TenantContext) -> GalleryOut:
    return GalleryOut(items=await _gallery_items(session), max_photos=get_settings().gallery_max_photos)


async def add_gallery_image(session: AsyncSession, ctx: TenantContext, upload: UploadFile, caption: str) -> GalleryOut:
    limit = get_settings().gallery_max_photos
    # Process the image first (slow), then serialise concurrent uploads on the tenant row.
    media = await store_image(
        session, tenant_id=ctx.tenant_id, kind="gallery", upload=upload, actor_user_id=ctx.user_id
    )
    await session.execute(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())
    used = set((await session.execute(select(GalleryImage.position))).scalars().all())
    if len(used) >= limit:
        key = media.storage_key  # read before rollback expires the object
        await session.rollback()
        await delete_files([key])
        raise ConflictError(
            f"The gallery already has {limit} photos. Remove or replace one first.",
            code="GALLERY_LIMIT_REACHED",
            details={"max_photos": limit},
        )
    position = min(p for p in range(1, limit + 1) if p not in used)
    session.add(GalleryImage(tenant_id=ctx.tenant_id, media_id=media.id, position=position, caption=caption.strip()))
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await get_gallery(session, ctx)


async def _gallery_item(session: AsyncSession, item_id: uuid.UUID) -> GalleryImage:
    item = (await session.execute(select(GalleryImage).where(GalleryImage.id == item_id))).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Photo not found.")
    return item


async def replace_gallery_image(
    session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, upload: UploadFile
) -> GalleryOut:
    item = await _gallery_item(session, item_id)
    media = await store_image(
        session, tenant_id=ctx.tenant_id, kind="gallery", upload=upload, actor_user_id=ctx.user_id
    )
    old = await _media(session, item.media_id)
    item.media_id = media.id
    await session.flush()
    old_keys = [old.storage_key] if old else []
    if old:
        await session.delete(old)
    await session.commit()
    await delete_files(old_keys)
    await invalidate_storefront(ctx.tenant_slug)
    return await get_gallery(session, ctx)


async def update_gallery_caption(
    session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, caption: str
) -> GalleryOut:
    item = await _gallery_item(session, item_id)
    item.caption = caption.strip()
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await get_gallery(session, ctx)


async def delete_gallery_image(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID) -> GalleryOut:
    item = await _gallery_item(session, item_id)
    media = await _media(session, item.media_id)
    media_key = media.storage_key if media else None
    # Explicit deletes (the media FK cascades to the gallery row; ORM-ordered deletes could double-delete).
    session.expunge(item)
    await session.execute(delete(GalleryImage).where(GalleryImage.id == item_id))
    if media:
        session.expunge(media)
        await session.execute(delete(MediaFile).where(MediaFile.id == media.id))
    # Close the gap so positions stay 1..n (unique constraint is deferred until commit).
    remaining = (await session.execute(select(GalleryImage).order_by(GalleryImage.position))).scalars().all()
    for i, g in enumerate(remaining, start=1):
        g.position = i
    await session.commit()
    if media_key:
        await delete_files([media_key])
    await invalidate_storefront(ctx.tenant_slug)
    return await get_gallery(session, ctx)


async def reorder_gallery(session: AsyncSession, ctx: TenantContext, ids: list[uuid.UUID]) -> GalleryOut:
    items = {g.id: g for g in (await session.execute(select(GalleryImage))).scalars().all()}
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        raise AppError("Send every photo exactly once in the new order.", code="INVALID_ORDER", status_code=422)
    for position, item_id in enumerate(ids, start=1):
        items[item_id].position = position
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await get_gallery(session, ctx)


# ---------- branches: location & hours ----------


async def update_branch_location(
    session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, data: BranchLocationUpdate
) -> BranchOut:
    branch = await _branch(session, ctx, branch_id, "branches.manage")
    for field, value in data.model_dump().items():
        setattr(branch, field, value)
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return BranchOut.model_validate(branch)


async def _hours(session: AsyncSession, branch_id: uuid.UUID) -> list[HoursDay]:
    rows = (
        await session.execute(
            select(BusinessHours).where(BusinessHours.branch_id == branch_id).order_by(BusinessHours.weekday)
        )
    ).scalars()
    return [
        HoursDay(weekday=h.weekday, is_closed=h.is_closed, opens_at=h.opens_at, closes_at=h.closes_at) for h in rows
    ]


async def get_hours(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID) -> HoursOut:
    branch = await _branch(session, ctx, branch_id, "restaurant.profile.view")
    return HoursOut(branch_id=branch.id, days=await _hours(session, branch.id))


async def set_hours(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, data: HoursUpdate) -> HoursOut:
    branch = await _branch(session, ctx, branch_id, "restaurant.profile.manage")
    await session.execute(delete(BusinessHours).where(BusinessHours.branch_id == branch.id))
    for d in data.days:
        session.add(
            BusinessHours(
                tenant_id=ctx.tenant_id,
                branch_id=branch.id,
                weekday=d.weekday,
                is_closed=d.is_closed,
                opens_at=d.opens_at,
                closes_at=d.closes_at,
            )
        )
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return HoursOut(branch_id=branch.id, days=await _hours(session, branch.id))


# ---------- social links ----------


async def get_social_links(session: AsyncSession, ctx: TenantContext) -> list[SocialLinkOut]:
    rows = (await session.execute(select(SocialLink).order_by(SocialLink.sort_order))).scalars()
    return [SocialLinkOut(platform=s.platform, url=s.url) for s in rows]


async def set_social_links(session: AsyncSession, ctx: TenantContext, data: SocialLinksUpdate) -> list[SocialLinkOut]:
    await session.execute(delete(SocialLink))  # RLS: only this tenant's rows
    for i, link in enumerate(data.links):
        session.add(SocialLink(tenant_id=ctx.tenant_id, platform=link.platform, url=str(link.url), sort_order=i))
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return await get_social_links(session, ctx)


# ---------- publishing (PRD §4 "not discoverable until publication requirements are satisfied") ----------


async def publish_checklist(session: AsyncSession, ctx: TenantContext) -> PublishChecklist:
    tenant = await _tenant(session, ctx)
    profile, branding = await ensure_profile_rows(session, ctx.tenant_id)
    primary = (await session.execute(select(Branch).where(Branch.is_primary))).scalar_one_or_none()
    hours_days = (
        (
            await session.execute(
                select(func.count()).select_from(BusinessHours).where(BusinessHours.branch_id == primary.id)
            )
        ).scalar_one()
        if primary
        else 0
    )
    gallery = (await session.execute(select(func.count()).select_from(GalleryImage))).scalar_one()
    live = await live_subscription(session, ctx.tenant_id)

    items = [
        ChecklistItem(
            key="approved",
            label="Approved by WaitLess",
            done=tenant.status == "active",
            required=True,
            hint="WaitLess reviews every new restaurant.",
        ),
        ChecklistItem(
            key="subscription",
            label="Active plan or trial",
            done=live is not None,
            required=True,
            hint="Your trial starts at registration.",
        ),
        ChecklistItem(
            key="description",
            label="Short description",
            done=bool(profile.short_description),
            required=True,
            hint="One or two lines shown on your homepage and in search.",
        ),
        ChecklistItem(
            key="cover",
            label="Cover image",
            done=profile.cover_media_id is not None,
            required=True,
            hint="The large photo at the top of your storefront.",
        ),
        ChecklistItem(
            key="location",
            label="Address pinned on the map",
            done=primary is not None and primary.lat is not None,
            required=True,
            hint="Guests find you with the map pin.",
        ),
        ChecklistItem(
            key="hours",
            label="Opening hours",
            done=hours_days == 7,
            required=True,
            hint="Set every day of the week (mark closed days).",
        ),
        ChecklistItem(
            key="logo",
            label="Logo",
            done=branding.logo_media_id is not None,
            required=False,
            hint="Without a logo your name is shown.",
        ),
        ChecklistItem(
            key="contact",
            label="Contact phone",
            done=bool(profile.contact_phone),
            required=False,
            hint="Shown on your Contact page.",
        ),
        ChecklistItem(
            key="gallery",
            label="Gallery photos",
            done=gallery > 0,
            required=False,
            hint=f"Up to {get_settings().gallery_max_photos} photos.",
        ),
    ]
    from app.services.menu import menu_ready  # local import: menu imports this module's helpers

    items.insert(
        6,
        ChecklistItem(
            key="menu",
            label="At least one dish on the menu",
            done=await menu_ready(session),
            required=True,
            hint="Guests need something to browse.",
        ),
    )
    from app.services.tables import tables_ready

    items.insert(
        7,
        ChecklistItem(
            key="tables",
            label="At least one table",
            done=await tables_ready(session),
            required=True,
            hint="Add your tables so guests can be seated and book.",
        ),
    )
    can_publish = all(i.done for i in items if i.required)
    return PublishChecklist(items=items, can_publish=can_publish, is_published=tenant.is_published)


async def set_published(session: AsyncSession, ctx: TenantContext, published: bool) -> PublishChecklist:
    tenant = await _tenant(session, ctx)
    if published:
        checklist = await publish_checklist(session, ctx)
        if not checklist.can_publish:
            missing = [i.key for i in checklist.items if i.required and not i.done]
            raise ConflictError(
                "Complete the required setup steps before publishing.",
                code="PUBLISH_CHECKLIST_INCOMPLETE",
                details={"missing": missing},
            )
    if tenant.is_published != published:
        tenant.is_published = published
        write_audit(
            session,
            action="restaurant.publish" if published else "restaurant.unpublish",
            entity="tenant",
            entity_id=tenant.id,
            tenant_id=tenant.id,
            actor_user_id=ctx.user_id,
        )
        await session.commit()
        await invalidate_storefront(tenant.slug)
    return await publish_checklist(session, ctx)


# ---------- public storefront ----------


async def _public_tenant(session: AsyncSession, slug: str) -> Tenant:
    # No tenant context and no bypass: RLS only reveals restaurants that are active AND published.
    await use_tenant(session, None)
    tenant = (await session.execute(select(Tenant).where(Tenant.slug == slug.lower()))).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Restaurant not found.")
    await use_tenant(session, tenant.id)
    return tenant


async def build_storefront(session: AsyncSession, tenant: Tenant) -> StorefrontOut:
    """Session must already be scoped to `tenant` (use_tenant). Shared by the public API and owner preview."""
    profile, branding = await ensure_profile_rows(session, tenant.id)
    branches = (
        (await session.execute(select(Branch).where(Branch.is_active).order_by(Branch.is_primary.desc(), Branch.name)))
        .scalars()
        .all()
    )
    social = (await session.execute(select(SocialLink).order_by(SocialLink.sort_order))).scalars().all()
    gallery_count = (await session.execute(select(func.count()).select_from(GalleryImage))).scalar_one()

    public_branches = []
    for b in branches:
        hours = await _hours(session, b.id)
        status = open_status(hours, b.timezone)
        public_branches.append(
            PublicBranch(
                id=b.id,
                name=b.name,
                address_line=b.address_line,
                city=b.city,
                state=b.state,
                country=b.country,
                postal_code=b.postal_code,
                lat=b.lat,
                lng=b.lng,
                phone=b.phone,
                timezone=b.timezone,
                is_primary=b.is_primary,
                hours=hours,
                open_now=status.is_open,
                today_hours=status.today,
            )
        )
    return StorefrontOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        restaurant_type=tenant.restaurant_type,
        cuisines=tenant.cuisines,
        currency=str((tenant.settings or {}).get("currency", "INR")),
        is_published=tenant.is_published and tenant.status == "active",
        short_description=profile.short_description,
        description=profile.description,
        about_us=profile.about_us,
        contact_phone=profile.contact_phone,
        contact_email=profile.contact_email,
        website=profile.website,
        cover_url=media_url(await _media(session, profile.cover_media_id)),
        branding=await _branding_out(session, branding),
        branches=public_branches,
        social_links=[SocialLinkOut(platform=s.platform, url=s.url) for s in social],
        gallery_count=gallery_count,
    )


async def public_storefront(session: AsyncSession, slug: str) -> StorefrontOut:
    key = cache_key(slug)
    if cached := await _cache_get(key):
        return StorefrontOut.model_validate_json(cached)
    tenant = await _public_tenant(session, slug)
    out = await build_storefront(session, tenant)
    await _cache_set(key, out.model_dump_json())
    return out


async def public_branding(session: AsyncSession, slug: str) -> BrandingOut:
    return (await public_storefront(session, slug)).branding


async def public_gallery(session: AsyncSession, slug: str) -> GalleryOut:
    key = cache_key(slug, ":gallery")
    if cached := await _cache_get(key):
        return GalleryOut.model_validate(json.loads(cached))
    await _public_tenant(session, slug)
    out = GalleryOut(items=await _gallery_items(session), max_photos=get_settings().gallery_max_photos)
    await _cache_set(key, out.model_dump_json())
    return out


async def public_menu(session: AsyncSession, slug: str) -> PublicMenu:
    from app.services.menu import build_public_menu

    key = cache_key(slug, ":menu")
    if cached := await _cache_get(key):
        return PublicMenu.model_validate_json(cached)
    tenant = await _public_tenant(session, slug)
    out = await build_public_menu(session, str((tenant.settings or {}).get("currency", "INR")))
    await _cache_set(key, out.model_dump_json())
    return out


# ---------- owner preview (unpublished storefront, never cached) ----------


async def preview_storefront(session: AsyncSession, ctx: TenantContext) -> StorefrontOut:
    return await build_storefront(session, await _tenant(session, ctx))


async def preview_menu(session: AsyncSession, ctx: TenantContext) -> PublicMenu:
    from app.services.menu import build_public_menu

    tenant = await _tenant(session, ctx)
    return await build_public_menu(session, str((tenant.settings or {}).get("currency", "INR")))

"""Digital menu management (PRD §7) and the public menu read model.

All queries run with the tenant applied to the session (RLS), so ids from the request can only ever
match the caller's own rows — a foreign id simply is "not found".
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import Tenant
from app.models.menu import (
    CategoryMealType,
    MealType,
    MenuAddon,
    MenuAddonGroup,
    MenuCategory,
    MenuItem,
    MenuItemAvailability,
    MenuItemBranchOverride,
    MenuItemVariant,
    MenuSubcategory,
)
from app.models.profile import MediaFile
from app.schemas.menu import (
    AddonGroupOut,
    AddonOut,
    AdminMenu,
    AvailabilityOut,
    BranchOverrideIn,
    BranchOverrideOut,
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    ItemIn,
    ItemOptionsIn,
    ItemOut,
    ItemPatch,
    MealTypeIn,
    MealTypeOut,
    MealTypePatch,
    PublicCategory,
    PublicItem,
    PublicMealType,
    PublicMenu,
    SubcategoryIn,
    SubcategoryOut,
    SubcategoryPatch,
    VariantOut,
)
from app.services.access import TenantContext
from app.services.media import delete_files, media_url, store_image
from app.services.storefront_cache import invalidate_storefront

# ---------- loaders ----------


async def _get(session: AsyncSession, model: type, obj_id: uuid.UUID, label: str):  # type: ignore[no-untyped-def]
    obj = (await session.execute(select(model).where(model.id == obj_id))).scalar_one_or_none()
    if obj is None:
        raise NotFoundError(f"{label} not found.")
    return obj


async def _meal_links(session: AsyncSession) -> dict[uuid.UUID, list[uuid.UUID]]:
    links: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for cid, mid in (
        await session.execute(select(CategoryMealType.category_id, CategoryMealType.meal_type_id))
    ).tuples():
        links[cid].append(mid)
    return links


async def _media_urls(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not ids:
        return {}
    rows = (await session.execute(select(MediaFile).where(MediaFile.id.in_(ids)))).scalars()
    return {m.id: media_url(m) for m in rows}


class ItemOptions:
    """Variants, add-on groups, time windows and branch overrides of a set of dishes."""

    def __init__(self) -> None:
        self.variants: dict[uuid.UUID, list[VariantOut]] = defaultdict(list)
        self.groups: dict[uuid.UUID, list[AddonGroupOut]] = defaultdict(list)
        self.windows: dict[uuid.UUID, list[AvailabilityOut]] = defaultdict(list)
        self.overrides: dict[uuid.UUID, list[BranchOverrideOut]] = defaultdict(list)

    def fields(self, item_id: uuid.UUID) -> dict:
        return {
            "variants": self.variants.get(item_id, []),
            "addon_groups": self.groups.get(item_id, []),
            "availability": self.windows.get(item_id, []),
            "branch_overrides": self.overrides.get(item_id, []),
        }


async def load_options(session: AsyncSession, item_ids: list[uuid.UUID] | None = None) -> ItemOptions:
    """None = every dish of the restaurant (RLS scopes the query)."""
    opts = ItemOptions()

    def scoped(stmt, col):  # type: ignore[no-untyped-def]
        return stmt if item_ids is None else stmt.where(col.in_(item_ids))

    variants = await session.execute(
        scoped(select(MenuItemVariant), MenuItemVariant.item_id).order_by(MenuItemVariant.sort_order)
    )
    for v in variants.scalars():
        opts.variants[v.item_id].append(VariantOut(id=v.id, name=v.name, price=v.price))
    groups = (
        (
            await session.execute(
                scoped(select(MenuAddonGroup), MenuAddonGroup.item_id).order_by(MenuAddonGroup.sort_order)
            )
        )
        .scalars()
        .all()
    )
    addons: dict[uuid.UUID, list[AddonOut]] = defaultdict(list)
    if groups:
        rows = await session.execute(
            select(MenuAddon).where(MenuAddon.group_id.in_([g.id for g in groups])).order_by(MenuAddon.sort_order)
        )
        for a in rows.scalars():
            addons[a.group_id].append(AddonOut(id=a.id, name=a.name, price=a.price))
    for g in groups:
        opts.groups[g.item_id].append(
            AddonGroupOut(
                id=g.id, name=g.name, min_select=g.min_select, max_select=g.max_select, addons=addons.get(g.id, [])
            )
        )
    windows = await session.execute(
        scoped(select(MenuItemAvailability), MenuItemAvailability.item_id).order_by(
            MenuItemAvailability.weekday, MenuItemAvailability.from_time
        )
    )
    for w in windows.scalars():
        opts.windows[w.item_id].append(AvailabilityOut(weekday=w.weekday, from_time=w.from_time, to_time=w.to_time))
    overrides = await session.execute(scoped(select(MenuItemBranchOverride), MenuItemBranchOverride.item_id))
    for o in overrides.scalars():
        opts.overrides[o.item_id].append(
            BranchOverrideOut(branch_id=o.branch_id, is_available=o.is_available, price_override=o.price_override)
        )
    return opts


def _item_out(i: MenuItem, urls: dict[uuid.UUID, str | None], opts: ItemOptions | None = None) -> ItemOut:
    return ItemOut(
        tax_pct=i.tax_pct,
        tags=i.tags,
        **(opts.fields(i.id) if opts else {}),
        id=i.id,
        category_id=i.category_id,
        subcategory_id=i.subcategory_id,
        name=i.name,
        description=i.description,
        image_url=urls.get(i.image_media_id) if i.image_media_id else None,
        base_price=i.base_price,
        food_class=i.food_class,  # type: ignore[arg-type]
        spice_level=i.spice_level,
        allergens=i.allergens,
        prep_minutes=i.prep_minutes,
        is_bestseller=i.is_bestseller,
        is_todays_special=i.is_todays_special,
        is_available=i.is_available,
        is_archived=i.archived_at is not None,
        sort_order=i.sort_order,
    )


async def _changed(ctx: TenantContext) -> None:
    await invalidate_storefront(ctx.tenant_slug)


# ---------- admin read ----------


async def admin_menu(session: AsyncSession, ctx: TenantContext) -> AdminMenu:
    tenant = await session.get(Tenant, ctx.tenant_id)
    meals = (await session.execute(select(MealType).order_by(MealType.sort_order, MealType.name))).scalars().all()
    cats = (
        (await session.execute(select(MenuCategory).order_by(MenuCategory.sort_order, MenuCategory.name)))
        .scalars()
        .all()
    )
    subs = (
        (await session.execute(select(MenuSubcategory).order_by(MenuSubcategory.sort_order, MenuSubcategory.name)))
        .scalars()
        .all()
    )
    items = (await session.execute(select(MenuItem).order_by(MenuItem.sort_order, MenuItem.name))).scalars().all()
    links = await _meal_links(session)
    urls = await _media_urls(session, {i.image_media_id for i in items if i.image_media_id})
    opts = await load_options(session)

    subs_by_cat: dict[uuid.UUID, list[SubcategoryOut]] = defaultdict(list)
    for s in subs:
        subs_by_cat[s.category_id].append(SubcategoryOut(id=s.id, name=s.name, sort_order=s.sort_order))
    count: dict[uuid.UUID, int] = defaultdict(int)
    for i in items:
        if i.archived_at is None:
            count[i.category_id] += 1

    return AdminMenu(
        meal_types=[MealTypeOut(id=m.id, name=m.name, is_active=m.is_active, sort_order=m.sort_order) for m in meals],
        categories=[
            CategoryOut(
                id=c.id,
                name=c.name,
                description=c.description,
                meal_type_ids=links.get(c.id, []),
                is_active=c.is_active,
                is_alcoholic=c.is_alcoholic,
                sort_order=c.sort_order,
                subcategories=subs_by_cat.get(c.id, []),
                item_count=count.get(c.id, 0),
            )
            for c in cats
        ],
        items=[_item_out(i, urls, opts) for i in items],
        alcohol_licensed=bool(tenant and tenant.alcohol_licensed),
    )


# ---------- meal types ----------


async def _unique_name(
    session: AsyncSession, model: type, name: str, exclude: uuid.UUID | None = None, **scope
) -> None:  # type: ignore[no-untyped-def]
    stmt = select(func.count()).select_from(model).where(func.lower(model.name) == name.strip().lower())
    for k, v in scope.items():
        stmt = stmt.where(getattr(model, k) == v)
    if exclude:
        stmt = stmt.where(model.id != exclude)
    if (await session.execute(stmt)).scalar_one():
        raise ConflictError(f'"{name.strip()}" already exists.', code="DUPLICATE_NAME")


async def create_meal_type(session: AsyncSession, ctx: TenantContext, data: MealTypeIn) -> AdminMenu:
    await _unique_name(session, MealType, data.name)
    top = (await session.execute(select(func.coalesce(func.max(MealType.sort_order), -1)))).scalar_one()
    session.add(MealType(tenant_id=ctx.tenant_id, name=data.name.strip(), is_active=data.is_active, sort_order=top + 1))
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


async def update_meal_type(
    session: AsyncSession, ctx: TenantContext, meal_id: uuid.UUID, data: MealTypePatch
) -> AdminMenu:
    meal = await _get(session, MealType, meal_id, "Meal type")
    if data.name is not None:
        await _unique_name(session, MealType, data.name, exclude=meal.id)
        meal.name = data.name.strip()
    if data.is_active is not None:
        meal.is_active = data.is_active
    if data.sort_order is not None:
        meal.sort_order = data.sort_order
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


# ---------- categories ----------


async def _check_meal_ids(session: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(ids))
    found = set((await session.execute(select(MealType.id).where(MealType.id.in_(unique)))).scalars())
    if found != set(unique):
        raise AppError("Unknown meal type.", code="UNKNOWN_MEAL_TYPE", status_code=422)
    return unique


async def _set_meal_links(
    session: AsyncSession, ctx: TenantContext, category_id: uuid.UUID, ids: list[uuid.UUID]
) -> None:
    await session.execute(delete(CategoryMealType).where(CategoryMealType.category_id == category_id))
    for mid in ids:
        session.add(CategoryMealType(tenant_id=ctx.tenant_id, category_id=category_id, meal_type_id=mid))


async def _guard_alcohol(session: AsyncSession, ctx: TenantContext, category: MenuCategory) -> None:
    if category.is_alcoholic and category.is_active:
        tenant = await session.get(Tenant, ctx.tenant_id)
        if not (tenant and tenant.alcohol_licensed):
            raise ConflictError(
                "Alcoholic categories stay disabled until WaitLess approves your liquor licence.",
                code="ALCOHOL_NOT_LICENSED",
            )


async def create_category(session: AsyncSession, ctx: TenantContext, data: CategoryIn) -> AdminMenu:
    await _unique_name(session, MenuCategory, data.name)
    meal_ids = await _check_meal_ids(session, data.meal_type_ids)
    top = (await session.execute(select(func.coalesce(func.max(MenuCategory.sort_order), -1)))).scalar_one()
    cat = MenuCategory(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=data.name.strip(),
        description=data.description.strip(),
        is_active=data.is_active,
        sort_order=top + 1,
    )
    session.add(cat)
    await session.flush()
    await _set_meal_links(session, ctx, cat.id, meal_ids)
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


async def update_category(
    session: AsyncSession, ctx: TenantContext, category_id: uuid.UUID, data: CategoryPatch
) -> AdminMenu:
    cat = await _get(session, MenuCategory, category_id, "Category")
    if data.name is not None:
        await _unique_name(session, MenuCategory, data.name, exclude=cat.id)
        cat.name = data.name.strip()
    if data.description is not None:
        cat.description = data.description.strip()
    if data.is_active is not None:
        cat.is_active = data.is_active
        await _guard_alcohol(session, ctx, cat)
    if data.sort_order is not None:
        cat.sort_order = data.sort_order
    if data.meal_type_ids is not None:
        await _set_meal_links(session, ctx, cat.id, await _check_meal_ids(session, data.meal_type_ids))
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


async def delete_category(session: AsyncSession, ctx: TenantContext, category_id: uuid.UUID) -> AdminMenu:
    cat = await _get(session, MenuCategory, category_id, "Category")
    used = (
        await session.execute(select(func.count()).select_from(MenuItem).where(MenuItem.category_id == cat.id))
    ).scalar_one()
    if used:
        raise ConflictError(
            "This category has dishes (including archived ones). Move them or switch the category off instead.",
            code="CATEGORY_NOT_EMPTY",
        )
    await session.delete(cat)
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


# ---------- subcategories ----------


async def create_subcategory(
    session: AsyncSession, ctx: TenantContext, category_id: uuid.UUID, data: SubcategoryIn
) -> AdminMenu:
    cat = await _get(session, MenuCategory, category_id, "Category")
    await _unique_name(session, MenuSubcategory, data.name, category_id=cat.id)
    top = (
        await session.execute(
            select(func.coalesce(func.max(MenuSubcategory.sort_order), -1)).where(MenuSubcategory.category_id == cat.id)
        )
    ).scalar_one()
    session.add(
        MenuSubcategory(tenant_id=ctx.tenant_id, category_id=cat.id, name=data.name.strip(), sort_order=top + 1)
    )
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


async def update_subcategory(
    session: AsyncSession, ctx: TenantContext, sub_id: uuid.UUID, data: SubcategoryPatch
) -> AdminMenu:
    sub = await _get(session, MenuSubcategory, sub_id, "Subcategory")
    if data.name is not None:
        await _unique_name(session, MenuSubcategory, data.name, exclude=sub.id, category_id=sub.category_id)
        sub.name = data.name.strip()
    if data.sort_order is not None:
        sub.sort_order = data.sort_order
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


async def delete_subcategory(session: AsyncSession, ctx: TenantContext, sub_id: uuid.UUID) -> AdminMenu:
    sub = await _get(session, MenuSubcategory, sub_id, "Subcategory")
    await session.delete(sub)  # items keep their category; their subcategory becomes empty (FK SET NULL)
    await session.commit()
    await _changed(ctx)
    return await admin_menu(session, ctx)


# ---------- items ----------


async def _check_placement(session: AsyncSession, category_id: uuid.UUID, subcategory_id: uuid.UUID | None) -> None:
    await _get(session, MenuCategory, category_id, "Category")
    if subcategory_id is not None:
        sub = await _get(session, MenuSubcategory, subcategory_id, "Subcategory")
        if sub.category_id != category_id:
            raise AppError(
                "That subcategory belongs to a different category.", code="SUBCATEGORY_MISMATCH", status_code=422
            )


async def _one_item(session: AsyncSession, item: MenuItem) -> ItemOut:
    urls = await _media_urls(session, {item.image_media_id} if item.image_media_id else set())
    return _item_out(item, urls, await load_options(session, [item.id]))


async def set_options(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, data: ItemOptionsIn) -> ItemOut:
    """Replace variants, add-on groups and time windows. Past orders are unaffected (they keep snapshots)."""
    item = await _get(session, MenuItem, item_id, "Dish")
    await session.execute(delete(MenuItemVariant).where(MenuItemVariant.item_id == item.id))
    await session.execute(delete(MenuAddonGroup).where(MenuAddonGroup.item_id == item.id))  # cascades add-ons
    await session.execute(delete(MenuItemAvailability).where(MenuItemAvailability.item_id == item.id))
    tid = ctx.tenant_id
    for n, v in enumerate(data.variants):
        session.add(
            MenuItemVariant(
                tenant_id=tid,
                item_id=item.id,
                name=v.name.strip(),
                price=v.price.quantize(Decimal("0.01")),
                sort_order=n,
            )
        )
    for n, g in enumerate(data.addon_groups):
        group = MenuAddonGroup(
            id=uuid.uuid4(),
            tenant_id=tid,
            item_id=item.id,
            name=g.name.strip(),
            min_select=g.min_select,
            max_select=min(g.max_select, len(g.addons)),
            sort_order=n,
        )
        session.add(group)
        await session.flush()
        for m, a in enumerate(g.addons):
            session.add(
                MenuAddon(
                    tenant_id=tid,
                    group_id=group.id,
                    name=a.name.strip(),
                    price=a.price.quantize(Decimal("0.01")),
                    sort_order=m,
                )
            )
    seen = set()
    for w in data.availability:
        key = (w.weekday, w.from_time, w.to_time)
        if key not in seen:
            seen.add(key)
            session.add(MenuItemAvailability(tenant_id=tid, item_id=item.id, **w.model_dump()))
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def set_branch_override(
    session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, branch_id: uuid.UUID, data: BranchOverrideIn
) -> ItemOut:
    from app.models import Branch

    item = await _get(session, MenuItem, item_id, "Dish")
    await _get(session, Branch, branch_id, "Branch")
    row = await session.get(MenuItemBranchOverride, (item.id, branch_id))
    if data.is_available and data.price_override is None:
        if row is not None:
            await session.delete(row)  # back to the dish defaults
    else:
        if row is None:
            row = MenuItemBranchOverride(tenant_id=ctx.tenant_id, item_id=item.id, branch_id=branch_id)
            session.add(row)
        price = data.price_override.quantize(Decimal("0.01")) if data.price_override is not None else None
        row.is_available, row.price_override = data.is_available, price
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def create_item(session: AsyncSession, ctx: TenantContext, data: ItemIn) -> ItemOut:
    await _check_placement(session, data.category_id, data.subcategory_id)
    top = (
        await session.execute(
            select(func.coalesce(func.max(MenuItem.sort_order), -1)).where(MenuItem.category_id == data.category_id)
        )
    ).scalar_one()
    item = MenuItem(tenant_id=ctx.tenant_id, sort_order=top + 1, **data.model_dump())
    item.name = item.name.strip()
    session.add(item)
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def update_item(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, data: ItemPatch) -> ItemOut:
    item = await _get(session, MenuItem, item_id, "Dish")
    changes = data.model_dump(exclude_unset=True)
    if "category_id" in changes or "subcategory_id" in changes:
        category_id = changes.get("category_id") or item.category_id
        sub_id = (
            changes["subcategory_id"]
            if "subcategory_id" in changes
            else (item.subcategory_id if category_id == item.category_id else None)
        )
        await _check_placement(session, category_id, sub_id)
        changes["category_id"], changes["subcategory_id"] = category_id, sub_id
    for key, value in changes.items():
        if key == "name" and value is not None:
            value = value.strip()
        if value is None and key not in ("subcategory_id",):
            continue
        setattr(item, key, value)
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def set_stock(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, available: bool) -> ItemOut:
    item = await _get(session, MenuItem, item_id, "Dish")
    item.is_available = available
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def archive_item(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, archived: bool) -> ItemOut:
    """Dishes are archived, never hard-deleted: past orders (Phase 7) keep pointing at them."""
    item = await _get(session, MenuItem, item_id, "Dish")
    item.archived_at = datetime.now(UTC) if archived else None
    await session.commit()
    await _changed(ctx)
    return await _one_item(session, item)


async def set_item_image(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID, upload: UploadFile) -> ItemOut:
    item = await _get(session, MenuItem, item_id, "Dish")
    media = await store_image(
        session, tenant_id=ctx.tenant_id, kind="menu_item", upload=upload, actor_user_id=ctx.user_id
    )
    old = await session.get(MediaFile, item.image_media_id) if item.image_media_id else None
    item.image_media_id = media.id
    await session.flush()
    old_key = old.storage_key if old else None
    if old:
        await session.delete(old)
    await session.commit()
    if old_key:
        await delete_files([old_key])
    await _changed(ctx)
    return await _one_item(session, item)


async def remove_item_image(session: AsyncSession, ctx: TenantContext, item_id: uuid.UUID) -> ItemOut:
    item = await _get(session, MenuItem, item_id, "Dish")
    old = await session.get(MediaFile, item.image_media_id) if item.image_media_id else None
    if old:
        key = old.storage_key
        item.image_media_id = None
        await session.flush()
        await session.delete(old)
        await session.commit()
        await delete_files([key])
        await _changed(ctx)
    return await _one_item(session, item)


async def menu_ready(session: AsyncSession) -> bool:
    """Publish checklist: at least one live dish in an active category."""
    n = (
        await session.execute(
            select(func.count())
            .select_from(MenuItem)
            .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
            .where(MenuItem.archived_at.is_(None), MenuCategory.is_active)
        )
    ).scalar_one()
    return n > 0


# ---------- public ----------


async def build_public_menu(session: AsyncSession, tenant: Tenant) -> PublicMenu:
    """Session must already be scoped to the restaurant (use_tenant)."""
    from app.api.deps import feature_enabled  # local: avoid import cycle

    currency = str((tenant.settings or {}).get("currency", "INR"))
    meals = (
        (await session.execute(select(MealType).where(MealType.is_active).order_by(MealType.sort_order, MealType.name)))
        .scalars()
        .all()
    )
    cats = (
        (
            await session.execute(
                select(MenuCategory).where(MenuCategory.is_active).order_by(MenuCategory.sort_order, MenuCategory.name)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await session.execute(
                select(MenuItem).where(MenuItem.archived_at.is_(None)).order_by(MenuItem.sort_order, MenuItem.name)
            )
        )
        .scalars()
        .all()
    )
    sub_names = dict((await session.execute(select(MenuSubcategory.id, MenuSubcategory.name))).tuples().all())
    links = await _meal_links(session)
    urls = await _media_urls(session, {i.image_media_id for i in items if i.image_media_id})
    opts = await load_options(session, [i.id for i in items])
    active_meals = {m.id for m in meals}

    by_cat: dict[uuid.UUID, list[PublicItem]] = defaultdict(list)
    for i in items:
        by_cat[i.category_id].append(
            PublicItem(
                id=i.id,
                name=i.name,
                description=i.description,
                image_url=urls.get(i.image_media_id) if i.image_media_id else None,
                price=i.base_price,
                food_class=i.food_class,  # type: ignore[arg-type]
                spice_level=i.spice_level,
                allergens=i.allergens,
                prep_minutes=i.prep_minutes,
                is_bestseller=i.is_bestseller,
                is_todays_special=i.is_todays_special,
                is_available=i.is_available,
                subcategory=sub_names.get(i.subcategory_id) if i.subcategory_id else None,
                tax_pct=i.tax_pct,
                tags=i.tags,
                **opts.fields(i.id),
            )
        )
    categories = []
    for c in cats:
        meal_ids = [m for m in links.get(c.id, []) if m in active_meals]
        if by_cat.get(c.id) and meal_ids:
            categories.append(
                PublicCategory(
                    id=c.id, name=c.name, description=c.description, meal_type_ids=meal_ids, items=by_cat[c.id]
                )
            )
    used_meals = {m for c in categories for m in c.meal_type_ids}
    return PublicMenu(
        currency=currency,
        meal_types=[PublicMealType(id=m.id, name=m.name) for m in meals if m.id in used_meals],
        categories=categories,
        ordering_enabled=await feature_enabled(session, tenant.id, "ordering"),
    )

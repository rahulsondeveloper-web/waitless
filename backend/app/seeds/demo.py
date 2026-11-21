"""Demo data for development and end-to-end tests: two complete, approved, published restaurants.

    python -m app.cli seed-demo

Idempotent (skips restaurants whose slug exists). Refuses to run in production.
Images are drawn procedurally with Pillow, so no third-party photos are involved.
"""

import io
import random
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time
from decimal import Decimal

from PIL import Image, ImageDraw
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import use_system
from app.core.storage import get_storage
from app.models import Branch, Membership, Role, Tenant, User, UserBranch
from app.models.booking import QueueEntry, Reservation, ReservationPolicy
from app.models.inventory import (
    InventoryCategory,
    InventoryItem,
    PurchaseOrder,
    RecipeIngredient,
    StockTransfer,
    Supplier,
)
from app.models.menu import CategoryMealType, MealType, MenuCategory, MenuItem, MenuSubcategory
from app.models.orders import Order
from app.models.profile import (
    BusinessHours,
    GalleryImage,
    MediaFile,
    RestaurantBranding,
    RestaurantProfile,
    SocialLink,
)
from app.models.sla import DiscountPolicy
from app.models.tables import RestaurantTable, TableAssignment, TableSection, TableSession
from app.schemas.tenancy import RestaurantRegistration
from app.services.media import process_image
from app.services.registration import register_restaurant
from app.services.storefront_cache import invalidate_storefront

DEMO_PASSWORD = "Demo-pass-123"  # development only


@dataclass
class Dish:
    name: str
    price: str
    description: str = ""
    food_class: str = "veg"
    spice: int = 0
    bestseller: bool = False
    special: bool = False
    sub: str | None = None


@dataclass
class DemoRestaurant:
    slug: str
    name: str
    owner: str
    email: str
    mobile: str
    city: str
    state: str
    address: str
    lat: str
    lng: str
    cuisines: list[str]
    restaurant_type: str
    short: str
    about: str
    tokens: dict[str, str]
    button_style: str
    palette: list[tuple[int, int, int]]
    menu: dict[str, list[Dish]] = field(default_factory=dict)
    new_categories: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)  # name -> (meals, subs)
    waiters: list["DemoWaiter"] = field(default_factory=list)


@dataclass
class DemoWaiter:
    """A waiter who signs in with email + DEMO_PASSWORD and looks after the listed tables."""

    name: str
    email: str
    mobile: str
    tables: list[str]


DEMOS = [
    DemoRestaurant(
        slug="urban-bites",
        name="Urban Bites",
        owner="Urban Bites Owner",
        email="owner@urbanbites.example.com",
        mobile="9000000101",
        city="Pune",
        state="Maharashtra",
        address="12 Olive Street, Koregaon Park",
        lat="18.536200",
        lng="73.893900",
        cuisines=["Italian", "Continental", "Cafe & Bakery"],
        restaurant_type="Casual Dining",
        short="Wood-fired pizzas, soup bowls and garden greens — served in 15 minutes.",
        about="Urban Bites started as a tiny wood-fire oven on a busy street. We still knead every dough by hand.",
        tokens={"primary": "#0a7c86", "accent": "#f2b134", "background": "#fbf8f1"},
        button_style="rounded",
        palette=[(10, 124, 134), (242, 177, 52), (246, 239, 222), (36, 61, 66)],
        new_categories={"Wood-fired Pizzas": (["Lunch", "Dinner"], ["Napoletana Style", "Sourdough Style"])},
        waiters=[
            DemoWaiter("Rohan Waiter", "rohan@urbanbites.example.com", "9000000111", ["T1", "T2", "T3", "T4"]),
            DemoWaiter("Priya Waiter", "priya@urbanbites.example.com", "9000000112", ["T5", "P1", "P2", "P3"]),
        ],
        menu={
            "Starters": [
                Dish(
                    "Italian Minestrone", "290", "Broth with diced pasta and farm vegetables, fresh basil.", sub="Soups"
                ),
                Dish(
                    "Roasted Broccoli & Almond Soup",
                    "290",
                    "Purée of roasted broccoli, almonds, pesto oil.",
                    bestseller=True,
                    sub="Soups",
                ),
                Dish(
                    "The Greek Garden",
                    "330",
                    "Mesclun, olives, cucumber, citrus vinaigrette, feta crumble.",
                    sub="Salads",
                ),
            ],
            "Wood-fired Pizzas": [
                Dish(
                    "Pizza Margherita",
                    "580",
                    "Sourdough, pomodoro, buffalo mozzarella, basil.",
                    bestseller=True,
                    sub="Sourdough Style",
                ),
                Dish(
                    "Quattro Formaggi", "760", "Bocconcini, ricotta, blue cheese, aged parmesan.", sub="Sourdough Style"
                ),
                Dish(
                    "Pizza Mediterranea", "550", "Sun-dried tomato, capers, artichoke, olives.", sub="Napoletana Style"
                ),
            ],
            "Main Course": [
                Dish("Fusilli Alfredo", "490", "Mushrooms, leeks, cream cheese sauce.", sub="Continental Main Course"),
                Dish(
                    "Penne Arrabbiata",
                    "475",
                    "Bell peppers, zucchini, spiced paprika sauce.",
                    spice=2,
                    sub="Continental Main Course",
                ),
            ],
            "Desserts": [
                Dish("Tiramisu", "275", "Coffee scented, cocoa dusted.", sub="Cakes"),
                Dish(
                    "Sizzling Brownie", "320", "Nutella brownie with vanilla ice cream.", special=True, sub="Brownies"
                ),
            ],
            "Mocktails": [
                Dish("Virgin Mojito", "240", "Lime, sugar and fresh mint.", sub="Virgin Mojito"),
                Dish("Mint Berry Smash", "260", "Mint, blueberry, strawberry, fizz.", sub="Fruit Mocktails"),
            ],
        },
    ),
    DemoRestaurant(
        slug="remelle",
        name="Restaurant Remelle",
        owner="Remelle Owner",
        email="owner@remelle.example.com",
        mobile="9000000102",
        city="Mumbai",
        state="Maharashtra",
        address="8 Marine Drive, Churchgate",
        lat="18.935400",
        lng="72.824200",
        cuisines=["Continental", "Seafood"],
        restaurant_type="Fine Dining",
        short="Good food brings people together.",
        about="Seasonal plates, slow evenings and a kitchen that respects the clock.",
        tokens={},  # default Remelle theme
        button_style="pill",
        palette=[(185, 85, 58), (78, 122, 74), (247, 239, 228), (43, 37, 34)],
        menu={
            "Starters": [
                Dish("Tomato Basil Soup", "290", "Slow-roasted tomatoes, basil, a swirl of cream.", sub="Soups"),
            ],
            "Main Course": [
                Dish(
                    "Grilled Salmon",
                    "520",
                    "Lemon butter sauce, seasonal vegetables.",
                    "non_veg",
                    bestseller=True,
                    sub="Continental Main Course",
                ),
                Dish(
                    "Herb Chicken",
                    "480",
                    "Grilled with herb sauce and mashed potato.",
                    "non_veg",
                    sub="Non-Veg Main Course",
                ),
                Dish(
                    "Truffle Mushroom Pasta",
                    "420",
                    "Creamy pasta with wild mushrooms and truffle oil.",
                    special=True,
                    sub="Continental Main Course",
                ),
                Dish(
                    "Seafood Risotto",
                    "560",
                    "Classic risotto with fresh seafood and parmesan.",
                    "non_veg",
                    sub="Rice & Biryani",
                ),
            ],
            "Desserts": [Dish("Chocolate Mousse Cake", "310", "Dark chocolate, berries.", sub="Cakes")],
            "Non-Alcoholic": [Dish("Fresh Lime Soda", "150", "Sweet or salted.", sub="Fresh Juices")],
        },
    ),
]


# ---------- procedural images ----------


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _cover(palette: list[tuple[int, int, int]], seed: int, size: tuple[int, int] = (1600, 700)) -> bytes:
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, palette[3])
    d = ImageDraw.Draw(img)
    for y in range(h):  # vertical gradient
        t = y / h
        c = tuple(int(palette[3][i] * (1 - t) + palette[0][i] * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    for _ in range(14):  # "plates"
        r = rnd.randint(60, 200)
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        d.ellipse((x - r, y - r, x + r, y + r), fill=palette[2], outline=palette[1], width=8)
        d.ellipse((x - r // 2, y - r // 2, x + r // 2, y + r // 2), fill=palette[rnd.choice([0, 1])])
    return _png(img)


def _logo(palette: list[tuple[int, int, int]]) -> bytes:
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((20, 20, 380, 380), fill=palette[0])
    d.ellipse((90, 90, 310, 310), fill=palette[2])
    d.pieslice((90, 90, 310, 310), 200, 340, fill=palette[1])
    return _png(img)


async def _media(session: AsyncSession, tenant_id: uuid.UUID, kind: str, data: bytes) -> MediaFile:
    processed = process_image(data, kind)
    stored = await get_storage().save(
        f"tenants/{tenant_id}/{kind}", processed.data, extension="webp", content_type="image/webp"
    )
    m = MediaFile(
        tenant_id=tenant_id,
        kind=kind,
        storage_key=stored.key,
        mime="image/webp",
        width=processed.width,
        height=processed.height,
        bytes=stored.size,
    )
    session.add(m)
    await session.flush()
    return m


async def _ensure_tables(session: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> int:
    """Two sections and eight tables per demo restaurant (added once)."""
    if (await session.execute(select(RestaurantTable.id).where(RestaurantTable.tenant_id == tenant_id))).first():
        return 0
    layout = {
        "Indoor": [("T1", 2), ("T2", 2), ("T3", 4), ("T4", 4), ("T5", 6)],
        "Terrace": [("P1", 2), ("P2", 4), ("P3", 8)],
    }
    n = 0
    for order, (section_name, tables) in enumerate(layout.items()):
        section = TableSection(tenant_id=tenant_id, branch_id=branch_id, name=section_name, sort_order=order)
        session.add(section)
        await session.flush()
        for label, capacity in tables:
            session.add(
                RestaurantTable(
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    section_id=section.id,
                    label=label,
                    capacity=capacity,
                    sort_order=n,
                )
            )
            n += 1
    return n


async def _ensure_waiters(
    session: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, demo: "DemoRestaurant"
) -> int:
    """Demo waiters (added once) and their tables — a table that already has a waiter keeps it."""
    from app.core.security import hash_password

    if not demo.waiters:
        return 0
    role_id = (
        await session.execute(select(Role.id).where(Role.key == "waiter", Role.tenant_id.is_(None)))
    ).scalar_one()
    tables = {
        t.label: t
        for t in (
            await session.execute(select(RestaurantTable).where(RestaurantTable.branch_id == branch_id))
        ).scalars()
    }
    added = 0
    for w in demo.waiters:
        user = (await session.execute(select(User).where(User.email == w.email))).scalar_one_or_none()
        if user is None:
            user = User(
                email=w.email, phone="+91" + w.mobile, full_name=w.name, password_hash=hash_password(DEMO_PASSWORD)
            )
            session.add(user)
            await session.flush()
        member = (
            await session.execute(
                select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
            )
        ).scalar_one_or_none()
        if member is None:
            member = Membership(tenant_id=tenant_id, user_id=user.id, role_id=role_id, all_branches=False)
            session.add(member)
            await session.flush()
            session.add(UserBranch(tenant_id=tenant_id, membership_id=member.id, branch_id=branch_id))
            added += 1
        for label in w.tables:
            table = tables.get(label)
            if table is not None and table.waiter_user_id is None:
                table.waiter_user_id = user.id
    await session.flush()
    return added


# ---------- seeding ----------


# Phase 9: a small pantry so Inventory, recipes and deductions can be tried right away.
_PANTRY = [  # name, unit, opening, reorder level, price, expiry in days
    ("Flour", "kg", "25", "8", "45", None),
    ("Mozzarella", "kg", "6", "3", "420", 10),
    ("Tomato", "kg", "12", "5", "40", 6),
    ("Olive Oil", "l", "5", "2", "650", None),
    ("Milk", "l", "18", "6", "56", 3),
    ("Coffee Beans", "kg", "3", "1", "900", None),
    ("Butter", "kg", "2", "3", "520", 20),  # already below its reorder level → shows in Alerts
    ("Mixed Vegetables", "kg", "10", "4", "60", 4),
]
_RECIPES = [  # dish name contains → (ingredient, quantity, unit)
    (
        ("pizza", "margherita", "focaccia"),
        [("Flour", "200", "g"), ("Mozzarella", "120", "g"), ("Tomato", "80", "g"), ("Olive Oil", "10", "ml")],
    ),
    (("coffee", "latte", "cappuccino", "espresso", "mocha"), [("Coffee Beans", "18", "g"), ("Milk", "150", "ml")]),
    (("soup", "salad", "bowl", "pasta"), [("Mixed Vegetables", "150", "g"), ("Olive Oil", "10", "ml")]),
    (
        ("croissant", "toast", "bread", "brioche", "pancake"),
        [("Flour", "80", "g"), ("Butter", "25", "g"), ("Milk", "50", "ml")],
    ),
]


async def _ensure_inventory(session: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> int:
    """Pantry items with opening stock, one supplier and recipes for matching dishes (only if empty)."""
    from datetime import timedelta

    from app.models.tenancy import Membership
    from app.services.inventory import apply

    if (await session.execute(select(InventoryItem.id).where(InventoryItem.tenant_id == tenant_id).limit(1))).first():
        return 0
    owner = (
        await session.execute(select(Membership.user_id).where(Membership.tenant_id == tenant_id).limit(1))
    ).scalar_one()
    supplier = Supplier(
        tenant_id=tenant_id, name="City Wholesale Traders", contact_name="Mahesh", phone="+919000000999"
    )
    session.add(supplier)
    await session.flush()
    items: dict[str, InventoryItem] = {}
    today = datetime.now(UTC).date()
    for name, unit, qty, level, price, days in _PANTRY:
        item = InventoryItem(
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            name=name,
            unit=unit,
            reorder_level=Decimal(level),
            min_stock=Decimal(level) / 2,
            purchase_price=Decimal(price),
            tracks_expiry=days is not None,
            storage_location="Cold room" if days else "Dry store",
        )
        session.add(item)
        await session.flush()
        items[name] = item
        await apply(
            session,
            tenant_id=tenant_id,
            branch_id=branch_id,
            item=item,
            delta=Decimal(qty),
            type="opening",
            reason="Opening stock (demo)",
            actor_user_id=owner,
            unit_cost=Decimal(price),
            expiry_date=today + timedelta(days=days) if days else None,
        )
    dishes = (await session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant_id))).scalars()
    for dish in dishes:
        lowered = dish.name.lower()
        for keys, lines in _RECIPES:
            if any(k in lowered for k in keys):
                for ing, q, u in lines:
                    session.add(
                        RecipeIngredient(
                            tenant_id=tenant_id,
                            menu_item_id=dish.id,
                            inventory_item_id=items[ing].id,
                            quantity=Decimal(q),
                            unit=u,
                        )
                    )
                break
    session.info.pop("inventory_alerts", None)  # no notifications while seeding
    return len(items)


async def _seed_one(session: AsyncSession, demo: DemoRestaurant, idx: int) -> str:
    await use_system(session)
    existing = (await session.execute(select(Tenant.id).where(Tenant.slug == demo.slug))).scalar_one_or_none()
    if existing:
        branch_id = (
            await session.execute(select(Branch.id).where(Branch.tenant_id == existing, Branch.is_primary))
        ).scalar_one()
        added = await _ensure_tables(session, existing, branch_id)
        stocked = await _ensure_inventory(session, existing, branch_id)
        waiters = await _ensure_waiters(session, existing, branch_id, demo)
        await session.commit()
        extra = [f"added {added} tables"] if added else []
        extra += [f"added {stocked} inventory items"] if stocked else []
        extra += [f"added {waiters} waiters"] if waiters else []
        return f"{demo.slug}: already exists" + (f" ({', '.join(extra)})" if extra else " (skipped)")
    tenant, _ = await register_restaurant(
        session,
        RestaurantRegistration(
            restaurant_name=demo.name,
            owner_name=demo.owner,
            email=demo.email,
            mobile=demo.mobile,
            password=DEMO_PASSWORD,
            address=demo.address,
            city=demo.city,
            state=demo.state,
            country="India",
            cuisines=demo.cuisines,
            restaurant_type=demo.restaurant_type,
            preferred_slug=demo.slug,
        ),
    )
    await use_system(session)
    tid = tenant.id
    tenant = (await session.execute(select(Tenant).where(Tenant.id == tid))).scalar_one()

    profile = await session.get(RestaurantProfile, tid)
    branding = await session.get(RestaurantBranding, tid)
    assert profile and branding
    profile.short_description = demo.short
    profile.about_us = demo.about
    profile.description = demo.short
    profile.contact_phone = "+91" + demo.mobile
    profile.contact_email = demo.email.replace("owner@", "hello@")
    profile.cover_media_id = (await _media(session, tid, "cover", _cover(demo.palette, idx))).id
    branding.logo_media_id = (await _media(session, tid, "logo", _logo(demo.palette))).id
    branding.tokens = demo.tokens
    branding.button_style = demo.button_style
    for pos in range(1, 4):
        media = await _media(session, tid, "gallery", _cover(demo.palette, idx * 10 + pos, (1200, 900)))
        session.add(GalleryImage(tenant_id=tid, media_id=media.id, position=pos, caption=f"{demo.name} — view {pos}"))
    session.add(
        SocialLink(tenant_id=tid, platform="instagram", url=f"https://instagram.com/{demo.slug.replace('-', '')}")
    )

    branch = (await session.execute(select(Branch).where(Branch.tenant_id == tid, Branch.is_primary))).scalar_one()
    branch.name = demo.name
    branch.lat, branch.lng = Decimal(demo.lat), Decimal(demo.lng)
    branch.postal_code = "411001" if demo.city == "Pune" else "400020"
    for wd in range(7):
        session.add(
            BusinessHours(tenant_id=tid, branch_id=branch.id, weekday=wd, opens_at=time(0, 0), closes_at=time(23, 59))
        )

    meals = {m.name: m for m in (await session.execute(select(MealType).where(MealType.tenant_id == tid))).scalars()}
    for cat_name, (meal_names, subs) in demo.new_categories.items():
        cat = MenuCategory(id=uuid.uuid4(), tenant_id=tid, name=cat_name, sort_order=-1)
        session.add(cat)
        await session.flush()
        for m in meal_names:
            session.add(CategoryMealType(tenant_id=tid, category_id=cat.id, meal_type_id=meals[m].id))
        for j, s in enumerate(subs):
            session.add(MenuSubcategory(tenant_id=tid, category_id=cat.id, name=s, sort_order=j))
    await session.flush()
    cats = {
        c.name: c for c in (await session.execute(select(MenuCategory).where(MenuCategory.tenant_id == tid))).scalars()
    }
    subs_by = {
        (s.category_id, s.name): s
        for s in (await session.execute(select(MenuSubcategory).where(MenuSubcategory.tenant_id == tid))).scalars()
    }
    for cat_name, dishes in demo.menu.items():
        cat = cats[cat_name]
        for order, d in enumerate(dishes):
            sub = subs_by.get((cat.id, d.sub)) if d.sub else None
            session.add(
                MenuItem(
                    tenant_id=tid,
                    category_id=cat.id,
                    subcategory_id=sub.id if sub else None,
                    name=d.name,
                    description=d.description,
                    base_price=Decimal(d.price),
                    food_class=d.food_class,
                    spice_level=d.spice,
                    is_bestseller=d.bestseller,
                    is_todays_special=d.special,
                    sort_order=order,
                )
            )

    await _ensure_tables(session, tid, branch.id)
    await session.flush()
    await _ensure_inventory(session, tid, branch.id)
    await _ensure_waiters(session, tid, branch.id, demo)

    tenant.status = "active"
    tenant.approved_at = datetime.now(UTC)
    tenant.is_published = True
    await session.commit()
    await invalidate_storefront(demo.slug)
    return f"{demo.slug}: created - owner {demo.email} / {DEMO_PASSWORD}"


def _e2e_variant(demo: DemoRestaurant, idx: int) -> DemoRestaurant:
    """Private copy for automated tests, so manual experiments on the demos never break them."""
    return replace(
        demo,
        slug=f"e2e-{demo.slug}",
        name=f"{demo.name} E2E",
        owner=f"{demo.owner} (tests)",
        email=f"e2e.{demo.email}",
        mobile=f"90000002{idx:02d}",
        waiters=[],  # tests add their own staff
    )


async def _reset_e2e(session: AsyncSession, demo: DemoRestaurant) -> None:
    """Undo whatever earlier test runs changed: every dish live and available, original theme, published."""
    await use_system(session)
    tenant = (await session.execute(select(Tenant).where(Tenant.slug == demo.slug))).scalar_one()
    dish_names = {d.name for dishes in demo.menu.values() for d in dishes}
    await session.execute(  # dishes created by tests go away; the demo menu stays
        delete(MenuItem).where(MenuItem.tenant_id == tenant.id, MenuItem.name.not_in(dish_names))
    )
    for item in (await session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id))).scalars():
        item.archived_at = None
        item.is_available = True
    names = set(demo.menu)
    for cat in (await session.execute(select(MenuCategory).where(MenuCategory.tenant_id == tenant.id))).scalars():
        if cat.name in names:
            cat.is_active = True
    branding = await session.get(RestaurantBranding, tenant.id)
    if branding is not None:
        branding.tokens, branding.button_style, branding.mode = demo.tokens, demo.button_style, "light"
    tenant.status, tenant.is_published = "active", True
    # Phase 6: empty queue, no bookings, default policy, every table free.
    tid = tenant.id
    await session.execute(delete(Order).where(Order.tenant_id == tid))
    await session.execute(delete(QueueEntry).where(QueueEntry.tenant_id == tid))
    await session.execute(delete(Reservation).where(Reservation.tenant_id == tid))
    await session.execute(delete(ReservationPolicy).where(ReservationPolicy.tenant_id == tid))
    await session.execute(delete(DiscountPolicy).where(DiscountPolicy.tenant_id == tid))  # Phase 8: defaults
    now = datetime.now(UTC)
    await session.execute(
        update(TableAssignment)
        .where(TableAssignment.tenant_id == tid, TableAssignment.released_at.is_(None))
        .values(released_at=now)
    )
    await session.execute(
        update(TableSession)
        .where(TableSession.tenant_id == tid, TableSession.status != "closed")
        .values(status="closed", closed_at=now)
    )
    await session.execute(update(RestaurantTable).where(RestaurantTable.tenant_id == tid).values(status="available"))
    # Phase 9: back to the demo pantry (fresh stock, recipes, one supplier).
    for model in (PurchaseOrder, StockTransfer, InventoryItem, Supplier, InventoryCategory):
        await session.execute(delete(model).where(model.tenant_id == tid))
    primary = (await session.execute(select(Branch.id).where(Branch.tenant_id == tid, Branch.is_primary))).scalar_one()
    await _ensure_inventory(session, tid, primary)
    await session.commit()
    await invalidate_storefront(demo.slug)


async def seed_demo(session: AsyncSession, *, e2e: bool = False) -> list[str]:
    if get_settings().is_production:
        raise RuntimeError("seed-demo is for development only")
    if not e2e:
        return [await _seed_one(session, d, i + 1) for i, d in enumerate(DEMOS)]
    out = []
    for i, d in enumerate(DEMOS):
        variant = _e2e_variant(d, i + 1)
        out.append(await _seed_one(session, variant, i + 11))
        await _reset_e2e(session, variant)
    out.append(await _ensure_e2e_admin(session))
    return out


E2E_ADMIN_EMAIL = "e2e.admin@waitless.example.com"


async def _ensure_e2e_admin(session: AsyncSession) -> str:
    """Phase 11: a test-only Super Admin for the end-to-end tests (development databases only)."""
    from app.core.security import hash_password
    from app.models import User

    await use_system(session)
    user = (await session.execute(select(User).where(User.email == E2E_ADMIN_EMAIL))).scalar_one_or_none()
    if user is None:
        user = User(email=E2E_ADMIN_EMAIL, full_name="E2E Admin (tests)")
        session.add(user)
    user.password_hash = hash_password(DEMO_PASSWORD)
    user.is_super_admin, user.is_active = True, True
    await session.commit()
    return f"super admin: {E2E_ADMIN_EMAIL}"

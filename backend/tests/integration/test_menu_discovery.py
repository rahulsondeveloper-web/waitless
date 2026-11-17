"""PRD §7 menu management, §2.1 discovery, owner preview, contact form."""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import bearer, create_super_admin, image_bytes, login, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

WEEK = [{"weekday": d, "is_closed": False, "opens_at": "00:00", "closes_at": "23:59"} for d in range(7)]


async def _owner(client: httpx.AsyncClient, **kw):  # type: ignore[no-untyped-def]
    tenant, payload = await register(client, **kw)
    return tenant, bearer(await login(client, payload["email"]))


async def _menu(client: httpx.AsyncClient, h: dict[str, str]) -> dict:
    r = await client.get("/api/v1/restaurant/menu", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _cat(menu: dict, name: str) -> dict:
    return next(c for c in menu["categories"] if c["name"] == name)


async def _publish(
    client: httpx.AsyncClient, tenant: dict, h: dict, admin: dict, *, lat: str, lng: str, city: str
) -> None:
    """Complete every required step, approve and publish."""
    p = (await client.get("/api/v1/restaurant/profile", headers=h)).json()
    await client.put(
        "/api/v1/restaurant/profile",
        json={**{k: p[k] for k in ("name", "restaurant_type", "cuisines")}, "short_description": f"{p['name']} food"},
        headers=h,
    )
    await client.post(
        "/api/v1/restaurant/branding/cover", files={"file": ("c.png", image_bytes(1600, 600), "image/png")}, headers=h
    )
    branch = (await client.get("/api/v1/restaurant/branches", headers=h)).json()[0]
    await client.patch(
        f"/api/v1/restaurant/branches/{branch['id']}",
        json={
            "name": branch["name"],
            "address_line": "1 Food Street",
            "city": city,
            "state": "MH",
            "country": "India",
            "lat": lat,
            "lng": lng,
        },
        headers=h,
    )
    await client.put(f"/api/v1/restaurant/branches/{branch['id']}/hours", json={"days": WEEK}, headers=h)
    await client.post(
        "/api/v1/restaurant/tables", json={"branch_id": branch["id"], "label": "T1", "capacity": 4}, headers=h
    )
    menu = await _menu(client, h)
    await client.post(
        "/api/v1/restaurant/menu/items",
        json={"category_id": _cat(menu, "Starters")["id"], "name": f"{p['name']} Special", "base_price": "250"},
        headers=h,
    )
    await client.patch(
        f"/api/v1/super-admin/restaurants/{tenant['id']}/status", json={"action": "approve"}, headers=admin
    )
    r = await client.post("/api/v1/restaurant/publish", json={"published": True}, headers=h)
    assert r.status_code == 200, r.text


# ---------- menu ----------


async def test_default_taxonomy_is_seeded(client: httpx.AsyncClient) -> None:
    _, h = await _owner(client)
    menu = await _menu(client, h)
    assert [m["name"] for m in menu["meal_types"]][:3] == ["Breakfast", "Brunch", "Snacks & Quick Bites"]
    starters = _cat(menu, "Starters")
    names = {m["id"]: m["name"] for m in menu["meal_types"]}
    assert {names[i] for i in starters["meal_type_ids"]} == {"Lunch", "Dinner"}
    assert "Veg Starters" in [s["name"] for s in starters["subcategories"]]
    alcoholic = _cat(menu, "Alcoholic")
    assert alcoholic["is_alcoholic"] and not alcoholic["is_active"]
    assert menu["alcohol_licensed"] is False and menu["items"] == []


async def test_item_lifecycle_and_public_menu(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    tenant, h = await _owner(client, restaurant_name="Menu House")
    menu = await _menu(client, h)
    starters = _cat(menu, "Starters")
    veg = next(s for s in starters["subcategories"] if s["name"] == "Veg Starters")
    desserts = _cat(menu, "Desserts")

    r = await client.post(
        "/api/v1/restaurant/menu/items",
        json={
            "category_id": starters["id"],
            "subcategory_id": veg["id"],
            "name": "  Paneer Tikka ",
            "description": "Smoky cottage cheese",
            "base_price": "320.50",
            "food_class": "veg",
            "spice_level": 2,
            "allergens": ["dairy", "dairy"],
            "is_bestseller": True,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["name"] == "Paneer Tikka" and item["base_price"] == "320.50" and item["allergens"] == ["dairy"]

    # Wrong subcategory for the category → 422
    bad = await client.post(
        "/api/v1/restaurant/menu/items",
        json={"category_id": desserts["id"], "subcategory_id": veg["id"], "name": "X", "base_price": "1"},
        headers=h,
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "SUBCATEGORY_MISMATCH"
    assert (
        await client.post(
            "/api/v1/restaurant/menu/items",
            json={"category_id": starters["id"], "name": "X", "base_price": "-1"},
            headers=h,
        )
    ).status_code == 422

    # Image
    img = await client.post(
        f"/api/v1/restaurant/menu/items/{item['id']}/image",
        files={"file": ("p.png", image_bytes(800, 600), "image/png")},
        headers=h,
    )
    assert img.json()["image_url"].endswith(".webp")

    # Move to Desserts: subcategory is cleared because it belonged to Starters.
    moved = (
        await client.patch(
            f"/api/v1/restaurant/menu/items/{item['id']}", json={"category_id": desserts["id"]}, headers=h
        )
    ).json()
    assert moved["category_id"] == desserts["id"] and moved["subcategory_id"] is None
    await client.patch(
        f"/api/v1/restaurant/menu/items/{item['id']}",
        json={"category_id": starters["id"], "subcategory_id": veg["id"]},
        headers=h,
    )

    sold_out = (
        await client.patch(f"/api/v1/restaurant/menu/items/{item['id']}/stock", json={"is_available": False}, headers=h)
    ).json()
    assert sold_out["is_available"] is False

    # Second dish, then publish and check what guests see.
    await _publish(client, tenant, h, admin, lat="18.52", lng="73.85", city="Pune")
    public = (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}/menu")).json()
    assert public["currency"] == "INR"
    assert {m["name"] for m in public["meal_types"]} == {"Lunch", "Dinner"}  # only meal types with dishes
    cat = next(c for c in public["categories"] if c["name"] == "Starters")
    paneer = next(i for i in cat["items"] if i["name"] == "Paneer Tikka")
    assert paneer["subcategory"] == "Veg Starters" and paneer["is_available"] is False and paneer["price"] == "320.50"
    assert all(c["name"] != "Desserts" for c in public["categories"])  # empty categories hidden

    # Archive hides it from guests immediately (cache invalidated).
    await client.post(f"/api/v1/restaurant/menu/items/{item['id']}/archive", headers=h)
    public = (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}/menu")).json()
    assert all(i["name"] != "Paneer Tikka" for c in public["categories"] for i in c["items"])
    restored = (await client.post(f"/api/v1/restaurant/menu/items/{item['id']}/restore", headers=h)).json()
    assert restored["is_archived"] is False

    # Switching a category off hides it.
    await client.patch(f"/api/v1/restaurant/menu/categories/{starters['id']}", json={"is_active": False}, headers=h)
    public = (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}/menu")).json()
    assert public["categories"] == [] and public["meal_types"] == []


async def test_structure_management_rules(client: httpx.AsyncClient) -> None:
    _, h = await _owner(client)
    menu = await _menu(client, h)
    lunch = next(m for m in menu["meal_types"] if m["name"] == "Lunch")

    created = await client.post(
        "/api/v1/restaurant/menu/categories",
        json={"name": "Wood-fired Pizzas", "meal_type_ids": [lunch["id"]]},
        headers=h,
    )
    assert created.status_code == 201
    pizza = _cat(created.json(), "Wood-fired Pizzas")
    dup = await client.post(
        "/api/v1/restaurant/menu/categories",
        json={"name": "wood-fired pizzas", "meal_type_ids": [lunch["id"]]},
        headers=h,
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_NAME"

    with_sub = await client.post(
        f"/api/v1/restaurant/menu/categories/{pizza['id']}/subcategories", json={"name": "Napoletana"}, headers=h
    )
    sub = _cat(with_sub.json(), "Wood-fired Pizzas")["subcategories"][0]
    await client.post(
        "/api/v1/restaurant/menu/items",
        json={"category_id": pizza["id"], "subcategory_id": sub["id"], "name": "Margherita", "base_price": "580"},
        headers=h,
    )
    blocked = await client.delete(f"/api/v1/restaurant/menu/categories/{pizza['id']}", headers=h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CATEGORY_NOT_EMPTY"

    # Deleting a subcategory keeps the dish in its category.
    after = (await client.delete(f"/api/v1/restaurant/menu/subcategories/{sub['id']}", headers=h)).json()
    marg = next(i for i in after["items"] if i["name"] == "Margherita")
    assert marg["subcategory_id"] is None and marg["category_id"] == pizza["id"]

    alcohol = _cat(menu, "Alcoholic")
    refused = await client.patch(
        f"/api/v1/restaurant/menu/categories/{alcohol['id']}", json={"is_active": True}, headers=h
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ALCOHOL_NOT_LICENSED"

    unknown = await client.post(
        "/api/v1/restaurant/menu/categories",
        json={"name": "Ghost", "meal_type_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=h,
    )
    assert unknown.status_code == 422


async def test_menu_is_private_per_restaurant(client: httpx.AsyncClient) -> None:
    _, ha = await _owner(client, restaurant_name="Alpha Menu")
    _, hb = await _owner(client, restaurant_name="Beta Menu")
    a_menu = await _menu(client, ha)
    item = (
        await client.post(
            "/api/v1/restaurant/menu/items",
            json={"category_id": _cat(a_menu, "Starters")["id"], "name": "Alpha Soup", "base_price": "100"},
            headers=ha,
        )
    ).json()
    # B cannot edit A's dish, nor put a dish into A's category.
    assert (
        await client.patch(f"/api/v1/restaurant/menu/items/{item['id']}", json={"name": "x"}, headers=hb)
    ).status_code == 404
    stolen = await client.post(
        "/api/v1/restaurant/menu/items",
        json={"category_id": _cat(a_menu, "Starters")["id"], "name": "B in A", "base_price": "1"},
        headers=hb,
    )
    assert stolen.status_code == 404
    assert (await _menu(client, hb))["items"] == []


async def test_menu_permissions(client: httpx.AsyncClient) -> None:
    mobile = "9811122233"
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    customer = bearer((await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})).json())
    assert (await client.get("/api/v1/restaurant/menu", headers=customer)).status_code == 403


# ---------- preview & checklist ----------


async def test_owner_preview_before_publishing(client: httpx.AsyncClient) -> None:
    tenant, h = await _owner(client, restaurant_name="Preview Place")
    assert (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}")).status_code == 404
    preview = await client.get("/api/v1/restaurant/storefront", headers=h)
    assert preview.status_code == 200
    assert preview.json()["name"] == "Preview Place" and preview.json()["is_published"] is False
    assert (await client.get("/api/v1/restaurant/storefront/menu", headers=h)).json()["categories"] == []


# ---------- discovery ----------


async def test_discovery_filters_distance_and_visibility(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    pune, ph = await _owner(
        client, restaurant_name="Pune Spice", cuisines=["North Indian"], restaurant_type="Casual Dining"
    )
    await _publish(client, pune, ph, admin, lat="18.520430", lng="73.856743", city="Pune")
    mumbai, mh = await _owner(client, restaurant_name="Bombay Bistro", cuisines=["Italian"], restaurant_type="Cafe")
    await _publish(client, mumbai, mh, admin, lat="19.076090", lng="72.877426", city="Mumbai")
    hidden, _ = await _owner(client, restaurant_name="Secret Kitchen")  # pending, unpublished

    all_ = (await client.get("/api/v1/public/restaurants")).json()
    slugs = [c["slug"] for c in all_["items"]]
    assert set(slugs) == {pune["slug"], mumbai["slug"]} and hidden["slug"] not in slugs
    card = next(c for c in all_["items"] if c["slug"] == pune["slug"])
    assert card["city"] == "Pune" and card["cover_url"] and card["open_now"] is True and card["today_hours"]

    by_city = (await client.get("/api/v1/public/restaurants", params={"city": "mumbai"})).json()
    assert [c["slug"] for c in by_city["items"]] == [mumbai["slug"]]
    by_cuisine = (await client.get("/api/v1/public/restaurants", params={"cuisine": "italian"})).json()
    assert [c["slug"] for c in by_cuisine["items"]] == [mumbai["slug"]]
    by_type = (await client.get("/api/v1/public/restaurants", params={"type": "Casual Dining"})).json()
    assert [c["slug"] for c in by_type["items"]] == [pune["slug"]]
    by_q = (await client.get("/api/v1/public/restaurants", params={"q": "bistro"})).json()
    assert [c["slug"] for c in by_q["items"]] == [mumbai["slug"]]

    near_pune = (await client.get("/api/v1/public/restaurants", params={"lat": 18.53, "lng": 73.86})).json()
    assert [c["slug"] for c in near_pune["items"]] == [pune["slug"], mumbai["slug"]]
    assert near_pune["items"][0]["distance_km"] < 3
    within_50 = (
        await client.get("/api/v1/public/restaurants", params={"lat": 18.53, "lng": 73.86, "radius_km": 50})
    ).json()
    assert [c["slug"] for c in within_50["items"]] == [pune["slug"]]

    paged = (await client.get("/api/v1/public/restaurants", params={"page_size": 1, "page": 2})).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1

    f = (await client.get("/api/v1/public/discovery/filters")).json()
    assert f["cities"] == ["Mumbai", "Pune"] and "Italian" in f["cuisines"] and "Cafe" in f["restaurant_types"]


async def test_contact_form(client: httpx.AsyncClient, admin_engine: AsyncEngine) -> None:
    body = {
        "name": "Riya",
        "email": "Riya@Example.com",
        "topic": "restaurant_signup",
        "message": "Please call me back.",
    }
    r = await client.post("/api/v1/public/contact", json=body)
    assert r.status_code == 201 and r.json()["received"]
    bot = await client.post("/api/v1/public/contact", json={**body, "website": "http://spam.example"})
    assert bot.status_code == 201
    assert (await client.post("/api/v1/public/contact", json={**body, "message": "hi"})).status_code == 422
    async with admin_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT email, topic FROM support_tickets"))).all()
    assert [tuple(r) for r in rows] == [("riya@example.com", "restaurant_signup")]  # honeypot not stored

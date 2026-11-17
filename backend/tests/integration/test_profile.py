"""PRD §5 profile & branding management, §6 public storefront. Covers PRD test 3 (logo + five photos) and 4."""

import io
import os
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import MEDIA_ROOT, bearer, create_super_admin, image_bytes, login, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

WEEK = [{"weekday": d, "is_closed": False, "opens_at": "11:00", "closes_at": "23:00"} for d in range(7)]


async def _owner(client: httpx.AsyncClient, **kw):  # type: ignore[no-untyped-def]
    tenant, payload = await register(client, **kw)
    return tenant, bearer(await login(client, payload["email"]))


def _file(name: str = "photo.png", data: bytes | None = None, ctype: str = "image/png"):  # type: ignore[no-untyped-def]
    return {"file": (name, data or image_bytes(), ctype)}


def _stored_path(url: str) -> Path:
    return Path(MEDIA_ROOT) / url.removeprefix("/media/")


# ---------- profile ----------


async def test_profile_read_and_update(client: httpx.AsyncClient) -> None:
    tenant, h = await _owner(client, restaurant_name="Urban Bites")
    p = (await client.get("/api/v1/restaurant/profile", headers=h)).json()
    assert p["name"] == "Urban Bites" and p["short_description"] == "" and p["cover_url"] is None

    body = {
        "name": "Urban Bites Cafe",
        "restaurant_type": "Cafe",
        "cuisines": ["Italian", "Italian", "Desserts"],
        "short_description": "Wood-fired pizzas and coffee.",
        "description": "Long text",
        "about_us": "Since 2015.",
        "contact_phone": "98765 43210",
        "contact_email": "Hello@UrbanBites.example.com",
        "website": "https://urbanbites.example.com",
    }
    r = await client.put("/api/v1/restaurant/profile", json=body, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "Urban Bites Cafe" and out["slug"] == tenant["slug"]  # slug never changes here
    assert out["cuisines"] == ["Italian", "Desserts"]
    assert out["contact_phone"] == "+919876543210"
    assert out["contact_email"] == "hello@urbanbites.example.com"

    bad = await client.put(
        "/api/v1/restaurant/profile", json={**body, "website": "http://plain.example.com"}, headers=h
    )
    assert bad.status_code == 422


# ---------- logo & cover ----------


async def test_logo_upload_replace_remove(client: httpx.AsyncClient) -> None:
    _, h = await _owner(client)
    r = await client.post("/api/v1/restaurant/branding/logo", files=_file(data=image_bytes(300, 300)), headers=h)
    assert r.status_code == 200, r.text
    first = r.json()["logo_url"]
    assert first.startswith("/media/tenants/") and first.endswith(".webp")
    assert Image.open(_stored_path(first)).format == "WEBP"

    served = await client.get(first)  # served by the app's /media mount
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"

    second = (
        await client.post("/api/v1/restaurant/branding/logo", files=_file(data=image_bytes(400, 400)), headers=h)
    ).json()
    assert second["logo_url"] != first
    assert not _stored_path(first).exists()  # replaced file is deleted

    removed = (await client.delete("/api/v1/restaurant/branding/logo", headers=h)).json()
    assert removed["logo_url"] is None
    assert not _stored_path(second["logo_url"]).exists()


async def test_cover_upload_and_validation(client: httpx.AsyncClient) -> None:
    _, h = await _owner(client)
    small = await client.post("/api/v1/restaurant/branding/cover", files=_file(data=image_bytes(400, 200)), headers=h)
    assert small.status_code == 422 and small.json()["error"]["code"] == "INVALID_IMAGE"

    fake = await client.post(
        "/api/v1/restaurant/branding/cover", files=_file("evil.png", b"GIF89a<script>", "image/png"), headers=h
    )
    assert fake.status_code == 422

    huge = await client.post(
        "/api/v1/restaurant/branding/cover", files=_file(data=os.urandom(6 * 1024 * 1024)), headers=h
    )
    assert huge.status_code == 413 and huge.json()["error"]["code"] == "FILE_TOO_LARGE"

    ok = await client.post("/api/v1/restaurant/branding/cover", files=_file(data=image_bytes(1600, 600)), headers=h)
    assert ok.status_code == 200 and ok.json()["cover_url"].endswith(".webp")


async def test_uploads_require_permission(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/restaurant/branding/logo", files=_file())
    assert r.status_code == 401


# ---------- gallery ----------


async def test_gallery_max_five_reorder_delete(client: httpx.AsyncClient) -> None:
    tenant, h = await _owner(client)
    for i in range(5):
        r = await client.post(
            "/api/v1/restaurant/gallery", files=_file(), data={"caption": f"Photo {i + 1}"}, headers=h
        )
        assert r.status_code == 201, r.text
    items = r.json()["items"]
    assert [i["position"] for i in items] == [1, 2, 3, 4, 5]
    assert r.json()["max_photos"] == 5

    sixth = await client.post("/api/v1/restaurant/gallery", files=_file(), headers=h)
    assert sixth.status_code == 409 and sixth.json()["error"]["code"] == "GALLERY_LIMIT_REACHED"
    folder = Path(MEDIA_ROOT) / "tenants" / tenant["id"] / "gallery"
    assert len(list(folder.iterdir())) == 5  # the rejected upload left no file behind

    ids = [i["id"] for i in items]
    reordered = (await client.put("/api/v1/restaurant/gallery/order", json={"ids": ids[::-1]}, headers=h)).json()
    assert [i["caption"] for i in reordered["items"]] == ["Photo 5", "Photo 4", "Photo 3", "Photo 2", "Photo 1"]

    bad_order = await client.put("/api/v1/restaurant/gallery/order", json={"ids": ids[:3]}, headers=h)
    assert bad_order.status_code == 422

    after_delete = (await client.delete(f"/api/v1/restaurant/gallery/{ids[2]}", headers=h)).json()
    assert [i["position"] for i in after_delete["items"]] == [1, 2, 3, 4]
    assert ids[2] not in {i["id"] for i in after_delete["items"]}
    assert len(list(folder.iterdir())) == 4

    captioned = (
        await client.patch(f"/api/v1/restaurant/gallery/{ids[0]}", json={"caption": "Terrace"}, headers=h)
    ).json()
    assert any(i["caption"] == "Terrace" for i in captioned["items"])

    old_url = next(i["url"] for i in captioned["items"] if i["id"] == ids[0])
    replaced = (await client.put(f"/api/v1/restaurant/gallery/{ids[0]}", files=_file(), headers=h)).json()
    new_url = next(i["url"] for i in replaced["items"] if i["id"] == ids[0])
    assert new_url != old_url and not _stored_path(old_url).exists()

    # Now there is room again.
    assert (await client.post("/api/v1/restaurant/gallery", files=_file(), headers=h)).status_code == 201


async def test_gallery_is_private_per_restaurant(client: httpx.AsyncClient) -> None:
    _, ha = await _owner(client, restaurant_name="Alpha")
    _, hb = await _owner(client, restaurant_name="Beta")
    item = (await client.post("/api/v1/restaurant/gallery", files=_file(), headers=ha)).json()["items"][0]
    assert (await client.delete(f"/api/v1/restaurant/gallery/{item['id']}", headers=hb)).status_code == 404
    assert (await client.get("/api/v1/restaurant/gallery", headers=hb)).json()["items"] == []
    assert len((await client.get("/api/v1/restaurant/gallery", headers=ha)).json()["items"]) == 1


async def test_gallery_db_constraint_caps_positions(client: httpx.AsyncClient, admin_engine: AsyncEngine) -> None:
    tenant, h = await _owner(client)
    await client.post("/api/v1/restaurant/gallery", files=_file(), headers=h)
    async with admin_engine.connect() as conn:
        with pytest.raises(Exception, match="position_range"):
            await conn.execute(
                text("UPDATE restaurant_gallery SET position = 6 WHERE tenant_id = :t"), {"t": tenant["id"]}
            )


# ---------- branding ----------


async def test_branding_update_and_reset(client: httpx.AsyncClient, admin_engine: AsyncEngine) -> None:
    tenant, h = await _owner(client)
    initial = (await client.get("/api/v1/restaurant/branding", headers=h)).json()
    assert initial["is_default"] is True and initial["tokens"] == {}

    r = await client.put(
        "/api/v1/restaurant/branding",
        json={"tokens": {"primary": "#0A7C86", "accent": "#f2b134"}, "button_style": "rounded", "mode": "light"},
        headers=h,
    )
    assert r.status_code == 200
    b = r.json()
    assert b["tokens"] == {"primary": "#0a7c86", "accent": "#f2b134"}
    assert b["button_style"] == "rounded" and b["is_default"] is False and b["version"] == initial["version"] + 1

    bad = await client.put("/api/v1/restaurant/branding", json={"tokens": {"primary": "red"}}, headers=h)
    assert bad.status_code == 422

    reset = (await client.post("/api/v1/restaurant/branding/reset", headers=h)).json()
    assert reset["is_default"] is True and reset["tokens"] == {} and reset["button_style"] == "pill"
    async with admin_engine.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE action='branding.reset' AND tenant_id=:t"),
                {"t": tenant["id"]},
            )
        ).scalar_one()
    assert n == 1


# ---------- hours, location, social ----------


async def test_hours_location_and_social_links(client: httpx.AsyncClient) -> None:
    _, h = await _owner(client)
    branch = (await client.get("/api/v1/restaurant/branches", headers=h)).json()[0]
    url = f"/api/v1/restaurant/branches/{branch['id']}/hours"

    week = [dict(d) for d in WEEK]
    week[0] = {"weekday": 0, "is_closed": True}
    week[5] = {"weekday": 5, "is_closed": False, "opens_at": "18:00", "closes_at": "02:00"}  # past midnight
    r = await client.put(url, json={"days": week}, headers=h)
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert days[0]["is_closed"] and days[0]["opens_at"] is None
    assert days[5]["closes_at"] == "02:00:00"

    assert (await client.put(url, json={"days": WEEK[:6]}, headers=h)).status_code == 422
    open_no_times = [*WEEK[:6], {"weekday": 6, "is_closed": False}]
    assert (await client.put(url, json={"days": open_no_times}, headers=h)).status_code == 422

    loc = {
        "name": "Main",
        "address_line": "12 Olive Street",
        "city": "Pune",
        "state": "MH",
        "country": "India",
        "lat": "18.520430",
        "lng": "73.856743",
    }
    moved = await client.patch(f"/api/v1/restaurant/branches/{branch['id']}", json=loc, headers=h)
    assert moved.status_code == 200 and moved.json()["name"] == "Main"
    half = await client.patch(f"/api/v1/restaurant/branches/{branch['id']}", json={**loc, "lng": None}, headers=h)
    assert half.status_code == 422

    links = [{"platform": "instagram", "url": "https://instagram.com/urbanbites"}]
    assert (await client.put("/api/v1/restaurant/social-links", json={"links": links}, headers=h)).json() == links
    dup = await client.put("/api/v1/restaurant/social-links", json={"links": links * 2}, headers=h)
    assert dup.status_code == 422
    insecure = [{"platform": "facebook", "url": "http://facebook.com/x"}]
    assert (await client.put("/api/v1/restaurant/social-links", json={"links": insecure}, headers=h)).status_code == 422


# ---------- publishing & public storefront ----------


async def _complete_setup(client: httpx.AsyncClient, h: dict[str, str]) -> None:
    profile = (await client.get("/api/v1/restaurant/profile", headers=h)).json()
    await client.put(
        "/api/v1/restaurant/profile",
        json={**{k: profile[k] for k in ("name", "restaurant_type", "cuisines")}, "short_description": "Great food."},
        headers=h,
    )
    await client.post("/api/v1/restaurant/branding/cover", files=_file(data=image_bytes(1600, 600)), headers=h)
    branch = (await client.get("/api/v1/restaurant/branches", headers=h)).json()[0]
    await client.patch(
        f"/api/v1/restaurant/branches/{branch['id']}",
        json={
            "name": branch["name"],
            "address_line": branch["address_line"],
            "city": "Pune",
            "state": "MH",
            "country": "India",
            "lat": "18.52",
            "lng": "73.85",
        },
        headers=h,
    )
    await client.put(f"/api/v1/restaurant/branches/{branch['id']}/hours", json={"days": WEEK}, headers=h)
    await client.post(
        "/api/v1/restaurant/tables", json={"branch_id": branch["id"], "label": "T1", "capacity": 4}, headers=h
    )
    menu = (await client.get("/api/v1/restaurant/menu", headers=h)).json()
    starters = next(c for c in menu["categories"] if c["name"] == "Starters")
    await client.post(
        "/api/v1/restaurant/menu/items",
        json={"category_id": starters["id"], "name": "Tomato Basil Soup", "base_price": "290"},
        headers=h,
    )


async def test_publish_flow_and_public_storefront(client: httpx.AsyncClient) -> None:
    """PRD test 4: the storefront shows the restaurant's own branding — only once approved and published."""
    tenant, h = await _owner(client, restaurant_name="Spice Route")
    slug = tenant["slug"]

    checklist = (await client.get("/api/v1/restaurant/publish-checklist", headers=h)).json()
    missing = {i["key"] for i in checklist["items"] if i["required"] and not i["done"]}
    assert missing == {"approved", "description", "cover", "location", "hours", "menu", "tables"}
    blocked = await client.post("/api/v1/restaurant/publish", json={"published": True}, headers=h)
    assert blocked.status_code == 409 and set(blocked.json()["error"]["details"]["missing"]) == missing

    await _complete_setup(client, h)
    await client.put("/api/v1/restaurant/branding", json={"tokens": {"primary": "#0a7c86"}}, headers=h)
    await client.post("/api/v1/restaurant/branding/logo", files=_file(data=image_bytes(300, 300)), headers=h)
    await client.post("/api/v1/restaurant/gallery", files=_file(), data={"caption": "Dining room"}, headers=h)

    still = (await client.get("/api/v1/restaurant/publish-checklist", headers=h)).json()
    assert [i["key"] for i in still["items"] if i["required"] and not i["done"]] == ["approved"]

    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    await client.patch(
        f"/api/v1/super-admin/restaurants/{tenant['id']}/status", json={"action": "approve"}, headers=admin
    )

    assert (await client.get(f"/api/v1/public/restaurants/{slug}")).status_code == 404  # approved, not yet published
    published = await client.post("/api/v1/restaurant/publish", json={"published": True}, headers=h)
    assert published.status_code == 200 and published.json()["is_published"] is True

    sf = await client.get(f"/api/v1/public/restaurants/{slug}")
    assert sf.status_code == 200, sf.text
    s = sf.json()
    assert s["name"] == "Spice Route" and s["short_description"] == "Great food."
    assert s["branding"]["tokens"] == {"primary": "#0a7c86"} and s["branding"]["logo_url"].endswith(".webp")
    assert s["cover_url"].endswith(".webp") and s["gallery_count"] == 1
    assert len(s["branches"][0]["hours"]) == 7 and s["branches"][0]["lat"] == "18.520000"
    gallery = (await client.get(f"/api/v1/public/restaurants/{slug}/gallery")).json()
    assert gallery["items"][0]["caption"] == "Dining room"
    assert (await client.get(f"/api/v1/public/restaurants/{slug}/branding")).json()["tokens"]["primary"] == "#0a7c86"

    # Branding change is visible immediately (cache invalidated on write).
    await client.put("/api/v1/restaurant/branding", json={"tokens": {"primary": "#123456"}}, headers=h)
    assert (await client.get(f"/api/v1/public/restaurants/{slug}")).json()["branding"]["tokens"]["primary"] == "#123456"

    # Suspension takes the storefront offline immediately.
    await client.patch(
        f"/api/v1/super-admin/restaurants/{tenant['id']}/status",
        json={"action": "suspend", "reason": "x"},
        headers=admin,
    )
    assert (await client.get(f"/api/v1/public/restaurants/{slug}")).status_code == 404


async def test_unpublished_and_unknown_storefronts_are_404(client: httpx.AsyncClient) -> None:
    tenant, _ = await _owner(client)
    assert (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}")).status_code == 404
    assert (await client.get(f"/api/v1/public/restaurants/{tenant['slug']}/gallery")).status_code == 404
    assert (await client.get("/api/v1/public/restaurants/no-such-place")).status_code == 404


async def test_published_storefront_ignores_other_tenants_data(client: httpx.AsyncClient) -> None:
    """PRD test 6 at API level: two published restaurants never mix logos, galleries or hours."""
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    slugs = []
    for name, colour in (("Alpha Grill", "#111111"), ("Beta Cafe", "#222222")):
        tenant, h = await _owner(client, restaurant_name=name)
        await _complete_setup(client, h)
        await client.put("/api/v1/restaurant/branding", json={"tokens": {"primary": colour}}, headers=h)
        await client.post("/api/v1/restaurant/gallery", files=_file(), data={"caption": name}, headers=h)
        await client.patch(
            f"/api/v1/super-admin/restaurants/{tenant['id']}/status", json={"action": "approve"}, headers=admin
        )
        assert (await client.post("/api/v1/restaurant/publish", json={"published": True}, headers=h)).status_code == 200
        slugs.append(tenant["slug"])

    a = (await client.get(f"/api/v1/public/restaurants/{slugs[0]}")).json()
    b = (await client.get(f"/api/v1/public/restaurants/{slugs[1]}")).json()
    assert a["branding"]["tokens"]["primary"] == "#111111" and b["branding"]["tokens"]["primary"] == "#222222"
    assert a["cover_url"] != b["cover_url"] and a["branches"][0]["id"] != b["branches"][0]["id"]
    ga = (await client.get(f"/api/v1/public/restaurants/{slugs[0]}/gallery")).json()["items"]
    gb = (await client.get(f"/api/v1/public/restaurants/{slugs[1]}/gallery")).json()["items"]
    assert [g["caption"] for g in ga] == ["Alpha Grill"] and [g["caption"] for g in gb] == ["Beta Cafe"]
    assert io  # keep import used for readers extending these tests

"""Phase 7: menu options, table code + PIN, ordering, idempotency, kitchen flow, pre-orders, isolation."""

import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.integrations.payments.gateway import MockGateway
from tests.conftest import random_mobile
from tests.integration.test_bookings import _book, _otp_login, _setup, _tomorrow_at

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
P = "/api/v1/public/restaurants"


async def _dish(client: httpx.AsyncClient, h: dict, name: str, price: str = "200", **kw) -> dict:  # type: ignore[no-untyped-def]
    menu = (await client.get(f"{B}/menu", headers=h)).json()
    cat = next(c for c in menu["categories"] if c["name"] == "Starters")
    r = await client.post(
        f"{B}/menu/items", json={"category_id": cat["id"], "name": name, "base_price": price, **kw}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _pizza(client: httpx.AsyncClient, h: dict) -> dict:
    """Pizza: Regular 300 / Large 450; toppings group (pick 1–2): Olives 40, Paneer 60."""
    item = await _dish(client, h, "Farmhouse Pizza", "300", tax_pct="5")
    r = await client.put(
        f"{B}/menu/items/{item['id']}/options",
        json={
            "variants": [{"name": "Regular", "price": "300"}, {"name": "Large", "price": "450"}],
            "addon_groups": [
                {
                    "name": "Toppings",
                    "min_select": 1,
                    "max_select": 2,
                    "addons": [{"name": "Olives", "price": "40"}, {"name": "Paneer", "price": "60"}],
                }
            ],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _seat(client: httpx.AsyncClient, h: dict, table: dict, party: int = 2) -> dict:
    r = await client.post(f"{B}/table-sessions", json={"table_id": table["id"], "party_size": party}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _join(client: httpx.AsyncClient, slug: str, seated: dict) -> dict[str, str]:
    r = await client.post(
        f"{P}/{slug}/table-sessions/join", json={"code": seated["session"]["public_code"], "pin": seated["pin"]}
    )
    assert r.status_code == 200, r.text
    return {"X-Table-Token": r.json()["token"]}


async def _staff(client: httpx.AsyncClient, h: dict, branch: dict, role: str) -> dict[str, str]:
    roles = {r["key"]: r for r in (await client.get(f"{B}/roles", headers=h)).json()}
    mobile = random_mobile()
    r = await client.post(
        f"{B}/staff",
        json={
            "full_name": f"{role.title()} Person",
            "phone": mobile,
            "role_id": roles[role]["id"],
            "branch_ids": [branch["id"]],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return await _otp_login(client, mobile)


# ---------- menu options ----------


async def test_menu_options_branch_override_and_public_menu(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    pizza = await _pizza(client, h)
    assert [v["name"] for v in pizza["variants"]] == ["Regular", "Large"]
    assert pizza["addon_groups"][0]["min_select"] == 1 and len(pizza["addon_groups"][0]["addons"]) == 2

    bad = await client.put(
        f"{B}/menu/items/{pizza['id']}/options",
        json={"addon_groups": [{"name": "X", "min_select": 3, "max_select": 2, "addons": [{"name": "a"}]}]},
        headers=h,
    )
    assert bad.status_code == 422

    soup = await _dish(client, h, "Lunch Soup", "120", tags=["Chef Pick", "chef pick"])
    assert soup["tags"] == ["chef pick"]
    r = await client.put(
        f"{B}/menu/items/{soup['id']}/options",
        json={"availability": [{"weekday": d, "from_time": "12:00", "to_time": "15:00"} for d in range(7)]},
        headers=h,
    )
    assert len(r.json()["availability"]) == 7
    ov = await client.put(
        f"{B}/menu/items/{soup['id']}/branches/{branch['id']}",
        json={"is_available": True, "price_override": "99"},
        headers=h,
    )
    assert ov.json()["branch_overrides"] == [
        {"branch_id": branch["id"], "is_available": True, "price_override": "99.00"}
    ]

    menu = (await client.get(f"{P}/{tenant['slug']}/menu")).json()
    assert menu["ordering_enabled"] is True
    items = {i["name"]: i for c in menu["categories"] for i in c["items"]}
    assert items["Farmhouse Pizza"]["variants"][1]["price"] == "450.00"
    assert items["Lunch Soup"]["availability"][0]["from_time"] == "12:00:00"


# ---------- table code + PIN, ordering ----------


async def test_guest_orders_from_table_with_code_and_pin(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    slug = tenant["slug"]
    pizza = await _pizza(client, h)
    seated = await _seat(client, h, tables["T1"])

    wrong = await client.post(
        f"{P}/{slug}/table-sessions/join",
        json={"code": seated["session"]["public_code"], "pin": "0000" if seated["pin"] != "0000" else "1111"},
    )
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "INVALID_TABLE_PIN"
    t = await _join(client, slug, seated)
    assert (await client.get("/api/v1/table-session")).status_code == 401  # token required

    view = (await client.get("/api/v1/table-session", headers=t)).json()
    assert view["code"] == seated["session"]["public_code"] and view["table_labels"] == ["T1"] and view["orders"] == []

    reg, large = pizza["variants"]
    olives, paneer = pizza["addon_groups"][0]["addons"]
    no_size = await client.post(
        "/api/v1/table-session/orders",
        json={"items": [{"menu_item_id": pizza["id"], "addon_ids": [olives["id"]]}]},
        headers=t,
    )
    assert no_size.status_code == 422 and no_size.json()["error"]["code"] == "VARIANT_REQUIRED"
    no_topping = await client.post(
        "/api/v1/table-session/orders",
        json={"items": [{"menu_item_id": pizza["id"], "variant_id": reg["id"]}]},
        headers=t,
    )
    assert no_topping.status_code == 422 and no_topping.json()["error"]["code"] == "ADDON_RULES"

    body = {
        "items": [
            {
                "menu_item_id": pizza["id"],
                "variant_id": large["id"],
                "addon_ids": [olives["id"], paneer["id"]],
                "quantity": 2,
                "instructions": "Extra crispy",
            },
        ],
        "notes": "Birthday",
    }
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = await client.post("/api/v1/table-session/orders", json=body, headers={**t, **key})
    assert first.status_code == 201, first.text
    o = first.json()
    # (450 + 40 + 60) × 2 = 1100; tax 5% = 55
    assert o["items"][0]["unit_price"] == "550.00" and o["subtotal"] == "1100.00" and o["tax_total"] == "55.00"
    assert o["total"] == "1155.00" and o["status"] == "placed" and o["order_type"] == "walk_in" and o["number"] == "001"
    assert o["items"][0]["addons"] == [{"name": "Olives", "price": "40.00"}, {"name": "Paneer", "price": "60.00"}]

    again = await client.post("/api/v1/table-session/orders", json=body, headers={**t, **key})
    assert again.status_code == 200 and again.json()["id"] == o["id"]  # same key → the original order
    view = (await client.get("/api/v1/table-session", headers=t)).json()
    assert len(view["orders"]) == 1 and view["total"] == "1155.00"

    # Menu edits afterwards never change the placed order (snapshots).
    await client.patch(f"{B}/menu/items/{pizza['id']}", json={"name": "Renamed Pizza"}, headers=h)
    await client.patch(f"{B}/menu/items/{pizza['id']}/stock", json={"is_available": False}, headers=h)
    view = (await client.get("/api/v1/table-session", headers=t)).json()
    assert view["orders"][0]["items"][0]["name"] == "Farmhouse Pizza"
    sold_out = await client.post("/api/v1/table-session/orders", json=body, headers=t)
    assert sold_out.status_code == 409 and sold_out.json()["error"]["code"] == "ITEM_UNAVAILABLE"

    # A new PIN logs out old links; closing the table stops new orders.
    new_pin = await client.post(f"{B}/table-sessions/{seated['session']['id']}/pin", headers=h)
    assert (await client.get("/api/v1/table-session", headers=t)).status_code == 401
    t2 = await _join(client, slug, {"session": seated["session"], "pin": new_pin.json()["pin"]})
    await client.post(f"{B}/table-sessions/{seated['session']['id']}/close", headers=h)
    closed = await client.post("/api/v1/table-session/orders", json=body, headers=t2)
    assert closed.status_code in (401, 409)


async def test_availability_window_is_enforced(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    other_day = (now.weekday() + 3) % 7
    soup = await _dish(client, h, "Weekend Soup", "120")
    await client.put(
        f"{B}/menu/items/{soup['id']}/options",
        json={"availability": [{"weekday": other_day, "from_time": "00:00", "to_time": "23:59"}]},
        headers=h,
    )
    t = await _join(client, tenant["slug"], await _seat(client, h, tables["T2"]))
    r = await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": soup["id"]}]}, headers=t)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ITEM_NOT_AVAILABLE_NOW"
    # Branch price override applies to the order.
    await client.put(f"{B}/menu/items/{soup['id']}/options", json={}, headers=h)
    await client.put(
        f"{B}/menu/items/{soup['id']}/branches/{branch['id']}",
        json={"is_available": True, "price_override": "99"},
        headers=h,
    )
    ok = await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": soup["id"]}]}, headers=t)
    assert ok.status_code == 201 and ok.json()["subtotal"] == "99.00"
    await client.put(f"{B}/menu/items/{soup['id']}/branches/{branch['id']}", json={"is_available": False}, headers=h)
    off = await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": soup["id"]}]}, headers=t)
    assert off.status_code == 409


async def test_pin_attempts_are_limited(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    seated = await _seat(client, h, tables["T1"])
    code = seated["session"]["public_code"]
    wrong = "0000" if seated["pin"] != "0000" else "1111"
    codes = [
        (await client.post(f"{P}/{tenant['slug']}/table-sessions/join", json={"code": code, "pin": wrong})).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # Even the right PIN is refused while locked.
    locked = await client.post(f"{P}/{tenant['slug']}/table-sessions/join", json={"code": code, "pin": seated["pin"]})
    assert locked.status_code == 429


# ---------- kitchen & staff ----------


async def test_kitchen_flow_ready_is_not_served(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    dish = await _dish(client, h, "Masala Fries", "150")
    seated = await _seat(client, h, tables["T1"])

    waiter = await _staff(client, h, branch, "waiter")
    cook = await _staff(client, h, branch, "kitchen")
    placed = await client.post(
        f"{B}/orders",
        json={"table_session_id": seated["session"]["id"], "items": [{"menu_item_id": dish["id"], "quantity": 3}]},
        headers=waiter,
    )
    assert placed.status_code == 201, placed.text
    o = placed.json()
    assert (
        o["order_type"] == "staff"
        and o["session_code"] == seated["session"]["public_code"]
        and o["table_labels"] == ["T1"]
    )
    assert (
        await client.post(
            f"{B}/orders",
            json={"table_session_id": seated["session"]["id"], "items": [{"menu_item_id": dish["id"]}]},
            headers=cook,
        )
    ).status_code == 403

    kitchen = (await client.get(f"{B}/orders", params={"branch_id": branch["id"]}, headers=cook)).json()
    assert [x["id"] for x in kitchen] == [o["id"]]

    async def move(to: str, who: dict) -> httpx.Response:
        return await client.post(f"{B}/orders/{o['id']}/status", json={"status": to}, headers=who)

    assert (await move("ready", cook)).status_code == 409  # cannot skip preparing
    assert (await move("accepted", waiter)).status_code == 403  # waiters don't run the kitchen
    assert (await move("accepted", cook)).json()["status"] == "accepted"
    assert (await move("preparing", cook)).json()["status"] == "preparing"
    ready = await move("ready", cook)
    assert ready.json()["status"] == "ready" and ready.json()["ready_at"]
    denied = await move("served", cook)
    assert denied.status_code == 403  # Ready ≠ Served: the kitchen cannot mark served
    served = await move("served", waiter)
    assert served.json()["status"] == "served" and served.json()["served_at"]
    assert (await client.post(f"{B}/orders/{o['id']}/cancel", json={"reason": "x"}, headers=h)).status_code == 409

    # Guests may cancel only before the kitchen accepts.
    t = await _join(client, tenant["slug"], seated)
    g = (
        await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=t)
    ).json()
    assert g["number"] == "002" and g["can_cancel"] is True
    assert (await client.post(f"/api/v1/table-session/orders/{g['id']}/cancel", headers=t)).json()[
        "status"
    ] == "cancelled"
    g2 = (
        await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=t)
    ).json()
    await client.post(f"{B}/orders/{g2['id']}/status", json={"status": "accepted"}, headers=cook)
    late = await client.post(f"/api/v1/table-session/orders/{g2['id']}/cancel", headers=t)
    assert late.status_code == 409
    staff_cancel = await client.post(f"{B}/orders/{g2['id']}/cancel", json={"reason": "Out of potatoes"}, headers=h)
    assert staff_cancel.json()["cancel_reason"] == "Out of potatoes"

    day = (await client.get(f"{B}/orders", params={"branch_id": branch["id"], "active": False}, headers=h)).json()
    assert {x["status"] for x in day} == {"served", "cancelled"}
    dash = (await client.get(f"{B}/dashboard", params={"branch_id": branch["id"]}, headers=h)).json()
    assert dash["orders_today"] == 1 and dash["active_orders"] == 0  # cancelled orders do not count


# ---------- pre-orders ----------


async def test_preorders_paid_only_and_start_at_arrival(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    slug = tenant["slug"]
    dish = await _dish(client, h, "Garlic Bread", "180")
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "300"},
        headers=h,
    )
    line = {"items": [{"menu_item_id": dish["id"], "quantity": 2}]}

    free_guest = await _otp_login(client)
    free = (await _book(client, slug, free_guest, branch, _tomorrow_at(13))).json()["reservation"]
    denied = await client.post(f"/api/v1/me/reservations/{free['id']}/orders", json=line, headers=free_guest)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "PREORDER_NOT_ALLOWED"

    guest = await _otp_login(client)
    booked = (await _book(client, slug, guest, branch, _tomorrow_at(19), type="paid")).json()
    res = booked["reservation"]
    unpaid = await client.post(f"/api/v1/me/reservations/{res['id']}/orders", json=line, headers=guest)
    assert unpaid.status_code == 403 and unpaid.json()["error"]["code"] == "PREORDER_NOT_ALLOWED"
    raw, sig = MockGateway.build_event(booked["payment"]["order_id"], Decimal("300"), True)
    await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})

    pre = await client.post(f"/api/v1/me/reservations/{res['id']}/orders", json=line, headers=guest)
    assert pre.status_code == 201, pre.text
    p = pre.json()
    assert p["order_type"] == "paid_preorder" and p["table_session_id"] is None and p["reservation_code"] == res["code"]
    assert p["restaurant_slug"] == slug and p["total"] == "378.00"

    early = await client.post(f"{B}/orders/{p['id']}/status", json={"status": "accepted"}, headers=h)
    assert early.status_code == 409 and early.json()["error"]["code"] == "PREORDER_NOT_ARRIVED"

    seated = await client.post(f"{B}/reservations/{res['id']}/arrive", json={}, headers=h)
    assert seated.status_code == 200
    mine = (await client.get(f"/api/v1/me/reservations/{res['id']}/orders", headers=guest)).json()
    assert mine[0]["table_session_id"] == seated.json()["session"]["id"]
    assert (
        await client.post(f"{B}/orders/{p['id']}/status", json={"status": "accepted"}, headers=h)
    ).status_code == 200
    assert [o["id"] for o in (await client.get("/api/v1/me/orders", headers=guest)).json()] == [p["id"]]


async def test_orders_isolated_between_restaurants(client: httpx.AsyncClient) -> None:
    tenant_a, h_a, branch_a, tables_a = await _setup(client, "Alpha Kitchen")
    _tenant_b, h_b, branch_b, _ = await _setup(client, "Beta Kitchen")
    dish_a = await _dish(client, h_a, "Alpha Dosa", "90")
    seated = await _seat(client, h_a, tables_a["T1"])
    t = await _join(client, tenant_a["slug"], seated)
    o = (
        await client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish_a["id"]}]}, headers=t)
    ).json()

    assert (await client.get(f"{B}/orders", params={"branch_id": branch_a["id"]}, headers=h_b)).status_code == 404
    assert (
        await client.post(f"{B}/orders/{o['id']}/status", json={"status": "accepted"}, headers=h_b)
    ).status_code == 404
    assert (await client.get(f"{B}/orders", params={"branch_id": branch_b["id"]}, headers=h_b)).json() == []
    # A's table code does not open anything at B; B's dishes cannot be ordered with A's token.
    other = await client.post(
        f"{P}/{_tenant_b['slug']}/table-sessions/join",
        json={"code": seated["session"]["public_code"], "pin": seated["pin"]},
    )
    assert other.status_code == 401
    dish_b = await _dish(client, h_b, "Beta Burger", "150")
    cross = await client.post(
        "/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish_b["id"]}]}, headers=t
    )
    assert cross.status_code == 409 and cross.json()["error"]["code"] == "ITEM_UNAVAILABLE"
    assert (
        await client.post(
            f"{B}/orders",
            json={"table_session_id": seated["session"]["id"], "items": [{"menu_item_id": dish_b["id"]}]},
            headers=h_b,
        )
    ).status_code == 404


async def test_concurrent_orders_get_unique_numbers(client: httpx.AsyncClient) -> None:
    import asyncio

    tenant, h, _, tables = await _setup(client)
    dish = await _dish(client, h, "Quick Chai", "30")
    t = await _join(client, tenant["slug"], await _seat(client, h, tables["T1"]))
    results = await asyncio.gather(
        *[
            client.post("/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=t)
            for _ in range(5)
        ]
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert sorted(r.json()["number"] for r in results) == ["001", "002", "003", "004", "005"]

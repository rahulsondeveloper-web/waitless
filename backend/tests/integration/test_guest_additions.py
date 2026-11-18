"""Additions after launch: names on orders (not on invoices), paying the restaurant's own UPI ID, receipts after the
visit with order ID + PIN, the customer's invoices, category photos, and table QR codes."""

import httpx
import pytest

from tests.conftest import bearer, image_bytes, random_mobile
from tests.integration.test_billing import _order, _serve, _settings
from tests.integration.test_bookings import _otp_login, _setup
from tests.integration.test_orders import _dish, _join, _seat

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
T = "/api/v1/table-session"
P = "/api/v1/public/restaurants"


async def test_names_show_on_orders_and_bills_but_not_on_the_invoice(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    dish = await _dish(client, h, "Pav Bhaji", "180", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    riya = await client.post(
        f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}], "guest_name": "Riya"}, headers=t
    )
    assert riya.json()["ordered_by_name"] == "Riya"
    # Signed in, no name typed → the account name.
    mobile = random_mobile()
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    auth = (
        await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code, "full_name": "Kabir"})
    ).json()
    guest = bearer(auth)
    signed = await client.post(f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers={**t, **guest})
    assert signed.json()["ordered_by_name"] == "Kabir"

    kitchen = (await client.get(f"{B}/orders", params={"branch_id": branch["id"]}, headers=h)).json()
    assert {o["ordered_by_name"] for o in kitchen} == {"Riya", "Kabir"}
    for o in (riya.json(), signed.json()):
        await _serve(client, h, o)
    bill = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()["bills"][0]
    assert "Riya" in {ln["ordered_by_name"] for ln in bill["lines"]}
    paid = (
        await client.post(
            f"{B}/bills/{bill['id']}/payments", json={"method": "cash", "amount": bill["grand_total"]}, headers=h
        )
    ).json()
    inv = (await client.get(f"{B}/invoices/{paid['invoices'][0]['id']}", headers=h)).json()
    assert all("ordered_by_name" not in ln for ln in inv["snapshot"]["bill"]["lines"])  # never on the invoice


async def test_pay_restaurant_upi_then_staff_confirm_and_receipt_after_closing(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    await _settings(client, h, round_off=False, upi_id="urbanbites@okhdfc", upi_payee_name="Urban Bites")
    bad = await client.put(
        f"{B}/billing-settings",
        json={**(await client.get(f"{B}/billing-settings", headers=h)).json(), "upi_id": "not a vpa"},
        headers=h,
    )
    assert bad.status_code == 422
    dish = await _dish(client, h, "Thali", "200", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    await _serve(client, h, await _order(client, t, (dish, 1)))
    fin = (await client.post(f"{T}/finish", headers=t)).json()
    assert fin["upi_id"] == "urbanbites@okhdfc" and fin["upi_payee_name"] == "Urban Bites"
    bill = fin["bills"][0]

    claimed = await client.post(f"{T}/bills/{bill['id']}/upi-claim", json={"reference": "UTR 4471"}, headers=t)
    assert claimed.status_code == 200
    b = claimed.json()["bills"][0]
    pending = b["payments"][0]
    assert (pending["status"], pending["amount"], b["locked"], b["status"]) == ("pending", "210.00", True, "open")
    again = (await client.post(f"{T}/bills/{bill['id']}/upi-claim", json={}, headers=t)).json()
    assert len(again["bills"][0]["payments"]) == 1  # one pending claim at a time

    rejected = await client.post(f"{B}/payments/{pending['id']}/reject", headers=h)
    assert rejected.json()["locked"] is False and rejected.json()["payments"][0]["status"] == "failed"
    second = (await client.post(f"{T}/bills/{bill['id']}/upi-claim", json={"reference": "UTR 4472"}, headers=t)).json()
    p2 = next(p for p in second["bills"][0]["payments"] if p["status"] == "pending")
    ok = await client.post(f"{B}/payments/{p2['id']}/confirm", headers=h)
    assert ok.json()["status"] == "paid" and ok.json()["invoices"][0]["kind"] == "invoice"
    assert (await client.post(f"{B}/payments/{p2['id']}/confirm", headers=h)).status_code == 409

    # After the guests leave, the same order ID + PIN still opens the visit to download the invoice.
    assert (await client.post(f"{B}/table-sessions/{seated['session']['id']}/close", headers=h)).status_code == 200
    later = await _join(client, tenant["slug"], seated)
    view = (await client.get(T, headers=later)).json()
    assert view["status"] == "closed" and view["ordering_open"] is False
    bills = (await client.get(f"{T}/bills", headers=later)).json()
    inv_id = bills["bills"][0]["invoices"][0]["id"]
    pdf = await client.get(f"{T}/invoices/{inv_id}/pdf", headers=later)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    blocked = await client.post(f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=later)
    assert blocked.status_code == 409


async def test_customer_sees_and_downloads_own_invoices(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    dish = await _dish(client, h, "Idli", "90", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    guest = await _otp_login(client)
    o = (
        await client.post(f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers={**t, **guest})
    ).json()
    await _serve(client, h, o)
    bill = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()["bills"][0]
    await client.post(
        f"{B}/bills/{bill['id']}/payments", json={"method": "upi", "amount": bill["grand_total"]}, headers=h
    )

    mine = (await client.get("/api/v1/me/invoices", headers=guest)).json()
    assert len(mine) == 1 and mine[0]["restaurant_slug"] == tenant["slug"] and mine[0]["items"] == ["1 × Idli"]
    pdf = await client.get(f"/api/v1/me/invoices/{mine[0]['id']}/pdf", headers=guest)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    stranger = await _otp_login(client)
    assert (await client.get("/api/v1/me/invoices", headers=stranger)).json() == []
    assert (await client.get(f"/api/v1/me/invoices/{mine[0]['id']}/pdf", headers=stranger)).status_code == 404


async def test_category_photo_upload_and_reset(client: httpx.AsyncClient) -> None:
    tenant, h, _, _ = await _setup(client)
    await _dish(client, h, "Spring Rolls", "150")
    menu = (await client.get(f"{B}/menu", headers=h)).json()
    cat = next(c for c in menu["categories"] if c["name"] == "Starters")
    assert cat["image_url"] is None  # the storefront shows the template's default photo
    up = await client.post(
        f"{B}/menu/categories/{cat['id']}/image",
        files={"file": ("s.png", image_bytes(800, 600), "image/png")},
        headers=h,
    )
    assert up.status_code == 200
    url = next(c for c in up.json()["categories"] if c["id"] == cat["id"])["image_url"]
    assert url and url.endswith(".webp")
    public = (await client.get(f"{P}/{tenant['slug']}/menu")).json()
    assert next(c for c in public["categories"] if c["id"] == cat["id"])["image_url"] == url
    reset = await client.delete(f"{B}/menu/categories/{cat['id']}/image", headers=h)
    assert next(c for c in reset.json()["categories"] if c["id"] == cat["id"])["image_url"] is None


async def test_table_qr_self_seating_join_and_rotate(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    slug = tenant["slug"]
    codes = (await client.get(f"{B}/table-qr", params={"branch_id": branch["id"]}, headers=h)).json()
    assert codes["self_seating"] is True and len(codes["tables"]) >= 2
    t1 = next(x for x in codes["tables"] if x["label"] == "T1")
    qr = t1["path"].rsplit("/", 1)[1]
    assert t1["path"] == f"/r/{slug}/t/{qr}"

    info = (await client.get(f"{P}/{slug}/tables/{qr}")).json()
    assert (info["table_label"], info["state"], info["self_seating"]) == ("T1", "free", True)
    started = await client.post(f"{P}/{slug}/tables/{qr}/start", json={"guest_name": "Arjun", "party_size": 3})
    assert started.status_code == 200, started.text
    s = started.json()
    assert len(s["pin"]) == 4 and s["code"] and s["table_label"] == "T1"
    view = (await client.get(T, headers={"X-Table-Token": s["token"]})).json()
    assert view["guest_name"] == "Arjun" and view["party_size"] == 3 and view["ordering_open"] is True
    assert (await client.get(f"{P}/{slug}/tables/{qr}")).json()["state"] == "occupied"
    taken = await client.post(f"{P}/{slug}/tables/{qr}/start", json={"guest_name": "Eve", "party_size": 2})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "TABLE_OCCUPIED"

    wrong = await client.post(f"{P}/{slug}/tables/{qr}/join", json={"pin": "0000" if s["pin"] != "0000" else "1111"})
    assert wrong.status_code == 401
    friend = await client.post(f"{P}/{slug}/tables/{qr}/join", json={"pin": s["pin"]})
    assert friend.status_code == 200 and friend.json()["session_id"] == s["session_id"] and friend.json()["pin"] is None

    t2 = next(x for x in codes["tables"] if x["label"] == "T2")["path"].rsplit("/", 1)[1]
    await client.put(f"{B}/table-qr/self-seating", json={"enabled": False}, headers=h)
    off = await client.post(f"{P}/{slug}/tables/{t2}/start", json={"guest_name": "Zoya", "party_size": 2})
    assert off.status_code == 409 and off.json()["error"]["code"] == "SELF_SEATING_OFF"
    rotated = (await client.post(f"{B}/table-qr/{t1['table_id']}/rotate", headers=h)).json()
    assert next(x for x in rotated["tables"] if x["label"] == "T1")["path"] != t1["path"]
    assert (await client.get(f"{P}/{slug}/tables/{qr}")).status_code == 404

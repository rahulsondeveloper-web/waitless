"""Guest service additions: call the waiter, Wi-Fi, reviews, split by person / equal shares, invoice with
names, and signed-in guests seeing their invoices without the order ID / PIN."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update

from app.core.db import get_sessionmaker, use_system
from app.models import ServiceRequest
from app.services import invoice_pdf
from tests.integration.test_billing import _serve, _settings
from tests.integration.test_bookings import _otp_login, _setup
from tests.integration.test_orders import _dish, _seat, _staff

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
T = "/api/v1/table-session"
P = "/api/v1/public/restaurants"


async def _join(client: httpx.AsyncClient, slug: str, seated: dict, auth: dict | None = None) -> dict[str, str]:
    r = await client.post(
        f"{P}/{slug}/table-sessions/join",
        json={"code": seated["session"]["public_code"], "pin": seated["pin"]},
        headers=auth or {},
    )
    assert r.status_code == 200, r.text
    return {"X-Table-Token": r.json()["token"]}


async def _named(client: httpx.AsyncClient, t: dict, dish: dict, qty: int, name: str) -> dict:
    r = await client.post(
        f"{T}/orders", json={"items": [{"menu_item_id": dish["id"], "quantity": qty}], "guest_name": name}, headers=t
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_call_the_waiter_with_cooldown_and_staff_clear(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)

    first = await client.post(f"{T}/calls", json={"kind": "water", "guest_name": "Dinesh"}, headers=t)
    assert first.status_code == 201, first.text
    call = first.json()["request"]
    assert (call["kind"], call["label"], call["table_labels"], call["guest_name"]) == ("water", "Water", "T1", "Dinesh")

    again = await client.post(f"{T}/calls", json={"kind": "bill"}, headers=t)  # any option, within 2 minutes
    assert again.status_code == 429 and again.json()["error"]["code"] == "CALL_COOLDOWN"
    assert 0 < again.json()["error"]["details"]["retry_after"] <= 120
    state = (await client.get(f"{T}/calls", headers=t)).json()
    assert state["cooldown_until"] and [c["kind"] for c in state["open"]] == ["water"]
    assert (await client.post(f"{T}/calls", json={"kind": "beer"}, headers=t)).status_code == 422
    assert (await client.post(f"{T}/calls", json={"kind": "help"})).status_code == 401  # needs the table token

    # Waiters and managers of the branch see it and clear it; kitchen staff cannot.
    waiter = await _staff(client, h, branch, "waiter")
    open_calls = (await client.get(f"{B}/service-calls", params={"branch_id": branch["id"]}, headers=waiter)).json()
    assert [c["id"] for c in open_calls] == [call["id"]]
    kitchen = await _staff(client, h, branch, "kitchen")
    assert (
        await client.get(f"{B}/service-calls", params={"branch_id": branch["id"]}, headers=kitchen)
    ).status_code == 403
    done = await client.post(f"{B}/service-calls/{call['id']}/done", headers=waiter)
    assert done.status_code == 200 and done.json()["status"] == "done"
    assert (await client.get(f"{B}/service-calls", params={"branch_id": branch["id"]}, headers=h)).json() == []

    # Two minutes later the guest can call again.
    async with get_sessionmaker()() as s:
        await use_system(s)
        await s.execute(update(ServiceRequest).values(created_at=datetime.now(UTC) - timedelta(minutes=3)))
        await s.commit()
    assert (await client.post(f"{T}/calls", json={"kind": "tissue"}, headers=t)).status_code == 201


async def test_wifi_for_seated_guests_only(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    assert (await client.get(f"{T}/wifi", headers=t)).json() is None  # not set up yet
    saved = await client.put(f"{B}/guest-wifi", json={"name": "Bistro-Guest", "password": "eat2gether"}, headers=h)
    assert saved.json() == {"name": "Bistro-Guest", "password": "eat2gether"}
    assert (await client.get(f"{T}/wifi", headers=t)).json() == {"name": "Bistro-Guest", "password": "eat2gether"}
    assert (await client.get(f"{T}/wifi")).status_code == 401  # never public


async def test_split_by_person_equal_shares_names_invoice_and_review(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    await _settings(client, h, round_off=False)
    dosa = await _dish(client, h, "Dosa", "100", tax_pct="5")
    lassi = await _dish(client, h, "Lassi", "60", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    customer = await _otp_login(client)
    t = await _join(client, tenant["slug"], seated, customer)  # signed in → linked to the visit
    for o in (await _named(client, t, dosa, 2, "Riya"), await _named(client, t, lassi, 1, "Kabir")):
        await _serve(client, h, o)
    fin = (await client.post(f"{T}/finish", headers=t)).json()
    bill = fin["bills"][0]
    assert bill["grand_total"] == "273.00"

    # Equal shares: one person pays half online.
    half = await client.post(f"{T}/bills/{bill['id']}/pay", json={"amount": "136.50"}, headers=t)
    assert half.status_code == 200 and half.json()["amount"] == "136.50"
    too_much = await client.post(f"{T}/bills/{bill['id']}/pay", json={"amount": "999"}, headers=t)
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "OVERPAYMENT"
    # The bill is locked now (a payment started), so it can no longer be split by person.
    locked = await client.post(f"{T}/bills/{bill['id']}/split-by-person", headers=t)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "BILL_LOCKED"

    # A second table: split by person before paying → one bill per name.
    seated2 = await _seat(client, h, tables["T2"])
    t2 = await _join(client, tenant["slug"], seated2)
    for o in (await _named(client, t2, dosa, 1, "Asha"), await _named(client, t2, lassi, 2, "Vikram")):
        await _serve(client, h, o)
    b2 = (await client.post(f"{T}/finish", headers=t2)).json()["bills"][0]
    split = await client.post(f"{T}/bills/{b2['id']}/split-by-person", headers=t2)
    assert split.status_code == 200, split.text
    by_name = {b["lines"][0]["ordered_by_name"]: b for b in split.json()["bills"]}
    assert set(by_name) == {"Asha", "Vikram"}
    assert by_name["Asha"]["grand_total"] == "105.00" and by_name["Vikram"]["grand_total"] == "126.00"
    for b in split.json()["bills"]:
        paid = await client.post(
            f"{B}/bills/{b['id']}/payments", json={"method": "cash", "amount": b["due"]}, headers=h
        )
        assert paid.status_code == 201
    one_name = (await client.post(f"{T}/bills/{bill['id']}/split-by-person", headers=t)).status_code
    assert one_name == 409  # (first table is locked; the one-person case is covered by ONE_PERSON below)

    # Pay the rest of table 1 → invoice; download with and without names.
    rest = (await client.get(f"{T}/bills", headers=t)).json()["bills"][0]
    await client.post(f"{B}/bills/{rest['id']}/payments", json={"method": "cash", "amount": rest["due"]}, headers=h)
    after = (await client.get(f"{T}/bills", headers=t)).json()
    assert after["session_status"] == "closed"
    inv = after["bills"][0]["invoices"][0]
    plain = await client.get(f"{T}/invoices/{inv['id']}/pdf", headers=t)
    named = await client.get(f"{T}/invoices/{inv['id']}/pdf", params={"names": "true"}, headers=t)
    assert plain.status_code == named.status_code == 200 and named.content[:5] == b"%PDF-"
    assert len(named.content) > len(plain.content)  # the copy with names has more on it

    # Signed-in guest: the invoice is under My orders without the order ID / PIN, with names too.
    mine = (await client.get("/api/v1/me/invoices", headers=customer)).json()
    assert inv["id"] in {i["id"] for i in mine}
    assert (await client.get(f"/api/v1/me/invoices/{inv['id']}/pdf?names=true", headers=customer)).status_code == 200

    # Review after paying: once per visit, public with the average; the owner can hide it.
    assert (await client.get(f"{T}/review", headers=t)).json()["can_review"] is True
    rev = await client.post(
        f"{T}/review", json={"rating": 4, "comment": "Crispy dosa!", "guest_name": "Riya"}, headers={**t, **customer}
    )
    assert rev.status_code == 201, rev.text
    assert (await client.post(f"{T}/review", json={"rating": 5}, headers=t)).status_code == 409
    public = (await client.get(f"{P}/{tenant['slug']}/reviews")).json()
    assert public["count"] == 1 and public["average"] == 4.0 and public["reviews"][0]["guest_name"] == "Riya"
    hidden = await client.patch(f"{B}/reviews/{rev.json()['id']}", json={"hidden": True}, headers=h)
    assert hidden.json()["hidden"] is True
    assert (await client.get(f"{P}/{tenant['slug']}/reviews")).json()["count"] == 0
    assert (await client.get(f"{B}/reviews", headers=h)).json()["reviews"][0]["hidden"] is True


async def test_review_needs_payment_and_split_needs_two_names(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    dosa = await _dish(client, h, "Dosa", "100", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    o = await _named(client, t, dosa, 1, "Riya")
    early = await client.post(f"{T}/review", json={"rating": 5}, headers=t)
    assert early.status_code == 409 and early.json()["error"]["code"] == "NOT_PAID"
    await _serve(client, h, o)
    bill = (await client.post(f"{T}/finish", headers=t)).json()["bills"][0]
    one = await client.post(f"{T}/bills/{bill['id']}/split-by-person", headers=t)
    assert one.status_code == 422 and one.json()["error"]["code"] == "ONE_PERSON"


def test_invoice_pdf_with_names_groups_dishes_per_person() -> None:
    snap = {
        "restaurant": {"name": "Bistro", "currency": "INR"},
        "bill": {
            "session_code": "BB-1234",
            "table_labels": ["T1"],
            "lines": [
                {
                    "order_item_id": "a",
                    "quantity": 2,
                    "name": "Dosa",
                    "line_total": "200.00",
                    "unit_price": "100.00",
                    "tax_pct": "5",
                    "order_number": "1",
                    "taxable": "200.00",
                },
                {
                    "order_item_id": "b",
                    "quantity": 1,
                    "name": "Lassi",
                    "line_total": "60.00",
                    "unit_price": "60.00",
                    "tax_pct": "5",
                    "order_number": "2",
                    "taxable": "60.00",
                },
            ],
            "subtotal": "260.00",
            "sla_discount": "0",
            "manual_discount": "0",
            "service_charge": "0",
            "taxes": [],
            "sla_discount_after_tax": "0",
            "booking_credit": "0",
            "round_off": "0",
            "grand_total": "273.00",
            "payments": [],
        },
    }
    plain = invoice_pdf.render("INV-1", "2026-11-18T12:00", snap)
    named = invoice_pdf.render("INV-1", "2026-11-18T12:00", snap, names={"a": "Riya", "b": "Kabir"})
    assert plain[:5] == named[:5] == b"%PDF-" and len(named) > len(plain)

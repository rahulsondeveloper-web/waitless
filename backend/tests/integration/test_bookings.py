"""Phase 6: walk-in queue, free & paid reservations, payment webhooks, expiry job, refunds, isolation."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker, use_system
from app.integrations.payments.gateway import MockGateway
from app.models.booking import Reservation, ReservationPayment
from app.models.tables import RestaurantTable
from app.services import reservations as res_svc
from tests.conftest import bearer, create_super_admin, login, random_mobile
from tests.integration.test_menu_discovery import _owner, _publish

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
P = "/api/v1/public/restaurants"
IST = ZoneInfo("Asia/Kolkata")


async def _otp_login(client: httpx.AsyncClient, mobile: str | None = None) -> dict[str, str]:
    mobile = mobile or random_mobile()
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    r = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})
    assert r.status_code == 200, r.text
    return bearer(r.json())


async def _setup(client: httpx.AsyncClient, name: str = "Booking Bistro"):  # type: ignore[no-untyped-def]
    email = f"admin-{random_mobile()}@waitless.test"
    await create_super_admin(email)
    admin = bearer(await login(client, email))
    tenant, h = await _owner(client, restaurant_name=name)
    await _publish(client, tenant, h, admin, lat="18.52", lng="73.85", city="Pune")
    branch = (await client.get(f"{B}/branches", headers=h)).json()[0]
    await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": "T2", "capacity": 2}, headers=h)
    tables = {
        t["label"]: t for t in (await client.get(f"{B}/tables", params={"branch_id": branch["id"]}, headers=h)).json()
    }
    return tenant, h, branch, tables


def _tomorrow_at(hour: int, minute: int = 0) -> datetime:
    d = datetime.now(IST).date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=IST)


async def _book(
    client: httpx.AsyncClient, slug: str, guest: dict, branch: dict, when: datetime, **kw
) -> httpx.Response:  # type: ignore[no-untyped-def]
    body = {"branch_id": branch["id"], "starts_at": when.isoformat(), "party_size": kw.pop("party", 2), **kw}
    return await client.post(f"{P}/{slug}/reservations", json=body, headers=guest)


# ---------- queue ----------


async def test_queue_join_notify_seat(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    slug = tenant["slug"]

    wt = (await client.get(f"{P}/{slug}/wait-time", params={"branch_id": branch["id"]})).json()
    assert wt["accepting"] is True and wt["waiting"] == 0 and wt["free_tables"] == 2

    # Everyone not signed in is refused; signed-in guests get a token.
    anon = await client.post(f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 2})
    assert anon.status_code == 401
    g1, g2 = await _otp_login(client), await _otp_login(client)
    e1 = await client.post(
        f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 2, "guest_name": "Asha"}, headers=g1
    )
    assert e1.status_code == 201, e1.text
    e1 = e1.json()
    assert e1["token"].startswith("A-") and e1["position"] == 1 and e1["status"] == "waiting"
    again = await client.post(f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 2}, headers=g1)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_IN_QUEUE"
    too_big = await client.post(f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 9}, headers=g2)
    assert too_big.status_code in (409, 422) and too_big.json()["error"]["code"] == "PARTY_TOO_LARGE"

    walk_in = await client.post(
        f"{B}/queue", json={"branch_id": branch["id"], "party_size": 3, "guest_name": "Ravi"}, headers=h
    )
    assert walk_in.status_code == 201 and walk_in.json()["position"] == 2 and walk_in.json()["source"] == "staff"

    staff_view = (await client.get(f"{B}/queue", params={"branch_id": branch["id"]}, headers=h)).json()
    assert [e["guest_name"] for e in staff_view] == ["Asha", "Ravi"]

    # Move Ravi up, then notify Asha with T2 held, then seat her.
    moved = await client.post(f"{B}/queue/{walk_in.json()['id']}/move", json={"direction": "up"}, headers=h)
    assert [e["guest_name"] for e in moved.json()] == ["Ravi", "Asha"]
    n = await client.post(f"{B}/queue/{e1['id']}/notify", json={"table_id": tables["T2"]["id"]}, headers=h)
    assert n.status_code == 200 and n.json()["status"] == "notified" and n.json()["notified_table_label"] == "T2"
    t2 = next(
        t
        for t in (await client.get(f"{B}/tables", params={"branch_id": branch["id"]}, headers=h)).json()
        if t["label"] == "T2"
    )
    assert t2["status"] == "reserved"  # held for Asha (yellow on the board)

    mine = (await client.get(f"/api/v1/me/queue/{e1['id']}", headers=g1)).json()
    assert mine["status"] == "notified" and mine["restaurant_slug"] == slug
    other = await client.get(f"/api/v1/me/queue/{e1['id']}", headers=g2)
    assert other.status_code == 404  # only the guest sees their own token

    seated = await client.post(f"{B}/queue/{e1['id']}/seat", json={"table_id": tables["T2"]["id"]}, headers=h)
    assert seated.status_code == 200, seated.text
    assert seated.json()["session"]["source"] == "queue" and len(seated.json()["pin"]) == 4

    left = await client.post(f"{B}/queue/{walk_in.json()['id']}/no-show", headers=h)
    assert left.json()["status"] == "no_show"
    history = (await client.get(f"{B}/queue", params={"branch_id": branch["id"], "history": True}, headers=h)).json()
    assert {e["status"] for e in history} == {"seated", "no_show"}

    # A guest can leave by themselves.
    e2 = (await client.post(f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 2}, headers=g2)).json()
    gone = await client.post(f"/api/v1/me/queue/{e2['id']}/leave", headers=g2)
    assert gone.json()["status"] == "cancelled"
    mine_all = (await client.get("/api/v1/me/bookings", headers=g2)).json()
    assert [q["id"] for q in mine_all["queue"]] == [e2["id"]]


async def test_queue_closed_by_policy(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    r = await client.put(
        f"{B}/branches/{branch['id']}/booking-policy", json={**policy, "accepts_queue": False}, headers=h
    )
    assert r.status_code == 200 and r.json()["accepts_queue"] is False
    g = await _otp_login(client)
    closed = await client.post(
        f"{P}/{tenant['slug']}/queue", json={"branch_id": branch["id"], "party_size": 2}, headers=g
    )
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "QUEUE_CLOSED"
    bad = await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "0"},
        headers=h,
    )
    assert bad.status_code == 422


# ---------- reservations ----------


async def test_free_booking_arrive_and_complete(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    slug = tenant["slug"]
    day = _tomorrow_at(19).date().isoformat()

    opts = (await client.get(f"{P}/{slug}/booking-options")).json()
    assert opts[0]["accepts_reservations"] is True and opts[0]["free_enabled"] is True
    av = (
        await client.get(f"{P}/{slug}/availability", params={"branch_id": branch["id"], "date": day, "party": 2})
    ).json()
    labels = [s["label"] for s in av["slots"]]
    assert "19:00" in labels and "19:30" in labels and all(s["available"] for s in av["slots"])

    guest = await _otp_login(client)
    r = await _book(client, slug, guest, branch, _tomorrow_at(19), notes="Window please")
    assert r.status_code == 201, r.text
    res = r.json()["reservation"]
    assert res["status"] == "confirmed" and res["type"] == "free" and res["table_labels"] == ["T2"]  # smallest fit
    assert r.json()["payment"] is None and res["can_cancel"] is True

    dup = await _book(client, slug, guest, branch, _tomorrow_at(19, 30))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_BOOKING"
    odd = await _book(client, slug, await _otp_login(client), branch, _tomorrow_at(19, 10))
    assert odd.status_code == 422 and odd.json()["error"]["code"] == "INVALID_SLOT"

    day_list = (
        await client.get(f"{B}/reservations", params={"branch_id": branch["id"], "date": day}, headers=h)
    ).json()
    assert [x["code"] for x in day_list] == [res["code"]]

    # Arrival is only possible for confirmed bookings; it seats on the held table.
    seated = await client.post(f"{B}/reservations/{res['id']}/arrive", json={}, headers=h)
    assert seated.status_code == 200, seated.text
    assert seated.json()["session"]["source"] == "reservation"
    again = await client.post(f"{B}/reservations/{res['id']}/arrive", json={}, headers=h)
    assert again.status_code == 409
    after = (await client.get(f"/api/v1/me/reservations/{res['id']}", headers=guest)).json()
    assert after["status"] == "checked_in" and after["staff_confirmed_at"] is not None

    closed = await client.post(f"{B}/table-sessions/{seated.json()['session']['id']}/close", headers=h)
    assert closed.status_code == 200
    done = (await client.get(f"/api/v1/me/reservations/{res['id']}", headers=guest)).json()
    assert done["status"] == "completed" and done["end_reason"] == "guests_left"


async def test_no_double_booking_even_concurrently(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    slug = tenant["slug"]
    # Only one table can seat 4 (T1). Two parties of 4 race for the same time: exactly one wins.
    g1, g2 = await _otp_login(client), await _otp_login(client)
    when = _tomorrow_at(20)
    r1, r2 = await asyncio.gather(
        _book(client, slug, g1, branch, when, party=4), _book(client, slug, g2, branch, when, party=4)
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["error"]["code"] == "SLOT_TAKEN"

    # Overlapping time (inside the 90-minute dining window) is also taken; after it ends it is free.
    g3 = await _otp_login(client)
    assert (await _book(client, slug, g3, branch, _tomorrow_at(21), party=4)).status_code == 409
    assert (await _book(client, slug, g3, branch, _tomorrow_at(21, 30), party=4)).status_code == 201
    av = (
        await client.get(
            f"{P}/{slug}/availability",
            params={"branch_id": branch["id"], "date": when.date().isoformat(), "party": 4},
        )
    ).json()
    by_label = {s["label"]: s["available"] for s in av["slots"]}
    assert by_label["20:00"] is False and by_label["18:30"] is True and by_label["23:00"] is True


async def test_paid_booking_webhook_flow(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    slug = tenant["slug"]
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    r = await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "500", "free_cancel_hours": 2},
        headers=h,
    )
    assert r.status_code == 200, r.text

    guest = await _otp_login(client)
    booked = await _book(client, slug, guest, branch, _tomorrow_at(13), type="paid")
    assert booked.status_code == 201, booked.text
    res, pay = booked.json()["reservation"], booked.json()["payment"]
    assert res["status"] == "pending_payment" and res["payment_due_at"] and Decimal(pay["amount"]) == Decimal("500")
    assert pay["checkout"]["url"] == f"/pay/mock/{pay['order_id']}"

    raw, sig = MockGateway.build_event(pay["order_id"], Decimal("500"), True)
    forged = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": "0" * 64})
    assert forged.status_code == 400 and forged.json()["error"]["code"] == "INVALID_SIGNATURE"
    still = (await client.get(f"/api/v1/me/reservations/{res['id']}", headers=guest)).json()
    assert still["status"] == "pending_payment"  # the browser can never confirm a booking by itself

    ok = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert ok.status_code == 200 and ok.json()["result"] == "confirmed"
    dup = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert dup.json()["result"] == "already_processed"  # idempotent
    paid = (await client.get(f"/api/v1/me/reservations/{res['id']}", headers=guest)).json()
    assert paid["status"] == "confirmed" and paid["payment_status"] == "captured" and paid["can_preorder"] is True

    # Cancelling well ahead (more than 2 h) refunds the fee.
    cancelled = await client.post(f"/api/v1/me/reservations/{res['id']}/cancel", headers=guest)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["payment_status"] == "refunded"
    assert Decimal(cancelled.json()["refunded_amount"]) == Decimal("500")

    # Mock checkout page path (dev only): pay through the same verified webhook code.
    b2 = (await _book(client, slug, guest, branch, _tomorrow_at(16), type="paid")).json()
    order = await client.get(f"/api/v1/public/payments/mock/{b2['payment']['order_id']}", headers=guest)
    assert order.status_code == 200 and order.json()["reservation_code"] == b2["reservation"]["code"]
    stranger = await client.get(
        f"/api/v1/public/payments/mock/{b2['payment']['order_id']}", headers=await _otp_login(client)
    )
    assert stranger.status_code == 404
    done = await client.post(
        f"/api/v1/public/payments/mock/{b2['payment']['order_id']}", json={"success": True}, headers=guest
    )
    assert done.json()["result"] == "confirmed"

    # Restaurant cancels a paid booking → full refund.
    staff_cancel = await client.post(f"{B}/reservations/{b2['reservation']['id']}/cancel", headers=h)
    assert staff_cancel.json()["payment_status"] == "refunded"


async def test_expiry_job_never_touches_checked_in(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client)
    slug = tenant["slug"]
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "300"},
        headers=h,
    )
    g1, g2, g3 = await _otp_login(client), await _otp_login(client), await _otp_login(client)
    unpaid = (await _book(client, slug, g1, branch, _tomorrow_at(12), type="paid")).json()["reservation"]
    no_arrival = (await _book(client, slug, g2, branch, _tomorrow_at(12), party=4)).json()["reservation"]
    arrived = (await _book(client, slug, g3, branch, _tomorrow_at(14), party=2)).json()["reservation"]
    assert (await client.post(f"{B}/reservations/{arrived['id']}/arrive", json={}, headers=h)).status_code == 200

    # Half an hour before 12:00 the job holds T1 as "reserved" on the floor board.
    async with get_sessionmaker()() as s:
        counts = await res_svc.tick(s, now=_tomorrow_at(11, 35).astimezone(UTC))
    assert counts["payment_expired"] == 1 and counts["tables_reserved"] >= 1
    async with get_sessionmaker()() as s:
        await use_system(s)
        t1 = (
            await s.execute(
                select(RestaurantTable).where(RestaurantTable.label == "T1", RestaurantTable.branch_id == branch["id"])
            )
        ).scalar_one()
        assert t1.status == "reserved"

    # A day later: the no-arrival booking expires and frees T1; the checked-in one is untouched.
    async with get_sessionmaker()() as s:
        counts = await res_svc.tick(s, now=_tomorrow_at(23).astimezone(UTC))
    assert counts["no_arrival_expired"] == 1
    states = {}
    for guest, r in ((g1, unpaid), (g2, no_arrival), (g3, arrived)):
        states[r["id"]] = (await client.get(f"/api/v1/me/reservations/{r['id']}", headers=guest)).json()
    assert states[unpaid["id"]]["status"] == "expired" and states[unpaid["id"]]["end_reason"] == "payment_timeout"
    assert states[no_arrival["id"]]["status"] == "expired" and states[no_arrival["id"]]["end_reason"] == "no_arrival"
    assert states[arrived["id"]]["status"] == "checked_in"
    async with get_sessionmaker()() as s:
        await use_system(s)
        t1 = (
            await s.execute(
                select(RestaurantTable).where(RestaurantTable.label == "T1", RestaurantTable.branch_id == branch["id"])
            )
        ).scalar_one()
        assert t1.status == "available"

    # A payment arriving after expiry is refunded automatically.
    async with get_sessionmaker()() as s:
        await use_system(s)
        order_id = (
            await s.execute(
                select(ReservationPayment.provider_order_id).where(ReservationPayment.reservation_id == unpaid["id"])
            )
        ).scalar_one()
    raw, sig = MockGateway.build_event(order_id, Decimal("300"), True)
    late = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert late.json()["result"] == "refunded_late_payment"
    async with get_sessionmaker()() as s:
        await use_system(s)
        assert (await s.get(Reservation, unpaid["id"])).status == "expired"  # type: ignore[union-attr]


async def test_booking_isolation_between_restaurants(client: httpx.AsyncClient) -> None:
    tenant_a, h_a, branch_a, _ = await _setup(client, "Alpha Diner")
    _tenant_b, h_b, branch_b, _ = await _setup(client, "Beta Diner")
    guest = await _otp_login(client)
    res = (await _book(client, tenant_a["slug"], guest, branch_a, _tomorrow_at(18))).json()["reservation"]

    # Restaurant B cannot list, see or act on A's bookings or branches.
    assert (await client.get(f"{B}/reservations", params={"branch_id": branch_a["id"]}, headers=h_b)).status_code == 404
    assert (await client.post(f"{B}/reservations/{res['id']}/cancel", headers=h_b)).status_code == 404
    assert (await client.get(f"{B}/branches/{branch_a['id']}/booking-policy", headers=h_b)).status_code == 404
    assert (await client.get(f"{B}/reservations", params={"branch_id": branch_b["id"]}, headers=h_b)).json() == []
    # Booking A's branch through B's storefront is impossible.
    wrong = await _book(client, _tenant_b["slug"], await _otp_login(client), branch_a, _tomorrow_at(18))
    assert wrong.status_code == 404
    # Another guest cannot see or cancel it.
    other = await _otp_login(client)
    assert (await client.get(f"/api/v1/me/reservations/{res['id']}", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/me/reservations/{res['id']}/cancel", headers=other)).status_code == 404
    mine = (await client.get("/api/v1/me/bookings", headers=guest)).json()
    assert [r["restaurant_name"] for r in mine["reservations"]] == ["Alpha Diner"]

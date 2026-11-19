"""'Join the queue' with free tables: the guest is seated at once when a table suits the party
(capacity −1 … +2 guests) and nobody already waiting fits it; the waiters get an alert (extra chairs)."""

import httpx
import pytest

from tests.integration.test_bookings import B, P, _otp_login, _setup

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]


async def _join(client: httpx.AsyncClient, slug: str, branch: dict, guest: dict, party: int, name: str) -> dict:
    r = await client.post(
        f"{P}/{slug}/queue",
        json={"branch_id": branch["id"], "party_size": party, "guest_name": name, "seat_now": True},
        headers=guest,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_seated_directly_when_a_table_suits(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client, "Seat Now Cafe")  # T1 · 4 seats, T2 · 2 seats
    slug = tenant["slug"]

    # 6 guests, no 6-seat table: T1 (4 seats) suits with 2 extra chairs.
    big = await _join(client, slug, branch, await _otp_login(client), 6, "Meera")
    assert big["status"] == "seated" and big["position"] == 0
    s = big["seated_now"]
    assert s["table_label"] == "T1" and s["capacity"] == 4 and s["extra_chairs"] == 2
    assert len(s["pin"]) == 4 and s["code"]

    # The table token works at once: the guest can order and call the waiter (no cooldown from the alert).
    view = await client.get("/api/v1/table-session", headers={"X-Table-Token": s["token"]})
    assert view.status_code == 200 and view.json()["code"] == s["code"]
    calls = (await client.get("/api/v1/table-session/calls", headers={"X-Table-Token": s["token"]})).json()
    assert calls["cooldown_until"] is None and calls["open"] == []

    # Waiters get an alert with the chairs to add; the table is occupied.
    alerts = (await client.get(f"{B}/service-calls", params={"branch_id": branch["id"]}, headers=h)).json()
    seat = next(a for a in alerts if a["kind"] == "seat")
    assert seat["table_labels"] == "T1" and "add 2 chairs" in seat["note"] and seat["guest_name"] == "Meera"
    board = {
        t["label"]: t for t in (await client.get(f"{B}/tables", params={"branch_id": branch["id"]}, headers=h)).json()
    }
    assert board["T1"]["status"] == "occupied"
    done = await client.post(f"{B}/service-calls/{seat['id']}/done", headers=h)
    assert done.status_code == 200 and done.json()["status"] == "done"

    # 1 guest: T2 (2 seats) suits (one fewer than its seats).
    solo = await _join(client, slug, branch, await _otp_login(client), 1, "Kiran")
    assert solo["seated_now"]["table_label"] == "T2" and solo["seated_now"]["extra_chairs"] == 0

    # No free table now → a normal token.
    g3 = await _otp_login(client)
    waiting = await _join(client, slug, branch, g3, 2, "Asha")
    assert waiting["status"] == "waiting" and waiting["seated_now"] is None and waiting["position"] == 1

    # A new 2-seat table frees up: Asha (already waiting, fits it) goes first — the newcomer queues.
    await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": "T3", "capacity": 2}, headers=h)
    later = await _join(client, slug, branch, await _otp_login(client), 2, "Dev")
    assert later["status"] == "waiting" and later["position"] == 2

    # Staff history shows the directly seated guests.
    history = (await client.get(f"{B}/queue", params={"branch_id": branch["id"], "history": True}, headers=h)).json()
    assert {e["guest_name"] for e in history if e["status"] == "seated"} == {"Meera", "Kiran"}


async def test_too_small_party_or_self_seating_off_joins_the_line(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client, "Queue Only Diner")  # T1 · 4 seats, T2 · 2 seats
    slug = tenant["slug"]

    # Party of 7: no table suits even with chairs (4 + 2 = 6) → the usual "too large".
    r = await client.post(
        f"{P}/{slug}/queue",
        json={"branch_id": branch["id"], "party_size": 7, "seat_now": True},
        headers=await _otp_login(client),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "PARTY_TOO_LARGE"

    # The restaurant seats every guest itself → a token even though T1 is free.
    off = await client.put(f"{B}/table-qr/self-seating", json={"enabled": False}, headers=h)
    assert off.status_code == 200
    e = await _join(client, slug, branch, await _otp_login(client), 4, "Rohan")
    assert e["status"] == "waiting" and e["seated_now"] is None

    # Without seat_now the old behaviour stays (a token).
    await client.put(f"{B}/table-qr/self-seating", json={"enabled": True}, headers=h)
    plain = await client.post(
        f"{P}/{slug}/queue", json={"branch_id": branch["id"], "party_size": 2}, headers=await _otp_login(client)
    )
    assert plain.status_code == 201 and plain.json()["status"] == "waiting"


async def test_one_guest_cannot_keep_grabbing_tables(client: httpx.AsyncClient) -> None:
    tenant, h, branch, _ = await _setup(client, "Many Tables Bar")  # T1 · 4 seats, T2 · 2 seats
    for label in ("T3", "T4", "T5"):
        await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": label, "capacity": 2}, headers=h)
    guest = await _otp_login(client)
    got = [(await _join(client, tenant["slug"], branch, guest, 2, "Sam"))["status"] for _ in range(4)]
    # Three tables an hour from the same guest; then a normal token (staff decide) instead of an error.
    assert got == ["seated", "seated", "seated", "waiting"]

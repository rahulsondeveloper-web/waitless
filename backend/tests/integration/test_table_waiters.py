"""Waiter in charge of each table: one waiter per table, a waiter can look after many tables."""

import httpx
import pytest

from tests.conftest import bearer, random_mobile
from tests.integration.test_operations import B, _floor, _owner, _roles, _second_branch

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]


async def _invite(client: httpx.AsyncClient, h: dict, role_id: str, branch_id: str, name: str) -> dict:
    r = await client.post(
        f"{B}/staff",
        json={"full_name": name, "phone": random_mobile(), "role_id": role_id, "branch_ids": [branch_id]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_assign_waiters_to_tables(client: httpx.AsyncClient) -> None:
    _, h, _ = await _owner(client)
    branch, t1, t2 = await _floor(client, h)
    other = await _second_branch(client, h)
    roles = await _roles(client, h)
    rohan = await _invite(client, h, roles["waiter"]["id"], branch["id"], "Rohan Waiter")
    elsewhere = await _invite(client, h, roles["waiter"]["id"], other["id"], "Other Branch Waiter")
    cook = await _invite(client, h, roles["kitchen"]["id"], branch["id"], "Kitchen Person")

    options = (await client.get(f"{B}/tables/waiters", params={"branch_id": branch["id"]}, headers=h)).json()
    ids = [o["user_id"] for o in options]
    assert rohan["user_id"] in ids and ids[0] == rohan["user_id"]  # waiters listed first
    assert elsewhere["user_id"] not in ids and cook["user_id"] not in ids

    # One waiter, two tables.
    for t in (t1, t2):
        r = await client.patch(f"{B}/tables/{t['id']}", json={"waiter_user_id": rohan["user_id"]}, headers=h)
        assert r.status_code == 200 and r.json()["waiter_user_id"] == rohan["user_id"], r.text
    board = (await client.get(f"{B}/tables/board", params={"branch_id": branch["id"]}, headers=h)).json()
    assert {t["label"]: t["waiter_name"] for t in board["tables"]} == {"T1": "Rohan Waiter", "T2": "Rohan Waiter"}
    options = (await client.get(f"{B}/tables/waiters", params={"branch_id": branch["id"]}, headers=h)).json()
    assert next(o for o in options if o["user_id"] == rohan["user_id"])["table_labels"] == ["T1", "T2"]

    # Not allowed: kitchen staff, a waiter of another branch.
    for bad in (cook, elsewhere):
        r = await client.patch(f"{B}/tables/{t1['id']}", json={"waiter_user_id": bad["user_id"]}, headers=h)
        assert r.status_code == 422 and r.json()["error"]["code"] == "WAITER_NOT_ELIGIBLE"

    # Other edits keep the waiter; null removes it.
    r = await client.patch(f"{B}/tables/{t1['id']}", json={"capacity": 6}, headers=h)
    assert r.json()["waiter_user_id"] == rohan["user_id"]
    r = await client.patch(f"{B}/tables/{t1['id']}", json={"waiter_user_id": None}, headers=h)
    assert r.json()["waiter_user_id"] is None

    # Disabling the waiter frees their tables.
    await client.patch(f"{B}/staff/{rohan['membership_id']}", json={"status": "disabled"}, headers=h)
    tables = (await client.get(f"{B}/tables", params={"branch_id": branch["id"]}, headers=h)).json()
    assert all(t["waiter_user_id"] is None for t in tables)


async def test_only_table_configurers_assign_waiters(client: httpx.AsyncClient) -> None:
    from tests.integration.test_operations import _otp_login

    _, h, _ = await _owner(client)
    branch, t1, _ = await _floor(client, h)
    roles = await _roles(client, h)
    mobile = random_mobile()
    r = await client.post(
        f"{B}/staff",
        json={"full_name": "Wanda", "phone": mobile, "role_id": roles["waiter"]["id"], "branch_ids": [branch["id"]]},
        headers=h,
    )
    me = r.json()
    wh = bearer(await _otp_login(client, mobile))
    r = await client.patch(f"{B}/tables/{t1['id']}", json={"waiter_user_id": me["user_id"]}, headers=wh)
    assert r.status_code == 403
    assert (await client.get(f"{B}/tables/waiters", params={"branch_id": branch["id"]}, headers=wh)).status_code == 403

"""WaitLess load test (Phase 12): storefront browsing and table ordering.

    cd backend
    .venv\\Scripts\\locust -f ..\\loadtest\\locustfile.py --host http://127.0.0.1:8000 \\
        --headless -u 40 -r 10 -t 2m --csv ..\\loadtest\\results\\run

Uses the e2e copy of the demo restaurant (seeded by `python -m app.cli seed-demo --e2e`), so real data is never
touched. At start it signs in once as the owner, seats guests at the free tables and joins each table once
(join attempts are rate limited per IP), then:

- StorefrontVisitor (most users): discovery list, storefront, menu, website content.
- TableGuest: places an order every few seconds with its table token and polls its table page.
- KitchenScreen: polls the active orders like the kitchen display does.

Afterwards run `seed-demo --e2e` again to free the tables.
"""

import itertools
import os
import random
import threading
import uuid

from locust import HttpUser, between, events, task

SLUG = os.environ.get("WL_SLUG", "e2e-urban-bites")
OWNER = os.environ.get("WL_OWNER", "e2e.owner@urbanbites.example.com")
PASSWORD = os.environ.get("WL_PASSWORD", "Demo-pass-123")
API = "/api/v1"

_state: dict = {"tokens": [], "dishes": [], "owner": None, "branch": None}
_lock = threading.Lock()
_cycle = None


@events.test_start.add_listener
def _prepare(environment, **_kw) -> None:  # type: ignore[no-untyped-def]
    """Seat guests at every free table once and keep their table tokens."""
    import requests

    host = environment.host.rstrip("/")
    r = requests.post(f"{host}{API}/auth/login", json={"identifier": OWNER, "password": PASSWORD}, timeout=20)
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = requests.get(f"{host}{API}/restaurant/me", headers=headers, timeout=20).json()
    branch = next((b for b in me["branches"] if b["is_primary"]), me["branches"][0])
    board = requests.get(f"{host}{API}/restaurant/tables/board", params={"branch_id": branch["id"]}, headers=headers, timeout=20).json()
    menu = requests.get(f"{host}{API}/public/restaurants/{SLUG}/menu", timeout=20).json()
    _state["dishes"] = [
        i["id"]
        for c in menu["categories"]
        for i in c["items"]
        if i["is_available"] and not i["variants"] and not i["availability"] and not i["addon_groups"]
    ]
    for t in [t for t in board["tables"] if t["status"] == "available"][:20]:
        s = requests.post(
            f"{host}{API}/restaurant/table-sessions",
            json={"table_id": t["id"], "party_size": 2, "guest_name": "Load test"},
            headers=headers,
            timeout=20,
        )
        if s.status_code != 201:
            continue
        seated = s.json()
        j = requests.post(
            f"{host}{API}/public/restaurants/{SLUG}/table-sessions/join",
            json={"code": seated["session"]["public_code"], "pin": seated["pin"]},
            timeout=20,
        )
        if j.ok:
            _state["tokens"].append(j.json()["token"])
    _state["owner"], _state["branch"] = headers, branch["id"]
    global _cycle
    _cycle = itertools.cycle(_state["tokens"]) if _state["tokens"] else None
    print(f"prepared {len(_state['tokens'])} tables, {len(_state['dishes'])} dishes")


class StorefrontVisitor(HttpUser):
    weight = 6
    wait_time = between(1, 3)

    @task(3)
    def discover(self) -> None:
        self.client.get(f"{API}/public/restaurants", params={"q": random.choice(["", "pizza", "cafe", "pune"])}, name="discover")

    @task(4)
    def storefront(self) -> None:
        self.client.get(f"{API}/public/restaurants/{SLUG}", name="storefront")
        self.client.get(f"{API}/public/restaurants/{SLUG}/menu", name="menu")

    @task(1)
    def website(self) -> None:
        self.client.get(f"{API}/public/content", name="content")


class TableGuest(HttpUser):
    weight = 3
    wait_time = between(3, 8)

    def on_start(self) -> None:
        with _lock:
            self.token = next(_cycle) if _cycle else None

    @task(1)
    def order(self) -> None:
        if not self.token or not _state["dishes"]:
            return
        lines = [{"menu_item_id": random.choice(_state["dishes"]), "quantity": random.randint(1, 3)} for _ in range(random.randint(1, 3))]
        self.client.post(
            f"{API}/table-session/orders",
            json={"items": lines},
            headers={"X-Table-Token": self.token, "Idempotency-Key": uuid.uuid4().hex},
            name="place order",
        )

    @task(3)
    def follow(self) -> None:
        if self.token:
            self.client.get(f"{API}/table-session", headers={"X-Table-Token": self.token}, name="table page")


class KitchenScreen(HttpUser):
    weight = 1
    wait_time = between(4, 6)

    @task
    def tickets(self) -> None:
        if _state["owner"]:
            self.client.get(
                f"{API}/restaurant/orders",
                params={"branch_id": _state["branch"], "active": "true"},
                headers=_state["owner"],
                name="kitchen tickets",
            )

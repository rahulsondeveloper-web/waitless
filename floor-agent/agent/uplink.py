"""Talks to WaitLess: pairing, the branch's tables, and sending "guests seated / left" events.

Events wait in a small file (`config/outbox.json`) until WaitLess confirms them, so a dropped internet connection or
a restart of the laptop loses nothing. Every event has its own ID, so sending one twice (the reply got lost) is
harmless: WaitLess recognises it and does nothing the second time.
"""

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

BATCH = 25


def pair(server: str, code: str, config_path: str | Path) -> dict:
    """Swap the owner's one-time code for this laptop's key and remember it."""
    r = httpx.post(f"{server.rstrip('/')}/api/v1/agent/pair", json={"code": code}, timeout=15)
    if r.status_code != 200:
        message = r.json().get("error", {}).get("message", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
        raise SystemExit(f"Pairing failed: {message}")
    data = r.json()
    Path(config_path).write_text(
        json.dumps({"server": server.rstrip("/"), "agent_key": data["agent_key"], "agent": data["agent"]}, indent=2),
        encoding="utf-8",
    )
    return data


class Uplink:
    def __init__(self, config_path: str | Path, outbox_path: str | Path = "config/outbox.json") -> None:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.server, self.key = cfg["server"], cfg["agent_key"]
        self.outbox = Path(outbox_path)
        self.pending: list[dict] = json.loads(self.outbox.read_text()) if self.outbox.exists() else []
        self.sent = 0
        self.paused_reason: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._http = httpx.Client(base_url=f"{self.server}/api/v1/agent", headers={"X-Agent-Key": self.key}, timeout=15)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- what the engine calls ----
    def tables(self) -> list[dict]:
        r = self._http.get("/tables")
        r.raise_for_status()
        return r.json()

    def enqueue(self, kind: str, table: str, guests: int = 1, at: datetime | None = None) -> str:
        event = {
            "event_id": str(uuid.uuid4()),
            "kind": kind,
            "table": table,
            "at": (at or datetime.now(UTC)).isoformat(),
            "guests": max(1, min(int(guests or 1), 100)),
        }
        with self._lock:
            self.pending.append(event)
            self._save()
        return event["event_id"]

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._http.close()

    # ---- background ----
    def _save(self) -> None:
        self.outbox.write_text(json.dumps(self.pending), encoding="utf-8")

    def _run(self) -> None:
        wait, beat = 1.0, 0.0
        while not self._stop.is_set():
            try:
                if time.monotonic() - beat > 30:
                    self._http.post("/heartbeat")
                    beat = time.monotonic()
                with self._lock:
                    batch = list(self.pending[:BATCH])
                if batch:
                    r = self._http.post("/events", json={"events": batch})
                    if r.status_code == 401:  # disconnected by the owner: keep the events, stop trying
                        self.paused_reason = "This laptop was disconnected in WaitLess. Pair it again."
                        print(f"[uplink] {self.paused_reason}", flush=True)
                        return
                    r.raise_for_status()
                    done = {x["event_id"]: x["status"] for x in r.json()["results"]}
                    with self._lock:
                        self.pending = [e for e in self.pending if e["event_id"] not in done]
                        self._save()
                    self.sent += len(done)
                    for e in batch:
                        print(f"[uplink] {e['kind']:<6} {e['table']:<4} -> WaitLess: {done.get(e['event_id'], '?')}", flush=True)
                wait = 1.0
            except (httpx.HTTPError, OSError) as exc:
                wait = min(wait * 2, 30.0)  # offline or server busy: events stay in the file, try again later
                print(f"[uplink] cannot reach WaitLess ({type(exc).__name__}); {len(self.pending)} waiting, retry in {wait:.0f}s", flush=True)
            self._stop.wait(wait if self.pending else 1.0)

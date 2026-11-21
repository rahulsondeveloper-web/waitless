"""Turns tracked people into table events: guests seated, guests left, waiter at the table.

Times are in seconds on the clock of the feed. Production defaults are slow on purpose (a guest must stay 30 s to
count as seated, and the table must be empty for 2 minutes to count as left); tests on short clips pass smaller ones.
"""

from collections import deque
from dataclasses import dataclass, field

from agent.tracker import Track
from agent.zones import Zone


@dataclass
class Settings:
    seat_after: float = 30.0  # guests must stay this long before the table counts as occupied
    leave_after: float = 120.0  # no guests for this long before the table counts as free again
    visit_after: float = 10.0  # a waiter must stay at the table this long to count as a visit
    visit_gap: float = 2.0  # waiter out of reach this long ends the visit
    reach: float = 45.0  # how far outside the table shape (pixels) a waiter's feet may be and still be "at the table"
    still: float = 30.0  # a waiter serving a table is nearly still: slower than this many pixels per second
    sit_confirm: float = 8.0  # someone in uniform colours must sit this long (s) before they count as a guest
    count_window: float = 20.0  # guests in the last seconds: the highest count wins (people hide each other)


@dataclass
class Event:
    t: float
    kind: str  # seated | left | visit_started | visit_ended
    table: str
    text: str
    notify: str | None = None  # who gets told: the waiter in charge of the table
    guests: int = 1

    def __str__(self) -> str:
        who = f"  -> notify {self.notify}" if self.notify else ""
        return f"[{self.t:6.1f}s] {self.kind:<13} {self.table}  {self.text}{who}"


@dataclass
class Table:
    zone: Zone
    status: str = "free"  # free | occupied
    guests: int = 0
    seated_at: float | None = None
    since: float | None = None  # guests first seen (candidate) / table first empty (while occupied)
    counts: deque = field(default_factory=deque)  # (time, guests seen)
    visitor: int | None = None  # staff track at the table now
    visit_start: float | None = None
    visit_confirmed: bool = False
    gone_since: float | None = None
    visits: int = 0
    first_visit_delay: float | None = None
    delay_from_this_visit: bool = False


class Engine:
    def __init__(self, zones: list[Zone], settings: Settings | None = None) -> None:
        self.s = settings or Settings()
        self.tables = {z.label: Table(z) for z in zones}
        self.events: list[Event] = []

    # ---- helpers ----
    def _emit(self, ev: Event) -> None:
        self.events.append(ev)
        print(ev, flush=True)

    @property
    def occupied(self) -> int:
        return sum(t.status == "occupied" for t in self.tables.values())

    @property
    def seated_guests(self) -> int:
        return sum(t.guests for t in self.tables.values() if t.status == "occupied")

    @property
    def capacity(self) -> int:
        return sum(t.zone.seats for t in self.tables.values())

    def _retract(self, tb: Table, t: float) -> None:
        if tb.visit_confirmed:
            tb.visits = max(0, tb.visits - 1)
            if tb.delay_from_this_visit:
                tb.first_visit_delay = None
            self._emit(Event(t, "visit_retracted", tb.zone.label, "that person sat down - a guest, not a waiter"))
        tb.visitor, tb.visit_start, tb.visit_confirmed, tb.gone_since, tb.delay_from_this_visit = None, None, False, None, False

    def _at_table(self, zone: Zone, foot: tuple[float, float]) -> bool:
        """Beside or in front of the table. Not above it: that is where the counter and kitchen usually are."""
        x1, y1, x2, y2 = zone.bbox
        r = self.s.reach
        return x1 - r <= foot[0] <= x2 + r and y1 <= foot[1] <= y2 + r

    # ---- main step ----
    def update(self, tracks: list[Track], t: float) -> None:
        for tr in tracks:  # someone who sits long enough is a guest for good, even in dark clothes
            if tr.seated_for(t) >= self.s.sit_confirm:
                tr.guest_locked = True
        by_id = {tr.id: tr for tr in tracks}
        for tb in self.tables.values():  # "the waiter" who then sits down was a guest after all
            who = by_id.get(tb.visitor) if tb.visitor is not None else None
            if who is not None and who.guest_locked:
                self._retract(tb, t)
        guests = [tr for tr in tracks if tr.confirmed and tr.seated_now and not tr.is_staff]
        staff = [tr for tr in tracks if tr.confirmed and tr.is_staff and not tr.seated_now and tr.speed(t) < self.s.still]
        for tb in self.tables.values():
            self._guests(tb, [g for g in guests if tb.zone.contains(g.hip, 10)], t)
            # A visit is a waiter stopping at a table that has guests; walking past empty tables is not service.
            near = [w for w in staff if self._at_table(tb.zone, w.foot)] if tb.status == "occupied" else []
            self._visits(tb, near, t)

    def _guests(self, tb: Table, here: list[Track], t: float) -> None:
        tb.counts.append((t, len(here)))
        while tb.counts and t - tb.counts[0][0] > self.s.count_window:
            tb.counts.popleft()
        recent = max((n for _, n in tb.counts), default=0)
        who = tb.zone.waiter
        if tb.status == "free":
            if here:
                tb.since = tb.since if tb.since is not None else t
                if t - tb.since >= self.s.seat_after:
                    tb.status, tb.seated_at, tb.guests, tb.since = "occupied", tb.since, recent, None
                    tb.visits, tb.first_visit_delay = 0, None
                    self._emit(Event(t, "seated", tb.zone.label, f"{recent} guest(s) sat down", who, recent))
            else:
                tb.since = None
        else:
            if here:  # somebody is sitting there right now
                tb.guests = recent  # the count uses the highest number seen lately (people hide each other)
                tb.since = None
            else:  # nobody now: the table is free once that has lasted long enough
                tb.since = tb.since if tb.since is not None else t
                if t - tb.since >= self.s.leave_after:
                    stay = t - (tb.seated_at or t)
                    self._emit(Event(t, "left", tb.zone.label, f"guests left after {stay:.0f}s - table is free", who))
                    tb.status, tb.guests, tb.seated_at, tb.since = "free", 0, None, None

    def _visits(self, tb: Table, near: list[Track], t: float) -> None:
        if near:
            tb.gone_since = None
            if tb.visitor is None:
                tb.visitor, tb.visit_start, tb.visit_confirmed = near[0].id, t, False
            if not tb.visit_confirmed and t - (tb.visit_start or t) >= self.s.visit_after:
                tb.visit_confirmed = True
                tb.visits += 1
                note = ""
                if tb.status == "occupied" and tb.seated_at is not None and tb.first_visit_delay is None:
                    tb.first_visit_delay = (tb.visit_start or t) - tb.seated_at
                    tb.delay_from_this_visit = True
                    note = f" - first visit {tb.first_visit_delay:.0f}s after the guests sat"
                self._emit(Event(t, "visit_started", tb.zone.label, f"waiter at the table{note}"))
        elif tb.visitor is not None:
            tb.gone_since = tb.gone_since if tb.gone_since is not None else t
            if t - tb.gone_since >= self.s.visit_gap:
                if tb.visit_confirmed:
                    stayed = tb.gone_since - (tb.visit_start or t)
                    self._emit(Event(t, "visit_ended", tb.zone.label, f"waiter left after {stayed:.0f}s"))
                tb.visitor, tb.visit_start, tb.visit_confirmed, tb.gone_since = None, None, False, None

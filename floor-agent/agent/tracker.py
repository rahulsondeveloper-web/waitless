"""Keeps one ID per person from one sampled frame to the next (greedy overlap + distance matching)."""

from collections import deque
from dataclasses import dataclass, field

from agent.detector import Detection


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


@dataclass
class Track:
    id: int
    box: tuple[int, int, int, int]
    first_t: float
    last_t: float
    hits: int = 1
    dark: deque = field(default_factory=lambda: deque(maxlen=12))  # uniform-colour votes, taken while standing
    seated_votes: deque = field(default_factory=lambda: deque(maxlen=3))
    seated_since: float | None = None  # start of the current unbroken sitting
    guest_locked: bool = False  # sat for a while: a guest for good, whatever they wear
    path: deque = field(default_factory=lambda: deque(maxlen=40))  # (time, foot x, foot y)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)

    @property
    def foot(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, float(self.box[3]))

    @property
    def hip(self) -> tuple[float, float]:
        """Where a seated person's body is: below the head, above the (hidden) legs."""
        return ((self.box[0] + self.box[2]) / 2, self.box[1] + 0.7 * self.height)

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]

    @property
    def confirmed(self) -> bool:
        return self.hits >= 2

    @property
    def seated_now(self) -> bool:
        return len(self.seated_votes) >= 2 and sum(self.seated_votes) / len(self.seated_votes) >= 0.6

    @property
    def uniform(self) -> bool:
        return len(self.dark) >= 3 and sum(self.dark) / len(self.dark) >= 0.7

    @property
    def is_staff(self) -> bool:
        return self.uniform and not self.guest_locked

    def seated_for(self, t: float) -> float:
        return 0.0 if self.seated_since is None else t - self.seated_since

    def speed(self, t: float, window: float = 1.2) -> float:
        """Pixels per second over the last second or so (a waiter standing at a table is nearly still)."""
        old = next((p for p in self.path if t - p[0] <= window), None)
        if old is None or t - old[0] < 0.4:
            return 0.0
        return ((self.foot[0] - old[1]) ** 2 + (self.foot[1] - old[2]) ** 2) ** 0.5 / (t - old[0])


class Tracker:
    def __init__(self, max_gap: float = 2.5, max_dist: float = 80.0) -> None:
        self.tracks: dict[int, Track] = {}
        self._next = 1
        self.max_gap, self.max_dist = max_gap, max_dist

    def update(self, detections: list[Detection], t: float) -> list[Track]:
        pairs = []
        for tid, tr in self.tracks.items():
            for di, d in enumerate(detections):
                iou = _iou(tr.box, d.box)
                dist = ((tr.center[0] - d.center[0]) ** 2 + (tr.center[1] - d.center[1]) ** 2) ** 0.5
                if iou >= 0.15 or dist <= self.max_dist:
                    pairs.append((iou - dist / 1000, tid, di))
        used_t: set[int] = set()
        used_d: set[int] = set()
        for _, tid, di in sorted(pairs, reverse=True):
            if tid in used_t or di in used_d:
                continue
            used_t.add(tid)
            used_d.add(di)
            tr = self.tracks[tid]
            tr.box, tr.last_t, tr.hits = detections[di].box, t, tr.hits + 1
        for di, d in enumerate(detections):
            if di not in used_d:
                self.tracks[self._next] = Track(self._next, d.box, t, t)
                self._next += 1
        for tid in [k for k, tr in self.tracks.items() if t - tr.last_t > self.max_gap]:
            del self.tracks[tid]
        now = [tr for tr in self.tracks.values() if tr.last_t == t]
        for tr in now:
            tr.path.append((t, *tr.foot))
        return now

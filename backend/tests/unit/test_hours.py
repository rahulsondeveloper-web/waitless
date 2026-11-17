from dataclasses import dataclass
from datetime import UTC, datetime, time

from app.services.discovery import haversine_km
from app.services.hours import open_status


@dataclass
class D:
    weekday: int
    is_closed: bool = False
    opens_at: time | None = time(11)
    closes_at: time | None = time(23)


WEEK = [D(i) for i in range(7)]
# 2026-11-16 is a Monday. India is UTC+5:30, so 06:30 UTC = 12:00 IST.
MON_NOON_IST = datetime(2026, 11, 16, 6, 30, tzinfo=UTC)


def test_open_and_closed_by_local_time() -> None:
    assert open_status(WEEK, "Asia/Kolkata", MON_NOON_IST).is_open
    assert open_status(WEEK, "Asia/Kolkata", MON_NOON_IST).today == "11:00–23:00"
    # 04:00 UTC = 09:30 IST → before opening
    assert not open_status(WEEK, "Asia/Kolkata", datetime(2026, 11, 16, 4, 0, tzinfo=UTC)).is_open


def test_closed_day() -> None:
    week = [D(0, is_closed=True, opens_at=None, closes_at=None), *WEEK[1:]]
    s = open_status(week, "Asia/Kolkata", MON_NOON_IST)
    assert not s.is_open and s.today == "Closed"


def test_past_midnight_window_counts_for_next_morning() -> None:
    week = [D(i, opens_at=time(18), closes_at=time(2)) for i in range(7)]
    # Tuesday 01:00 IST (Monday 19:30 UTC) → still Monday's night service
    tue_1am = datetime(2026, 11, 16, 19, 30, tzinfo=UTC)
    assert open_status(week, "Asia/Kolkata", tue_1am).is_open
    # Tuesday 03:00 IST → closed
    assert not open_status(week, "Asia/Kolkata", datetime(2026, 11, 16, 21, 30, tzinfo=UTC)).is_open
    # Monday 20:00 IST → open
    assert open_status(week, "Asia/Kolkata", datetime(2026, 11, 16, 14, 30, tzinfo=UTC)).is_open


def test_previous_day_closed_does_not_spill() -> None:
    week = [D(i, opens_at=time(18), closes_at=time(2)) for i in range(7)]
    week[0] = D(0, is_closed=True, opens_at=None, closes_at=None)
    tue_1am = datetime(2026, 11, 16, 19, 30, tzinfo=UTC)
    assert not open_status(week, "Asia/Kolkata", tue_1am).is_open


def test_no_hours_and_bad_timezone() -> None:
    assert open_status([], "Asia/Kolkata") == open_status([], "Asia/Kolkata")
    assert open_status([], "x").today is None
    assert open_status(WEEK, "Not/AZone", MON_NOON_IST).is_open  # falls back to India time


def test_haversine() -> None:
    pune, mumbai = (18.5204, 73.8567), (19.0760, 72.8777)
    assert 115 < haversine_km(*pune, *mumbai) < 125

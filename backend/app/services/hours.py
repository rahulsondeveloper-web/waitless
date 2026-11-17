"""Opening-hours logic shared by storefront and discovery. Times are local to the branch's timezone."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DayHours(Protocol):
    weekday: int  # 0 = Monday
    is_closed: bool
    opens_at: time | None
    closes_at: time | None


@dataclass(frozen=True)
class OpenStatus:
    is_open: bool
    today: str | None  # "11:00–23:00", "Closed" or None when hours are not set


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


def _covers(day: DayHours | None, t: time, *, previous_day: bool) -> bool:
    if day is None or day.is_closed or day.opens_at is None or day.closes_at is None:
        return False
    o, c = day.opens_at, day.closes_at
    overnight = c <= o  # e.g. 18:00 → 02:00
    if previous_day:
        return overnight and t < c  # yesterday's window spilling past midnight
    return (o <= t < c) if not overnight else t >= o


def open_status(days: list[DayHours], timezone: str, now: datetime | None = None) -> OpenStatus:
    if not days:
        return OpenStatus(is_open=False, today=None)
    local = (now or datetime.now(UTC)).astimezone(_tz(timezone))
    by_day = {d.weekday: d for d in days}
    today = by_day.get(local.weekday())
    yesterday = by_day.get((local - timedelta(days=1)).weekday())
    t = local.time()
    is_open = _covers(today, t, previous_day=False) or _covers(yesterday, t, previous_day=True)
    if today is None:
        label = None
    elif today.is_closed or not today.opens_at or not today.closes_at:
        label = "Closed"
    else:
        label = f"{today.opens_at:%H:%M}–{today.closes_at:%H:%M}"
    return OpenStatus(is_open=is_open, today=label)

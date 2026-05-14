"""Window-start and window-reset computation for limit windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


ROLLING_WINDOWS = {
    "rolling-24h": timedelta(hours=24),
    "rolling-7d": timedelta(days=7),
    "rolling-30d": timedelta(days=30),
}

CALENDAR_WINDOWS = {"calendar-day", "calendar-week", "calendar-month"}

ALL_WINDOWS = set(ROLLING_WINDOWS) | CALENDAR_WINDOWS


def window_start(window: str, now: datetime) -> datetime:
    """Return the inclusive lower bound of the window containing `now`."""
    if window in ROLLING_WINDOWS:
        return now - ROLLING_WINDOWS[window]
    if window == "calendar-day":
        return _midnight(now)
    if window == "calendar-week":
        midnight = _midnight(now)
        return midnight - timedelta(days=midnight.weekday())
    if window == "calendar-month":
        return _midnight(now).replace(day=1)
    raise ValueError(f"Unknown window: {window!r}")


def window_reset(window: str, now: datetime) -> Optional[datetime]:
    """Return the next reset point for calendar windows, or None for rolling windows."""
    if window in ROLLING_WINDOWS:
        return None
    if window == "calendar-day":
        return _midnight(now) + timedelta(days=1)
    if window == "calendar-week":
        return window_start("calendar-week", now) + timedelta(days=7)
    if window == "calendar-month":
        start = window_start("calendar-month", now)
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    raise ValueError(f"Unknown window: {window!r}")


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

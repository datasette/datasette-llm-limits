from datetime import datetime, timedelta, timezone

import pytest

from datasette_llm_limits.windows import window_start, window_reset

UTC = timezone.utc


@pytest.mark.parametrize(
    "window,delta",
    [
        ("rolling-24h", timedelta(hours=24)),
        ("rolling-7d", timedelta(days=7)),
        ("rolling-30d", timedelta(days=30)),
    ],
)
def test_rolling_windows_subtract_their_duration(window, delta):
    now = datetime(2026, 3, 14, 12, 30, 45, tzinfo=UTC)
    assert window_start(window, now) == now - delta


def test_calendar_day_starts_at_utc_midnight():
    now = datetime(2026, 3, 14, 23, 59, 59, tzinfo=UTC)
    assert window_start("calendar-day", now) == datetime(2026, 3, 14, tzinfo=UTC)


def test_calendar_week_starts_on_monday_at_midnight_utc():
    # 2026-03-14 is a Saturday; Monday of that week is 2026-03-09
    now = datetime(2026, 3, 14, 23, 59, 59, tzinfo=UTC)
    assert window_start("calendar-week", now) == datetime(2026, 3, 9, tzinfo=UTC)


def test_calendar_week_on_a_monday_returns_that_monday():
    now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
    assert window_start("calendar-week", now) == datetime(2026, 3, 9, tzinfo=UTC)


def test_calendar_month_starts_on_day_1_utc_midnight():
    now = datetime(2026, 3, 14, 23, 59, 59, tzinfo=UTC)
    assert window_start("calendar-month", now) == datetime(2026, 3, 1, tzinfo=UTC)


def test_unknown_window_raises_value_error():
    with pytest.raises(ValueError):
        window_start("rolling-1h", datetime(2026, 1, 1, tzinfo=UTC))


def test_window_reset_is_none_for_rolling_windows():
    now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    assert window_reset("rolling-24h", now) is None
    assert window_reset("rolling-7d", now) is None
    assert window_reset("rolling-30d", now) is None


def test_window_reset_calendar_day_is_next_midnight_utc():
    now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    assert window_reset("calendar-day", now) == datetime(2026, 3, 15, tzinfo=UTC)


def test_window_reset_calendar_week_is_next_monday_midnight_utc():
    now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)  # Saturday
    assert window_reset("calendar-week", now) == datetime(2026, 3, 16, tzinfo=UTC)


def test_window_reset_calendar_month_is_first_of_next_month():
    now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    assert window_reset("calendar-month", now) == datetime(2026, 4, 1, tzinfo=UTC)


def test_window_reset_calendar_month_crosses_year():
    now = datetime(2026, 12, 31, 23, 0, 0, tzinfo=UTC)
    assert window_reset("calendar-month", now) == datetime(2027, 1, 1, tzinfo=UTC)

"""The Qt-free helpers behind the clock's next-holiday countdown."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.widgets.services.clock.next_holiday import find_next_holiday, format_countdown, truncate_name

JAKARTA = ZoneInfo("Asia/Jakarta")
CHRISTMAS = date(2026, 12, 25)

# Real `holidays.country_holidays("ID", years=[2026, 2027])` entries around the year end.
HOLIDAYS = {
    date(2026, 8, 17): "Hari Kemerdekaan Republik Indonesia",
    date(2026, 12, 25): "Hari Raya Natal",
    date(2027, 1, 1): "Tahun Baru Masehi",
    date(2027, 1, 5): "Isra Mikraj Nabi Muhammad (perkiraan)",
}


def _at(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=JAKARTA)


# --- find_next_holiday ---------------------------------------------------------------


def test_returns_the_first_holiday_after_today():
    assert find_next_holiday(HOLIDAYS, date(2026, 10, 1)) == (CHRISTMAS, "Hari Raya Natal")


def test_a_holiday_today_is_the_next_one():
    assert find_next_holiday(HOLIDAYS, CHRISTMAS) == (CHRISTMAS, "Hari Raya Natal")


def test_rolls_over_into_next_year():
    assert find_next_holiday(HOLIDAYS, date(2026, 12, 26)) == (date(2027, 1, 1), "Tahun Baru Masehi")


def test_none_when_nothing_is_left():
    assert find_next_holiday(HOLIDAYS, date(2027, 1, 6)) is None


def test_none_for_an_empty_calendar():
    assert find_next_holiday({}, date(2026, 10, 1)) is None


# --- format_countdown ----------------------------------------------------------------


def test_far_off_counts_calendar_days():
    now = _at(2026, 10, 1, 9, 18)
    assert format_countdown(now, CHRISTMAS) == "85d"
    assert format_countdown(now, CHRISTMAS, long=True) == "85 days"


def test_seven_days_out_still_counts_days():
    assert format_countdown(_at(2026, 12, 18, 0, 0), CHRISTMAS) == "7d"


def test_within_a_week_shows_days_and_hours():
    now = _at(2026, 12, 22, 9, 30)
    assert format_countdown(now, CHRISTMAS) == "2d 14h"
    assert format_countdown(now, CHRISTMAS, long=True) == "2d 14h"


def test_under_a_day_shows_hours_and_minutes():
    now = _at(2026, 12, 24, 9, 28)
    assert format_countdown(now, CHRISTMAS) == "14h 32m"
    assert format_countdown(now, CHRISTMAS, long=True) == "14h 32m"


def test_under_an_hour_shows_minutes_only():
    assert format_countdown(_at(2026, 12, 24, 23, 15), CHRISTMAS) == "45m"


def test_last_minute_never_reads_zero():
    assert format_countdown(_at(2026, 12, 24, 23, 59, 30), CHRISTMAS) == "1m"


def test_on_the_day_reads_today():
    now = _at(2026, 12, 25, 0, 0)
    assert format_countdown(now, CHRISTMAS) == "Today"
    assert format_countdown(now, CHRISTMAS, long=True) == "Today"


def test_counts_to_midnight_in_the_clocks_timezone():
    # 08:00 UTC on 24 Dec is 15:00 in Jakarta: nine hours to go there, sixteen in UTC.
    utc_now = datetime(2026, 12, 24, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert format_countdown(utc_now.astimezone(JAKARTA), CHRISTMAS) == "9h 0m"
    assert format_countdown(utc_now, CHRISTMAS) == "16h 0m"


# --- truncate_name -------------------------------------------------------------------


def test_short_names_are_kept():
    assert truncate_name("Hari Raya Natal", 20) == "Hari Raya Natal"


def test_long_names_end_in_an_ellipsis():
    assert truncate_name("Isra Mikraj Nabi Muhammad (perkiraan)", 20) == "Isra Mikraj Nabi..."

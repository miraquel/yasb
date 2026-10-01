"""Tests for the Qt-free next-holiday helpers behind the clock's holiday countdown."""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.clock.next_holiday import (  # noqa: E402
    find_next_holiday,
    format_countdown,
    truncate_name,
)

JAKARTA = ZoneInfo("Asia/Jakarta")

# Real `holidays.country_holidays("ID", years=[2026, 2027])` entries around the year end.
HOLIDAYS = {
    date(2026, 8, 17): "Hari Kemerdekaan Republik Indonesia",
    date(2026, 12, 25): "Hari Raya Natal",
    date(2027, 1, 1): "Tahun Baru Masehi",
    date(2027, 1, 5): "Isra Mikraj Nabi Muhammad (perkiraan)",
}


class FindNextHolidayTests(unittest.TestCase):
    def test_returns_the_first_holiday_after_today(self) -> None:
        self.assertEqual(find_next_holiday(HOLIDAYS, date(2026, 10, 1)), (date(2026, 12, 25), "Hari Raya Natal"))

    def test_a_holiday_today_is_the_next_one(self) -> None:
        self.assertEqual(find_next_holiday(HOLIDAYS, date(2026, 12, 25)), (date(2026, 12, 25), "Hari Raya Natal"))

    def test_rolls_over_into_next_year(self) -> None:
        self.assertEqual(find_next_holiday(HOLIDAYS, date(2026, 12, 26)), (date(2027, 1, 1), "Tahun Baru Masehi"))

    def test_none_when_nothing_is_left(self) -> None:
        self.assertIsNone(find_next_holiday(HOLIDAYS, date(2027, 1, 6)))

    def test_none_for_an_empty_calendar(self) -> None:
        self.assertIsNone(find_next_holiday({}, date(2026, 10, 1)))


class FormatCountdownTests(unittest.TestCase):
    CHRISTMAS = date(2026, 12, 25)

    def at(self, *args: int) -> datetime:
        return datetime(*args, tzinfo=JAKARTA)

    def test_far_off_counts_calendar_days(self) -> None:
        now = self.at(2026, 10, 1, 9, 18)
        self.assertEqual(format_countdown(now, self.CHRISTMAS), "85d")
        self.assertEqual(format_countdown(now, self.CHRISTMAS, long=True), "85 days")

    def test_seven_days_out_still_counts_days(self) -> None:
        self.assertEqual(format_countdown(self.at(2026, 12, 18, 0, 0), self.CHRISTMAS), "7d")

    def test_within_a_week_shows_days_and_hours(self) -> None:
        now = self.at(2026, 12, 22, 9, 30)
        self.assertEqual(format_countdown(now, self.CHRISTMAS), "2d 14h")
        self.assertEqual(format_countdown(now, self.CHRISTMAS, long=True), "2d 14h")

    def test_under_a_day_shows_hours_and_minutes(self) -> None:
        now = self.at(2026, 12, 24, 9, 28)
        self.assertEqual(format_countdown(now, self.CHRISTMAS), "14h 32m")
        self.assertEqual(format_countdown(now, self.CHRISTMAS, long=True), "14h 32m")

    def test_under_an_hour_shows_minutes_only(self) -> None:
        self.assertEqual(format_countdown(self.at(2026, 12, 24, 23, 15), self.CHRISTMAS), "45m")

    def test_last_minute_never_reads_zero(self) -> None:
        self.assertEqual(format_countdown(self.at(2026, 12, 24, 23, 59, 30), self.CHRISTMAS), "1m")

    def test_on_the_day_reads_today(self) -> None:
        now = self.at(2026, 12, 25, 0, 0)
        self.assertEqual(format_countdown(now, self.CHRISTMAS), "Today")
        self.assertEqual(format_countdown(now, self.CHRISTMAS, long=True), "Today")

    def test_counts_to_midnight_in_the_clocks_timezone(self) -> None:
        # 08:00 UTC on 24 Dec is 15:00 in Jakarta: nine hours to go there, sixteen in UTC.
        utc_now = datetime(2026, 12, 24, 8, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(format_countdown(utc_now.astimezone(JAKARTA), self.CHRISTMAS), "9h 0m")
        self.assertEqual(format_countdown(utc_now, self.CHRISTMAS), "16h 0m")


class TruncateNameTests(unittest.TestCase):
    def test_short_names_are_kept(self) -> None:
        self.assertEqual(truncate_name("Hari Raya Natal", 20), "Hari Raya Natal")

    def test_long_names_end_in_an_ellipsis(self) -> None:
        self.assertEqual(truncate_name("Isra Mikraj Nabi Muhammad (perkiraan)", 20), "Isra Mikraj Nabi...")


if __name__ == "__main__":
    unittest.main()

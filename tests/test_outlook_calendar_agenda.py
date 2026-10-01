"""Tests for the Outlook calendar's pure logic: which event the bar shows, countdowns, the
popup's day groups, join links, the status line and the cache format.

The fixture day is Thursday 2026-10-01, 09:00 local time.
"""

import json
import sys
import unittest
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.outlook_calendar.agenda import (  # noqa: E402
    CalEvent,
    Day,
    Snapshot,
    day_heading,
    find_join_url,
    format_countdown,
    format_status,
    format_time_range,
    group_by_day,
    row_status,
    select_event,
    shorten,
    snapshot_from_cache,
    snapshot_to_cache,
    today_count,
)

NOW = datetime(2026, 10, 1, 9, 0)
TEAMS = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_NjM4%40thread.v2/0?context=%7b%22Tid%22%3a%22a1%22%7d"
TEAMS_NEW = "https://teams.microsoft.com/meet/23456789012?p=AbCdEf"
ZOOM = "https://us02web.zoom.us/j/81234567890?pwd=abcDEF123"
MEET = "https://meet.google.com/abc-defg-hij"


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second)


def ev(start: datetime, end: datetime, subject: str = "Meeting", **fields) -> CalEvent:
    return CalEvent(start=start, end=end, subject=subject, **fields)


def all_day(first: int, last: int, subject: str = "Holiday") -> CalEvent:
    """An all-day event covering October *first* to *last*, stored the way Outlook does."""
    return ev(at(first, 0), at(last + 1, 0), subject, all_day=True)


class SelectEventTests(unittest.TestCase):
    def test_next_timed_event(self):
        events = [ev(at(1, 14), at(1, 15), "Weekly sync"), ev(at(1, 11), at(1, 12), "Standup")]
        self.assertEqual(select_event(events, NOW).subject, "Standup")

    def test_ongoing_wins_over_next(self):
        events = [ev(at(1, 9, 15), at(1, 9, 45), "Call"), ev(at(1, 8, 30), at(1, 9, 30), "Vendor review")]
        self.assertEqual(select_event(events, NOW).subject, "Vendor review")

    def test_overlapping_ongoing_events_pick_the_one_ending_first(self):
        events = [ev(at(1, 8), at(1, 11), "Workshop"), ev(at(1, 8, 30), at(1, 9, 30), "Check-in")]
        self.assertEqual(select_event(events, NOW).subject, "Check-in")

    def test_free_all_day_and_declined_are_skipped(self):
        events = [
            ev(at(1, 10), at(1, 11), "Focus", busy=0),
            all_day(1, 1),
            ev(at(1, 10), at(1, 11), "Declined", response=4),
            ev(at(2, 10), at(2, 11), "Tomorrow"),
        ]
        self.assertEqual(select_event(events, NOW).subject, "Tomorrow")

    def test_unanswered_invite_counts_and_is_tentative(self):
        invite = ev(at(1, 10), at(1, 11), "Invite", busy=1, response=5)
        self.assertIs(select_event([invite], NOW), invite)
        self.assertTrue(invite.tentative)
        self.assertFalse(ev(at(1, 10), at(1, 11), response=3).tentative)

    def test_end_is_exclusive(self):
        self.assertIsNone(select_event([ev(at(1, 8), at(1, 9))], NOW))

    def test_nothing_left(self):
        self.assertIsNone(select_event([], NOW))

    def test_zero_length_event_counts_down_then_disappears(self):
        reminder = ev(at(1, 10), at(1, 10), "Reminder")
        self.assertEqual(format_countdown(reminder, at(1, 9, 59, 30)), "in 1m")
        self.assertIs(select_event([reminder], at(1, 9, 59, 30)), reminder)
        self.assertIsNone(select_event([reminder], at(1, 10)))


class TodayCountTests(unittest.TestCase):
    def test_counts_eligible_events_today_not_yet_ended(self):
        events = [
            ev(at(1, 7), at(1, 8), "Ended"),
            ev(at(1, 8, 30), at(1, 9, 30), "Ongoing"),
            ev(at(1, 14), at(1, 15), "Later"),
            ev(at(1, 16), at(1, 17), "Free", busy=0),
            ev(at(2, 10), at(2, 11), "Tomorrow"),
        ]
        self.assertEqual(today_count(events, NOW), 2)


class CountdownTests(unittest.TestCase):
    def countdown(self, start: datetime, now: datetime = NOW, **kwargs) -> str:
        return format_countdown(ev(start, start + timedelta(minutes=30)), now, **kwargs)

    def test_minutes_round_up(self):
        self.assertEqual(self.countdown(NOW + timedelta(minutes=24, seconds=10)), "in 25m")
        self.assertEqual(self.countdown(NOW + timedelta(seconds=20)), "in 1m")

    def test_rounding_reaches_the_hour(self):
        self.assertEqual(self.countdown(NOW + timedelta(minutes=59, seconds=30)), "in 1h")

    def test_later_today(self):
        self.assertEqual(self.countdown(at(1, 12, 20)), "in 3h 20m")
        self.assertEqual(self.countdown(at(1, 11)), "in 2h")

    def test_later_days(self):
        self.assertEqual(self.countdown(at(2, 10)), "tomorrow 10:00")
        self.assertEqual(self.countdown(at(6, 10)), "Tue 10:00")
        self.assertEqual(self.countdown(at(8, 10)), "8 Oct 10:00")

    def test_across_midnight(self):
        self.assertEqual(self.countdown(at(2, 0, 10), now=at(1, 23, 50)), "in 20m")
        self.assertEqual(self.countdown(at(2, 0, 45), now=at(1, 23, 30)), "tomorrow 00:45")

    def test_ongoing_and_ended(self):
        event = ev(at(1, 8, 30), at(1, 9, 30))
        self.assertEqual(format_countdown(event, NOW), "now")
        self.assertEqual(format_countdown(event, at(1, 9, 30)), "ended")

    def test_time_format(self):
        self.assertEqual(self.countdown(at(2, 15), time_format="%I:%M %p"), "tomorrow 03:00 PM")


class FormattingTests(unittest.TestCase):
    def test_row_status(self):
        self.assertEqual(row_status(ev(at(1, 7), at(1, 8)), NOW), "ended")
        self.assertEqual(row_status(ev(at(1, 8, 30), at(1, 9, 30)), NOW), "now")
        self.assertEqual(row_status(ev(at(1, 14), at(1, 15)), NOW), "in 5h")
        self.assertEqual(row_status(ev(at(2, 10), at(2, 11)), NOW), "")
        self.assertEqual(row_status(all_day(1, 1), NOW), "")

    def test_time_range(self):
        self.assertEqual(format_time_range(ev(at(1, 14), at(1, 15))), "14:00–15:00")
        self.assertEqual(format_time_range(all_day(1, 1)), "all day")

    def test_shorten(self):
        self.assertEqual(shorten("Weekly sync", 20), "Weekly sync")
        self.assertEqual(shorten("Quarterly planning", 10), "Quarterly…")
        self.assertEqual(shorten("Quarterly planning", 0), "Quarterly planning")
        self.assertEqual(shorten("Line one\r\nline two", 0), "Line one line two")


class GroupByDayTests(unittest.TestCase):
    def test_groups_sorts_and_omits_empty_days(self):
        late = ev(at(1, 14), at(1, 15), "Late")
        early = ev(at(1, 11), at(1, 12), "Early")
        saturday = ev(at(3, 10), at(3, 11), "Saturday")
        days = group_by_day([late, saturday, early], date(2026, 10, 1), 7)
        self.assertEqual(
            days,
            [Day(date(2026, 10, 1), (), (early, late)), Day(date(2026, 10, 3), (), (saturday,))],
        )

    def test_all_day_events_cover_each_of_their_days(self):
        trip = all_day(1, 3, "Trip")
        days = group_by_day([trip], date(2026, 10, 1), 7)
        self.assertEqual([d.day.day for d in days], [1, 2, 3])
        self.assertTrue(all(d.all_day == (trip,) for d in days))

    def test_event_from_before_today_is_listed_under_today(self):
        overnight = ev(datetime(2026, 9, 30, 22), at(1, 1), "Overnight")
        self.assertEqual(group_by_day([overnight], date(2026, 10, 1), 7), [Day(date(2026, 10, 1), (), (overnight,))])

    def test_window_bounds(self):
        yesterday = ev(datetime(2026, 9, 30, 10), datetime(2026, 9, 30, 11), "Yesterday")
        beyond = ev(at(8, 10), at(8, 11), "Next Thursday")
        self.assertEqual(group_by_day([yesterday, beyond], date(2026, 10, 1), 7), [])

    def test_midnight_rollover_moves_today(self):
        thursday = ev(at(1, 14), at(1, 15), "Thursday")
        friday = ev(at(2, 10), at(2, 11), "Friday")
        days = group_by_day([thursday, friday], date(2026, 10, 2), 7)
        self.assertEqual(days, [Day(date(2026, 10, 2), (), (friday,))])
        self.assertEqual(day_heading(days[0].day, date(2026, 10, 2)), "Today")

    def test_day_headings(self):
        today = date(2026, 10, 1)
        self.assertEqual(day_heading(today, today), "Today")
        self.assertEqual(day_heading(date(2026, 10, 2), today), "Tomorrow")
        self.assertEqual(day_heading(date(2026, 10, 3), today), "Sat 3 Oct")


class JoinUrlTests(unittest.TestCase):
    def test_teams_link_inside_angle_brackets(self):
        body = f"Microsoft Teams meeting\r\nJoin on your computer\r\n<{TEAMS}>\r\nMeeting ID: 123"
        self.assertEqual(find_join_url(body), TEAMS)

    def test_new_teams_link(self):
        self.assertEqual(find_join_url(f"Join: {TEAMS_NEW}"), TEAMS_NEW)

    def test_zoom_link_drops_trailing_punctuation(self):
        self.assertEqual(find_join_url(f"Zoom: {ZOOM}."), ZOOM)

    def test_meet_link(self):
        self.assertEqual(find_join_url(f"{MEET} (Google Meet)"), MEET)

    def test_safe_links_wrapper_is_unwrapped(self):
        wrapped = (
            "https://apc01.safelinks.protection.outlook.com/?url="
            + urllib.parse.quote(ZOOM, safe="")
            + "&data=05%7C02%7C&reserved=0"
        )
        self.assertEqual(find_join_url(f"Join <{wrapped}>"), ZOOM)

    def test_no_link(self):
        for text in (
            "",
            "Room 4B",
            "https://teams.microsoft.com/",
            "https://example.com/j/123",
            "meet.google.com/abc-defg-hij",
        ):
            self.assertEqual(find_join_url(text), "", text)


class FormatStatusTests(unittest.TestCase):
    def test_lines(self):
        events = (ev(at(1, 14), at(1, 15)),)
        cases = [
            (Snapshot(events, at(1, 8, 12), "live"), "updated 08:12"),
            (Snapshot(events, at(1, 8, 12), "stale"), "Outlook closed · cached 08:12"),
            (Snapshot(events, datetime(2026, 9, 30, 17, 5), "stale"), "Outlook closed · cached 30 Sep 17:05"),
            (Snapshot(events, at(1, 8, 12), "error"), "Outlook unavailable · cached 08:12"),
            (Snapshot(), "Outlook closed"),
            (Snapshot((), None, "error"), "Outlook unavailable"),
        ]
        for snapshot, text in cases:
            self.assertEqual(format_status(snapshot, NOW), text)


class CacheTests(unittest.TestCase):
    def test_round_trip_comes_back_stale(self):
        events = (
            ev(
                at(1, 14),
                at(1, 15),
                "Sync",
                location="Room 4B",
                busy=1,
                response=5,
                entry_id="E1",
                store_id="S1",
                recurring=True,
                join_url=ZOOM,
            ),
            all_day(2, 2),
        )
        restored = snapshot_from_cache(snapshot_to_cache(Snapshot(events, at(1, 8, 12), "live")))
        self.assertEqual(restored, Snapshot(events, at(1, 8, 12), "stale"))

    def test_survives_json(self):
        snapshot = Snapshot((ev(at(1, 14), at(1, 15), "Sync"),), at(1, 8, 12), "live")
        data = json.loads(json.dumps(snapshot_to_cache(snapshot)))
        self.assertEqual(snapshot_from_cache(data).events, snapshot.events)

    def test_rejects_other_versions_and_garbage(self):
        for data in (
            None,
            [],
            "x",
            {"version": 99, "events": []},
            {"version": 1, "events": [{"start": "nope"}]},
            {"version": 1, "events": "x"},
        ):
            self.assertIsNone(snapshot_from_cache(data), data)


if __name__ == "__main__":
    unittest.main()

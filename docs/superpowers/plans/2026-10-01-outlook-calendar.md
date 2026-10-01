# Outlook Calendar Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A yasb bar widget that counts down to the next event on the default classic-Outlook calendar, with a popup listing the coming days.

**Architecture:** A pure logic module (`agenda.py`) holds the event model and every rule. A COM source (`outlook.py`) reads Outlook by attaching only, never launching it. A shared, reference-counted service (`service.py`) polls on a `QThread` and caches the last read to disk. The widget only renders from the service's snapshot. The layout copies the fork's `anime_airing` widget.

**Tech Stack:** Python 3.14, PyQt6 6.10.2, pywin32 312 (`win32com`, `pythoncom`, `pywintypes`, `win32api`), pydantic, unittest.

**Spec:** `docs/superpowers/specs/2026-10-01-outlook-calendar-design.md` on branch `spec/outlook-calendar`. Read it before starting; this plan argues from it.

## Global Constraints

- All work happens on branch `feat/outlook-calendar`, created from `main` (`d6d1e6d5`), in its own git worktree (create it with superpowers:using-git-worktrees). This plan writes that worktree's root as `<wt>`. Every command runs from `<wt>`.
- Never commit on `squash`; it is an assembly of the feature branches only. Never commit `src/schema.json`. Never push.
- No new dependencies: pywin32 312 and PyQt6 are already in `pyproject.toml`.
- The Python is `D:\Programming\yasb\.venv\Scripts\python.exe` (the worktree has no venv). pytest is not installed. Tests are unittest modules run by name from `<wt>`: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.<module> -v`.
- ruff: line length 120, rules `I`, `F`, `UP`, `G004` (no f-strings in logging calls), target py314. Before every commit, run `-m ruff format <files>` then `-m ruff check --fix <files>` then `-m ruff check <files>`. With py314, `ruff format` writes `except A, B:` without parentheses; that is expected.
- COM runs only off the UI thread. `fetch` attaches with `GetActiveObject` and never calls `Dispatch`, so a poll cannot start Outlook. Only `open_event` (an explicit click) may use `Dispatch`.
- Times are naive local wall-clock `datetime`s everywhere. Outlook returns local wall time labelled with a GMT tzinfo: keep the wall time and drop the tzinfo. Going the other way, pass COM a wall time labelled UTC. pywintypes treats a naive datetime as local and shifts it by the UTC offset (7 h here); this was verified on 2026-10-01.
- Weekday and month names are fixed English (`Mon`, `Oct`), never strftime `%a`/`%b`, because yasb's clock widget switches the process locale.
- Every label shows event text as plain text (`Qt.TextFormat.PlainText`), and the tooltip HTML-escapes it.
- Widgets must read sensibly unstyled and under other themes. Bar label classes: `soon`, `ongoing`, `tentative`, `stale`, `empty`, `closed`, `error`.
- Nerd Font glyphs must be v3 codepoints outside U+F500–U+FD46. The default icon is U+F073 (fa-calendar).
- Logger name: `outlook_calendar`.
- Cache file: `%LOCALAPPDATA%\YASB\outlook_calendar.json`, `{"version": 1, "fetched_at": ..., "events": [...]}`.
- Defaults: `days` 7 (1–31), `update_interval` 300 s (60–3600), `soon_minutes` 15 (0–240; 0 turns `soon` off), `max_title_length` 20 (0–200; 0 means no limit), `time_format` `"%H:%M"`, `scan_body` true, `menu.min_width` 340, `menu.max_rows` 12. An `error` status needs 3 consecutive non-"not running" failures.

## Review Focus

These five inputs aren't spelled out by the spec, and each could bite a real user. Each one has a pinning test in the task that owns its code:

1. **A subject that looks like markup or a placeholder** (`<b>Budget</b> & {time}`, `Review <draft>`) must show exactly as typed on the bar, in the popup and in the tooltip. Pinned in Task 4: `test_subject_is_plain_text`, `test_subject_in_popup_is_plain_text`, `test_event_details`.
2. **A cache from an earlier day** (Outlook closed since yesterday) must not count down to, or list under Today, events that already ended. Pinned in Task 1 (`test_window_bounds`) and Task 4 (`test_cache_from_yesterday_shows_no_ended_events`).
3. **A zero-length event** (a reminder with start equal to end) must count down and then disappear, never sticking as `now`. Pinned in Task 1: `test_zero_length_event_counts_down_then_disappears`.
4. **Outlook busy behind a modal dialog** (`RPC_E_CALL_REJECTED`) must surface as a failure, never as "Outlook closed", so the stale marker and the 3-strikes error stay honest. Pinned in Task 2 (`test_busy_outlook_is_an_error_not_closed`) and Task 3 (`test_three_failures_in_a_row_mark_an_error`).
5. **Midnight passing with yasb running** must move "Today" to the new date and drop yesterday's rows. Pinned in Task 1: `test_midnight_rollover_moves_today`.

---

## File Map

| File | Responsibility |
|---|---|
| Create `src/core/widgets/services/outlook_calendar/agenda.py` | `CalEvent`, `Snapshot`, `Day`; selection, countdowns, grouping, join links, status line, cache (de)serialisation. Pure. |
| Create `src/core/widgets/services/outlook_calendar/outlook.py` | COM: `fetch`, `outlook_time`, `open_event`, `open_event_in_background`, `open_calendar`, `OutlookNotRunning`. |
| Create `src/core/widgets/services/outlook_calendar/service.py` | `OutlookCalendarService` (shared poller), `_FetchWorker`, `load_cache`, `write_cache`, `cache_path`. |
| Create `src/core/validation/widgets/yasb/outlook_calendar.py` | `OutlookCalendarConfig` and its sub-models. |
| Create `src/core/widgets/yasb/outlook_calendar.py` | `OutlookCalendarWidget`: bar label, tooltip, popup. |
| Create `tests/test_outlook_calendar_agenda.py`, `tests/test_outlook_calendar_outlook.py`, `tests/test_outlook_calendar_service.py`, `tests/test_outlook_calendar_widget.py` | Tests: 35, 20, 16 and 32, so 103 in all. |
| Create `docs/widgets/(Widget)-Outlook-Calendar.md` | Docs page. |
| Modify `README.md` (after the Open Meteo row, line 119), `docs/_Sidebar.md` (after the Open Meteo entry, line 51) | Listing. |

The services folders have no `__init__.py` (namespace packages, like `services/anime_airing`), so none is created.

---

### Task 1: Event model and agenda logic

**Files:**
- Create: `src/core/widgets/services/outlook_calendar/agenda.py`
- Test: `tests/test_outlook_calendar_agenda.py`

**Interfaces:**
- Consumes: nothing.
- Produces (later tasks import exactly these names):
  - Constants `BUSY_FREE=0`, `BUSY_TENTATIVE=1`, `BUSY_BUSY=2`, `RESPONSE_NONE=0`, `RESPONSE_TENTATIVE=2`, `RESPONSE_DECLINED=4`, `RESPONSE_NOT_RESPONDED=5`, `CACHE_VERSION=1`.
  - `CalEvent(start, end, subject, location="", all_day=False, busy=2, response=0, entry_id="", store_id="", recurring=False, join_url="")`, frozen. Properties `.tentative` and `.eligible`; methods `.ongoing(now)`, `.to_dict()`, `CalEvent.from_dict(d)`.
  - `Snapshot(events: tuple[CalEvent, ...] = (), fetched_at: datetime | None = None, status: "live"|"stale"|"closed"|"error" = "closed")`, frozen.
  - `Day(day: date, all_day: tuple[CalEvent, ...], timed: tuple[CalEvent, ...])`, frozen.
  - Functions:
    - `day_start(d: date) -> datetime`
    - `select_event(events, now) -> CalEvent | None`
    - `today_count(events, now) -> int`
    - `format_countdown(event, now, time_format="%H:%M") -> str`
    - `row_status(event, now, time_format="%H:%M") -> str`
    - `format_time_range(event, time_format="%H:%M") -> str`
    - `shorten(text, limit) -> str`
    - `day_heading(d, today) -> str`
    - `group_by_day(events, today: date, days: int) -> list[Day]`
    - `find_join_url(text) -> str`
    - `format_status(snapshot, now, time_format="%H:%M") -> str`
    - `snapshot_to_cache(snapshot) -> dict`
    - `snapshot_from_cache(data) -> Snapshot | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outlook_calendar_agenda.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_agenda -v`
Expected: `FAILED (errors=1)`, with `ModuleNotFoundError: No module named 'core.widgets.services.outlook_calendar'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/widgets/services/outlook_calendar/agenda.py`:

```python
"""Pure logic for the Outlook calendar widget: which event the bar counts down to, how the
popup groups the coming days, and how times read.

Nothing here touches COM or Qt, so every rule can be tested with plain datetimes. Times are
naive local wall-clock times throughout: Outlook keeps appointments in local time, and the
widget only ever compares them with ``datetime.now()``.
"""

from __future__ import annotations

import math
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

# OlBusyStatus values.
BUSY_FREE = 0
BUSY_TENTATIVE = 1
BUSY_BUSY = 2
# OlResponseStatus values.
RESPONSE_NONE = 0
RESPONSE_TENTATIVE = 2
RESPONSE_DECLINED = 4
RESPONSE_NOT_RESPONDED = 5

CACHE_VERSION = 1

# Fixed English names: strftime's %a and %b follow the process locale, which yasb's clock
# widget switches temporarily, and the bar must not change language mid-day.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Meeting links worth a Join button. The tail stops at whitespace, quotes and angle brackets:
# plain-text invitation bodies wrap links as <https://...>.
_JOIN_RE = re.compile(
    r"https://(?:"
    r"teams\.microsoft\.com/(?:l/meetup-join|meet)/"
    r"|teams\.live\.com/meet/"
    r"|(?:[\w-]+\.)*zoom\.us/(?:j|my|w)/"
    r"|meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}"
    r")[^\s<>\"']*",
    re.IGNORECASE,
)
# Defender for Office rewrites links as safelinks URLs carrying the original in ?url=.
_SAFELINKS_RE = re.compile(r"https://[\w.-]*safelinks\.protection\.outlook\.com/\?[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ".,;:)]}>\"'"

Status = Literal["live", "stale", "closed", "error"]


@dataclass(frozen=True)
class CalEvent:
    start: datetime
    end: datetime
    subject: str
    location: str = ""
    all_day: bool = False
    busy: int = BUSY_BUSY
    response: int = RESPONSE_NONE
    entry_id: str = ""
    store_id: str = ""
    recurring: bool = False
    join_url: str = ""

    @property
    def tentative(self) -> bool:
        """An invite not yet accepted, or an appointment shown as Tentative."""
        return self.response in (RESPONSE_TENTATIVE, RESPONSE_NOT_RESPONDED) or self.busy == BUSY_TENTATIVE

    @property
    def eligible(self) -> bool:
        """Whether the bar may count down to this event."""
        return not self.all_day and self.busy != BUSY_FREE and self.response != RESPONSE_DECLINED

    def ongoing(self, now: datetime) -> bool:
        return self.start <= now < self.end

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalEvent:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            subject=str(data["subject"]),
            location=str(data.get("location", "")),
            all_day=bool(data.get("all_day", False)),
            busy=int(data.get("busy", BUSY_BUSY)),
            response=int(data.get("response", RESPONSE_NONE)),
            entry_id=str(data.get("entry_id", "")),
            store_id=str(data.get("store_id", "")),
            recurring=bool(data.get("recurring", False)),
            join_url=str(data.get("join_url", "")),
        )


@dataclass(frozen=True)
class Snapshot:
    """What the service last knew. ``fetched_at`` is when the events were read from Outlook."""

    events: tuple[CalEvent, ...] = ()
    fetched_at: datetime | None = None
    status: Status = "closed"


@dataclass(frozen=True)
class Day:
    day: date
    all_day: tuple[CalEvent, ...]
    timed: tuple[CalEvent, ...]


def day_start(value: date) -> datetime:
    return datetime.combine(value, time())


def select_event(events: Iterable[CalEvent], now: datetime) -> CalEvent | None:
    """The event the bar shows: the ongoing one that ends first, else the next to start."""
    eligible = [event for event in events if event.eligible and event.end > now]
    ongoing = [event for event in eligible if event.ongoing(now)]
    if ongoing:
        return min(ongoing, key=lambda event: (event.end, event.start))
    upcoming = [event for event in eligible if event.start > now]
    if not upcoming:
        return None
    return min(upcoming, key=lambda event: (event.start, event.end))


def today_count(events: Iterable[CalEvent], now: datetime) -> int:
    """Eligible events today that have not ended yet."""
    tomorrow = day_start(now.date() + timedelta(days=1))
    return sum(1 for event in events if event.eligible and event.end > now and event.start < tomorrow)


def format_countdown(event: CalEvent, now: datetime, time_format: str = "%H:%M") -> str:
    """How long until *event* starts. The wait is rounded up to whole minutes first."""
    if event.start <= now:
        return "now" if event.end > now else "ended"
    minutes = math.ceil((event.start - now).total_seconds() / 60)
    if minutes < 60:
        return f"in {minutes}m"
    days = (event.start.date() - now.date()).days
    clock = event.start.strftime(time_format)
    if days == 0:
        hours, rest = divmod(minutes, 60)
        return f"in {hours}h {rest}m" if rest else f"in {hours}h"
    if days == 1:
        return f"tomorrow {clock}"
    if days <= 6:
        return f"{_WEEKDAYS[event.start.weekday()]} {clock}"
    return f"{event.start.day} {_MONTHS[event.start.month - 1]} {clock}"


def row_status(event: CalEvent, now: datetime, time_format: str = "%H:%M") -> str:
    """The right-hand text of a popup row; only today's timed events carry one."""
    if event.all_day:
        return ""
    if event.end <= now:
        return "ended"
    if event.ongoing(now) or event.start.date() == now.date():
        return format_countdown(event, now, time_format)
    return ""


def format_time_range(event: CalEvent, time_format: str = "%H:%M") -> str:
    if event.all_day:
        return "all day"
    return f"{event.start.strftime(time_format)}–{event.end.strftime(time_format)}"


def shorten(text: str, limit: int) -> str:
    """*text* on one line, cut to *limit* characters with an ellipsis; 0 means no limit."""
    text = " ".join(text.split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def day_heading(value: date, today: date) -> str:
    offset = (value - today).days
    if offset == 0:
        return "Today"
    if offset == 1:
        return "Tomorrow"
    return f"{_WEEKDAYS[value.weekday()]} {value.day} {_MONTHS[value.month - 1]}"


def group_by_day(events: Iterable[CalEvent], today: date, days: int) -> list[Day]:
    """The window's days that have events, in order.

    An all-day event appears on every day it covers. A timed event appears once: under the
    day it starts, or under today if it began earlier and is still running. Events that
    ended before today (a cache from an earlier day) appear nowhere.
    """
    events = list(events)
    window_start = day_start(today)
    result: list[Day] = []
    for offset in range(days):
        current = today + timedelta(days=offset)
        current_start = day_start(current)
        current_end = current_start + timedelta(days=1)
        whole_days = sorted(
            (e for e in events if e.all_day and e.start < current_end and e.end > current_start),
            key=lambda e: (e.start, e.subject),
        )
        timed = sorted(
            (
                e
                for e in events
                if not e.all_day and e.end > window_start and max(e.start, window_start).date() == current
            ),
            key=lambda e: (e.start, e.end, e.subject),
        )
        if whole_days or timed:
            result.append(Day(current, tuple(whole_days), tuple(timed)))
    return result


def _trim(url: str) -> str:
    return url.rstrip(_TRAILING)


def find_join_url(text: str) -> str:
    """The first Teams, Zoom or Google Meet link in *text*, unwrapped from Safe Links."""
    if not text:
        return ""
    for wrapped in _SAFELINKS_RE.findall(text):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(wrapped).query)
        target = query.get("url", [""])[0]
        match = _JOIN_RE.match(target)
        if match:
            return _trim(match.group(0))
    match = _JOIN_RE.search(text)
    return _trim(match.group(0)) if match else ""


def format_status(snapshot: Snapshot, now: datetime, time_format: str = "%H:%M") -> str:
    """The popup's status line; the tooltip repeats it for a stale reading."""
    if snapshot.fetched_at is None:
        return "Outlook unavailable" if snapshot.status == "error" else "Outlook closed"
    when = snapshot.fetched_at.strftime(time_format)
    if snapshot.fetched_at.date() != now.date():
        when = f"{snapshot.fetched_at.day} {_MONTHS[snapshot.fetched_at.month - 1]} {when}"
    if snapshot.status == "live":
        return f"updated {when}"
    if snapshot.status == "error":
        return f"Outlook unavailable · cached {when}"
    return f"Outlook closed · cached {when}"


def snapshot_to_cache(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
        "events": [event.to_dict() for event in snapshot.events],
    }


def snapshot_from_cache(data: Any) -> Snapshot | None:
    """A cached snapshot, marked stale; None unless *data* is a cache this version wrote."""
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    try:
        events = tuple(CalEvent.from_dict(item) for item in data.get("events") or [])
        fetched = data.get("fetched_at")
        fetched_at = datetime.fromisoformat(fetched) if fetched else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return Snapshot(events, fetched_at, "stale")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_agenda -v`
Expected: `Ran 35 tests` … `OK`.

- [ ] **Step 5: Lint**

Run:
```powershell
$py = "D:\Programming\yasb\.venv\Scripts\python.exe"; $f = "src/core/widgets/services/outlook_calendar/agenda.py", "tests/test_outlook_calendar_agenda.py"
& $py -m ruff format @f; & $py -m ruff check --fix @f; & $py -m ruff check @f
```
Expected: the last command prints `All checks passed!`. Re-run the tests if `ruff format` changed anything.

- [ ] **Step 6: Commit**

```powershell
git add src/core/widgets/services/outlook_calendar/agenda.py tests/test_outlook_calendar_agenda.py
git commit -m "wip(outlook_calendar): agenda logic"
```

---

### Task 2: COM source

**Files:**
- Create: `src/core/widgets/services/outlook_calendar/outlook.py`
- Test: `tests/test_outlook_calendar_outlook.py`

**Interfaces:**
- Consumes from Task 1: `CalEvent`, `RESPONSE_DECLINED`, `day_start(d)`, `find_join_url(text)`.
- Produces:
  - `class OutlookNotRunning(Exception)`
  - `MAX_ITEMS = 500`
  - `outlook_time(value: datetime) -> str`
  - `fetch(now: datetime, days: int, scan_body: bool = True, application=None) -> list[CalEvent]`. It raises `OutlookNotRunning`, or `pywintypes.com_error` for any other COM failure. The caller has already initialised COM on its thread.
  - `open_event(entry_id: str, store_id: str, start: datetime, recurring: bool, application=None) -> None`. It initialises COM itself and logs failures instead of raising.
  - `open_event_in_background(event: CalEvent) -> threading.Thread`
  - `open_calendar() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outlook_calendar_outlook.py`:

```python
"""Tests for the Outlook COM source, against a fake Outlook object model.

The fakes follow the real one where it matters: Start and End come back as local wall time
labelled GMT, Restrict sees whether IncludeRecurrences was already set, and Body counts its
reads, since reading it is the access Outlook's security prompt would guard.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pywintypes  # noqa: E402

from core.widgets.services.outlook_calendar import outlook  # noqa: E402
from core.widgets.services.outlook_calendar.agenda import CalEvent  # noqa: E402
from core.widgets.services.outlook_calendar.outlook import (  # noqa: E402
    MAX_ITEMS,
    OutlookNotRunning,
    fetch,
    open_calendar,
    open_event,
    open_event_in_background,
    outlook_time,
)

NOW = datetime(2026, 10, 1, 9, 0)
GMT = timezone(timedelta(0), "GMT Standard Time")
ZOOM = "https://us02web.zoom.us/j/81234567890?pwd=abcDEF123"
TEAMS_NEW = "https://teams.microsoft.com/meet/23456789012?p=AbCdEf"


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


def com_error(hresult: int, text: str = "") -> pywintypes.com_error:
    return pywintypes.com_error(hresult, text, None, None)


class FakeItem:
    def __init__(
        self,
        start,
        end,
        subject="Meeting",
        location="",
        body="",
        all_day=False,
        busy=2,
        response=3,
        meeting_status=0,
        entry_id="E1",
        recurring=False,
        broken=False,
    ):
        # Outlook hands back local wall time labelled with a GMT tzinfo.
        self.Start = start.replace(tzinfo=GMT)
        self.End = end.replace(tzinfo=GMT)
        self._subject = subject
        self.Location = location
        self._body = body
        self.body_reads = 0
        self.AllDayEvent = all_day
        self.BusyStatus = busy
        self.ResponseStatus = response
        self.MeetingStatus = meeting_status
        self.EntryID = entry_id
        self.IsRecurring = recurring
        self._broken = broken

    @property
    def Subject(self):
        if self._broken:
            raise com_error(-2147467259, "Unspecified error")
        return self._subject

    @property
    def Body(self):
        self.body_reads += 1
        return self._body


class FakeRestricted:
    def __init__(self, items):
        self._items = list(items)
        self._index = 0
        self.reads = 0

    def GetFirst(self):
        self._index = 0
        return self._current()

    def GetNext(self):
        self._index += 1
        return self._current()

    def _current(self):
        if self._index < len(self._items):
            self.reads += 1
            return self._items[self._index]
        return None


class FakeItems:
    def __init__(self, items):
        self._items = items
        self.IncludeRecurrences = False
        self.calls = []
        self.query = None
        self.restricted = None

    def Sort(self, key):
        self.calls.append(("Sort", key, self.IncludeRecurrences))

    def Restrict(self, query):
        self.calls.append(("Restrict", self.IncludeRecurrences))
        self.query = query
        self.restricted = FakeRestricted(self._items)
        return self.restricted


class FakeOutlook:
    def __init__(self, items):
        self.items = FakeItems(items)
        self.folder = mock.Mock(StoreID="S1", Items=self.items)
        self.namespace = mock.Mock()
        self.namespace.GetDefaultFolder.return_value = self.folder

    def GetNamespace(self, name):
        assert name == "MAPI"
        return self.namespace


class FetchTests(unittest.TestCase):
    def fetch(self, items, **kwargs):
        app = FakeOutlook(items)
        return fetch(NOW, 7, application=app, **kwargs), app

    def test_converts_items_to_naive_local_events(self):
        item = FakeItem(
            at(1, 9, 30),
            at(1, 11, 30),
            "Vendor review",
            location="Room 4B",
            busy=1,
            response=5,
            meeting_status=3,
            entry_id="E9",
            recurring=True,
        )
        events, app = self.fetch([item])
        expected = CalEvent(
            start=at(1, 9, 30),
            end=at(1, 11, 30),
            subject="Vendor review",
            location="Room 4B",
            busy=1,
            response=5,
            entry_id="E9",
            store_id="S1",
            recurring=True,
        )
        self.assertEqual(events, [expected])
        self.assertIsNone(events[0].start.tzinfo)
        app.namespace.GetDefaultFolder.assert_called_once_with(9)

    def test_sorts_before_expanding_recurrences_and_restricts_to_the_window(self):
        _, app = self.fetch([])
        self.assertEqual(app.items.calls, [("Sort", "[Start]", False), ("Restrict", True)])
        self.assertEqual(
            app.items.query,
            f"[Start] < '{outlook_time(at(8, 0))}' AND [End] > '{outlook_time(at(1, 0))}'",
        )

    def test_drops_declined_and_cancelled_meetings(self):
        events, _ = self.fetch(
            [
                FakeItem(at(1, 10), at(1, 11), "Declined", response=4),
                FakeItem(at(1, 11), at(1, 12), "Cancelled", meeting_status=5),
                FakeItem(at(1, 12), at(1, 13), "Cancelled invite", meeting_status=7),
                FakeItem(at(1, 14), at(1, 15), "Kept"),
            ]
        )
        self.assertEqual([e.subject for e in events], ["Kept"])

    def test_stops_at_the_window_end(self):
        items = [
            FakeItem(at(1, 10), at(1, 11), "Inside"),
            FakeItem(at(8, 0), at(8, 1), "At the end"),
            FakeItem(at(9, 10), at(9, 11), "After"),
        ]
        events, app = self.fetch(items)
        self.assertEqual([e.subject for e in events], ["Inside"])
        self.assertEqual(app.items.restricted.reads, 2)

    def test_drops_items_that_ended_before_today(self):
        events, _ = self.fetch(
            [
                FakeItem(datetime(2026, 9, 30, 23), at(1, 0), "Ended at midnight"),
                FakeItem(datetime(2026, 9, 30, 23), at(1, 1), "Overnight"),
            ]
        )
        self.assertEqual([e.subject for e in events], ["Overnight"])

    def test_caps_the_walk(self):
        events, _ = self.fetch([FakeItem(at(1, 10), at(1, 11), f"Event {i}") for i in range(MAX_ITEMS + 100)])
        self.assertEqual(len(events), MAX_ITEMS)

    def test_skips_an_unreadable_item(self):
        events, _ = self.fetch(
            [FakeItem(at(1, 10), at(1, 11), broken=True), FakeItem(at(1, 12), at(1, 13), "Readable")]
        )
        self.assertEqual([e.subject for e in events], ["Readable"])

    def test_join_url_prefers_location_then_body(self):
        in_location = FakeItem(at(1, 10), at(1, 11), location=f"Zoom {ZOOM}", body=TEAMS_NEW)
        in_body = FakeItem(at(1, 12), at(1, 13), location="Room 4B", body=f"Join: {TEAMS_NEW}")
        events, _ = self.fetch([in_location, in_body])
        self.assertEqual([e.join_url for e in events], [ZOOM, TEAMS_NEW])
        self.assertEqual(in_location.body_reads, 0)

    def test_scan_body_off_never_reads_the_body(self):
        item = FakeItem(at(1, 10), at(1, 11), body=TEAMS_NEW)
        events, _ = self.fetch([item], scan_body=False)
        self.assertEqual(events[0].join_url, "")
        self.assertEqual(item.body_reads, 0)


class AttachTests(unittest.TestCase):
    def attach_fails(self, hresult):
        return mock.patch.object(outlook.win32com.client, "GetActiveObject", side_effect=com_error(hresult))

    def test_not_running(self):
        with self.attach_fails(-2147221021), self.assertRaises(OutlookNotRunning):
            fetch(NOW, 7)

    def test_not_installed_counts_as_not_running(self):
        with self.attach_fails(-2147221005), self.assertRaises(OutlookNotRunning):
            fetch(NOW, 7)

    def test_busy_outlook_is_an_error_not_closed(self):
        with self.attach_fails(-2147418111), self.assertRaises(pywintypes.com_error):
            fetch(NOW, 7)

    def test_never_dispatches(self):
        with (
            self.attach_fails(-2147221021),
            mock.patch.object(outlook.win32com.client, "Dispatch") as dispatch,
            self.assertRaises(OutlookNotRunning),
        ):
            fetch(NOW, 7)
        dispatch.assert_not_called()


class OutlookTimeTests(unittest.TestCase):
    def test_keeps_the_wall_time(self):
        text = outlook_time(datetime(2026, 10, 1, 13, 45))
        self.assertIn("2026", text)
        self.assertTrue("13:45" in text or "1:45" in text, text)


class OpenEventTests(unittest.TestCase):
    def setUp(self):
        for target, name in (
            (outlook.pythoncom, "CoInitialize"),
            (outlook.pythoncom, "CoUninitialize"),
            (outlook, "_allow_foreground"),
        ):
            patcher = mock.patch.object(target, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = mock.Mock()
        self.item = self.app.GetNamespace.return_value.GetItemFromID.return_value

    def test_opens_a_single_event(self):
        open_event("E1", "S1", at(1, 10), False, application=self.app)
        self.app.GetNamespace.return_value.GetItemFromID.assert_called_once_with("E1", "S1")
        self.item.Display.assert_called_once_with()
        self.item.GetRecurrencePattern.assert_not_called()

    def test_opens_the_occurrence_of_a_recurring_event(self):
        get_occurrence = self.item.GetRecurrencePattern.return_value.GetOccurrence
        open_event("E1", "S1", at(1, 10), True, application=self.app)
        (stamp,), _ = get_occurrence.call_args
        self.assertEqual((stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute), (2026, 10, 1, 10, 0))
        get_occurrence.return_value.Display.assert_called_once_with()
        self.item.Display.assert_not_called()

    def test_falls_back_to_the_series(self):
        self.item.GetRecurrencePattern.return_value.GetOccurrence.side_effect = com_error(-2147352567)
        open_event("E1", "S1", at(1, 10), True, application=self.app)
        self.item.Display.assert_called_once_with()

    def test_failure_is_logged_not_raised(self):
        self.app.GetNamespace.return_value.GetItemFromID.side_effect = com_error(-2147221233, "Not found")
        with self.assertLogs("outlook_calendar", "WARNING"):
            open_event("E1", "S1", at(1, 10), False, application=self.app)

    def test_in_background(self):
        event = CalEvent(start=at(1, 10), end=at(1, 11), subject="Sync", entry_id="E1", store_id="S1", recurring=True)
        with mock.patch.object(outlook, "open_event") as opener:
            open_event_in_background(event).join(5)
        opener.assert_called_once_with("E1", "S1", at(1, 10), True)

    def test_open_calendar(self):
        with mock.patch.object(outlook, "shell_open") as shell_open:
            open_calendar()
        shell_open.assert_called_once_with("outlook.exe", parameters="/select outlook:calendar")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_outlook -v`
Expected: `FAILED (errors=1)`, with `ModuleNotFoundError: No module named 'core.widgets.services.outlook_calendar.outlook'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/widgets/services/outlook_calendar/outlook.py`:

```python
"""Reads the default Outlook calendar over COM.

Only classic Outlook (OUTLOOK.EXE) has a COM interface; new Outlook (olk.exe) has none.
``fetch`` attaches to an Outlook that is already running and never starts one: yasb starts
at login, and a status bar that launched the mail client would bring it back every time it
was closed. ``open_event`` and ``open_calendar`` answer a click, so starting Outlook there is
the point.

Everything here blocks on Outlook, so it runs off the UI thread. ``fetch``'s caller has
initialised COM on its thread; ``open_event`` always runs on a thread of its own and does so
itself.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from datetime import UTC, datetime, timedelta

import pythoncom
import pywintypes
import win32api
import win32com.client

from core.utils.shell_utils import shell_open
from core.widgets.services.outlook_calendar.agenda import RESPONSE_DECLINED, CalEvent, day_start, find_join_url

logger = logging.getLogger("outlook_calendar")

OL_FOLDER_CALENDAR = 9
MAX_ITEMS = 500
_CANCELLED = (5, 7)  # olMeetingCanceled, olMeetingReceivedAndCanceled
# MK_E_UNAVAILABLE: not in the Running Object Table, so not running in this session (or
# running at another integrity level). CO_E_CLASSSTRING: classic Outlook is not installed.
_NOT_RUNNING = (-2147221021, -2147221005)
_LOCALE_USER_DEFAULT = 0x0400
_DATE_SHORTDATE = 0x1
_TIME_NOSECONDS = 0x2
_ASFW_ANY = -1


class OutlookNotRunning(Exception):
    """Classic Outlook is not running in this session."""


def _attach():
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except pywintypes.com_error as error:
        if error.hresult in _NOT_RUNNING:
            raise OutlookNotRunning() from error
        raise


def _com_time(value: datetime):
    """*value*'s wall time as a COM time.

    pywintypes treats a naive datetime as local time and shifts it to UTC on the way in;
    labelling the wall time UTC makes it pass through unchanged.
    """
    return pywintypes.Time(value.replace(tzinfo=UTC))


def outlook_time(value: datetime) -> str:
    """*value* the way Items.Restrict parses a date: the user's short date and time format."""
    stamp = _com_time(value)
    date_text = win32api.GetDateFormat(_LOCALE_USER_DEFAULT, _DATE_SHORTDATE, stamp, None)
    time_text = win32api.GetTimeFormat(_LOCALE_USER_DEFAULT, _TIME_NOSECONDS, stamp, None)
    return f"{date_text} {time_text}"


def _local(value: datetime) -> datetime:
    """Outlook returns local wall time labelled with a GMT tzinfo: keep the wall time."""
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)


def _skipped(item) -> bool:
    return int(item.ResponseStatus) == RESPONSE_DECLINED or int(item.MeetingStatus) in _CANCELLED


def _event(item, store_id: str, scan_body: bool) -> CalEvent:
    location = str(item.Location or "")
    join_url = find_join_url(location)
    if not join_url and scan_body:
        join_url = find_join_url(str(item.Body or ""))
    return CalEvent(
        start=_local(item.Start),
        end=_local(item.End),
        subject=str(item.Subject or ""),
        location=location,
        all_day=bool(item.AllDayEvent),
        busy=int(item.BusyStatus),
        response=int(item.ResponseStatus),
        entry_id=str(item.EntryID),
        store_id=store_id,
        recurring=bool(item.IsRecurring),
        join_url=join_url,
    )


def fetch(now: datetime, days: int, scan_body: bool = True, application=None) -> list[CalEvent]:
    """The default calendar's events from today 00:00 for *days* days, soonest first.

    Raises ``OutlookNotRunning`` when there is no Outlook to attach to. Any other COM failure
    (Outlook busy behind a modal dialog, say) propagates as ``pywintypes.com_error``.
    """
    app = application if application is not None else _attach()
    folder = app.GetNamespace("MAPI").GetDefaultFolder(OL_FOLDER_CALENDAR)
    store_id = str(folder.StoreID)
    window_start = day_start(now.date())
    window_end = window_start + timedelta(days=days)
    # Every access to folder.Items returns a new collection, so keep one. Sorting must come
    # before IncludeRecurrences, or the recurrences are not expanded in start order.
    items = folder.Items
    items.Sort("[Start]")
    items.IncludeRecurrences = True
    found = items.Restrict(f"[Start] < '{outlook_time(window_end)}' AND [End] > '{outlook_time(window_start)}'")
    events: list[CalEvent] = []
    seen = 0
    item = found.GetFirst()
    # Count is meaningless once recurrences are expanded, so walk until past the window.
    while item is not None and seen < MAX_ITEMS:
        seen += 1
        try:
            if _local(item.Start) >= window_end:
                break
            if not _skipped(item) and _local(item.End) > window_start:
                events.append(_event(item, store_id, scan_body))
        except (pywintypes.com_error, AttributeError, TypeError, ValueError) as error:
            logger.debug("outlook calendar: skipped an unreadable item: %s", error)
        item = found.GetNext()
    return events


def _allow_foreground() -> None:
    """Let Outlook take the foreground; Windows only allows it if the foreground process says so."""
    ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)


def open_event(entry_id: str, store_id: str, start: datetime, recurring: bool, application=None) -> None:
    """Open one event in Outlook, starting Outlook if needed. Blocks; run it on its own thread."""
    pythoncom.CoInitialize()
    try:
        app = application if application is not None else win32com.client.Dispatch("Outlook.Application")
        item = app.GetNamespace("MAPI").GetItemFromID(entry_id, store_id)
        if recurring:
            try:
                item = item.GetRecurrencePattern().GetOccurrence(_com_time(start))
            except pywintypes.com_error:
                # A moved occurrence is an exception with no slot at its original time;
                # opening the series is the next best thing.
                logger.debug("outlook calendar: no occurrence at %s, opening the series", start)
        _allow_foreground()
        item.Display()
    except pywintypes.com_error as error:
        logger.warning("outlook calendar: could not open the event: %s", error)
    finally:
        pythoncom.CoUninitialize()


def open_event_in_background(event: CalEvent) -> threading.Thread:
    thread = threading.Thread(
        target=open_event,
        args=(event.entry_id, event.store_id, event.start, event.recurring),
        daemon=True,
        name="outlook-calendar-open",
    )
    thread.start()
    return thread


def open_calendar() -> None:
    """Show Outlook's calendar, starting Outlook if needed."""
    shell_open("outlook.exe", parameters="/select outlook:calendar")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_outlook tests.test_outlook_calendar_agenda -v`
Expected: `Ran 55 tests` … `OK`.

- [ ] **Step 5: Live read-only smoke test against the real Outlook**

This reads the user's calendar but prints no subjects or locations. Write `<scratchpad>\smoke_fetch.py`:

```python
"""Read-only: fetch the real calendar through the new module. Prints no subjects."""

import sys
from datetime import datetime

sys.path.insert(0, sys.argv[1])

import pythoncom  # noqa: E402

from core.widgets.services.outlook_calendar.outlook import OutlookNotRunning, fetch  # noqa: E402

pythoncom.CoInitialize()
try:
    events = fetch(datetime.now(), 7)
except OutlookNotRunning:
    print("Outlook is not running")
    raise SystemExit(0)
print("events:", len(events))
for e in events:
    kind = "all-day" if e.all_day else "timed"
    print(e.start, e.end, kind, "busy", e.busy, "response", e.response, "tentative", e.tentative,
          "subject chars", len(e.subject), "join", bool(e.join_url), "tz", e.start.tzinfo)
pythoncom.CoUninitialize()
```

Run: `& "D:\Programming\yasb\.venv\Scripts\python.exe" "<scratchpad>\smoke_fetch.py" "<wt>\src"`
Expected, if Outlook is running: an `events:` count, each start and end in local wall time, and `tz None` on every line. Run on 2026-10-01, it must list the 09:30–11:30 event as `timed busy 1 response 5 tentative True`, as the design probe saw. If Outlook is not running it prints `Outlook is not running`; start Outlook and re-run. If any time comes out shifted by 7 hours, stop: the `_local` / `_com_time` handling is wrong.

- [ ] **Step 6: Lint and commit**

```powershell
$py = "D:\Programming\yasb\.venv\Scripts\python.exe"; $f = "src/core/widgets/services/outlook_calendar/outlook.py", "tests/test_outlook_calendar_outlook.py"
& $py -m ruff format @f; & $py -m ruff check --fix @f; & $py -m ruff check @f
git add @f
git commit -m "wip(outlook_calendar): COM source"
```
Expected: `All checks passed!` before the commit.

---

### Task 3: Shared service

**Files:**
- Create: `src/core/widgets/services/outlook_calendar/service.py`
- Test: `tests/test_outlook_calendar_service.py`

**Interfaces:**
- Consumes from Task 1: `Snapshot`, `snapshot_from_cache`, `snapshot_to_cache`. From Task 2: `fetch`, `OutlookNotRunning`.
- Produces:
  - `CACHE_FILE = "outlook_calendar.json"`, `FAILURES_BEFORE_ERROR = 3`, `TICK_MS = 30_000`
  - `cache_path() -> Path`, `load_cache(path) -> Snapshot | None`, `write_cache(path, snapshot) -> None`
  - `class _FetchWorker(QThread)`, whose signal `done(object, str)` carries `(list[CalEvent] | None, "" | "closed" | "error")`
  - `class OutlookCalendarService(QObject)`:
    - signal `updated()`
    - attribute `snapshot: Snapshot`
    - `get_instance(days: int, update_interval_s: int, scan_body: bool)` (classmethod)
    - `refresh_now()`, `release()`
    - `__init__(days, update_interval_s, scan_body, cache_file: Path | None = None)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outlook_calendar_service.py`:

```python
"""Tests for the shared Outlook calendar service: the cache, the snapshot states, and one
service shared by every bar. Polling is switched off and results are fed in directly."""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.widgets.services.outlook_calendar import service as service_module  # noqa: E402
from core.widgets.services.outlook_calendar.agenda import CalEvent, Snapshot  # noqa: E402
from core.widgets.services.outlook_calendar.outlook import OutlookNotRunning  # noqa: E402
from core.widgets.services.outlook_calendar.service import (  # noqa: E402
    OutlookCalendarService,
    load_cache,
    write_cache,
)

NOW = datetime(2026, 10, 1, 9, 0)
FETCHED = datetime(2026, 10, 1, 8, 12)
EVENT = CalEvent(start=datetime(2026, 10, 1, 14), end=datetime(2026, 10, 1, 15), subject="Weekly sync")


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name) / "outlook_calendar.json"
        patcher = mock.patch.object(OutlookCalendarService, "refresh_now")
        self.refresh = patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, cache_file: Path | None = None) -> OutlookCalendarService:
        service = OutlookCalendarService(7, 300, True, cache_file=cache_file or self.cache)
        service._now = lambda: NOW
        self.addCleanup(self.stop, service)
        return service

    @staticmethod
    def stop(service: OutlookCalendarService) -> None:
        service._timer.stop()
        service._tick.stop()
        service.deleteLater()


class SnapshotStateTests(ServiceTestCase):
    def test_starts_closed_without_a_cache(self):
        service = self.make()
        self.assertEqual(service.snapshot, Snapshot())
        self.refresh.assert_called_once_with()

    def test_starts_from_the_cache_marked_stale(self):
        write_cache(self.cache, Snapshot((EVENT,), FETCHED, "live"))
        self.assertEqual(self.make().snapshot, Snapshot((EVENT,), FETCHED, "stale"))

    def test_corrupt_cache_is_ignored(self):
        self.cache.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.make().snapshot, Snapshot())

    def test_success_goes_live_and_is_cached(self):
        service = self.make()
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "live"))
        self.assertEqual(load_cache(self.cache), Snapshot((EVENT,), NOW, "stale"))

    def test_outlook_closing_keeps_the_events(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "closed")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "stale"))

    def test_closed_with_nothing_cached(self):
        service = self.make()
        service._on_done(None, "closed")
        self.assertEqual(service.snapshot, Snapshot())

    def test_three_failures_in_a_row_mark_an_error(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "error")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot.status, "live")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "error"))
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot.status, "live")

    def test_closed_resets_the_failure_count(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "error")
        service._on_done(None, "error")
        service._on_done(None, "closed")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot.status, "stale")

    def test_every_result_emits_updated(self):
        service = self.make()
        seen = []
        service.updated.connect(lambda: seen.append(service.snapshot.status))
        service._on_done(None, "closed")
        service._on_done([EVENT], "")
        self.assertEqual(seen, ["closed", "live"])

    def test_unwritable_cache_is_not_fatal(self):
        service = self.make(cache_file=self.cache.parent / "missing" / "outlook_calendar.json")
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot.status, "live")


class SharedInstanceTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(service_module, "cache_path", return_value=self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, OutlookCalendarService, "_instance", None)

    def get(self, *args) -> OutlookCalendarService:
        service = OutlookCalendarService.get_instance(*args)
        self.addCleanup(self.stop, service)
        return service

    def test_bars_share_one_service_that_widens(self):
        first = self.get(7, 300, False)
        self.refresh.reset_mock()
        second = self.get(14, 120, True)
        self.assertIs(first, second)
        self.assertEqual((first._days, first._scan_body, first._timer.interval()), (14, True, 120_000))
        self.refresh.assert_called_once_with()

    def test_a_narrower_bar_changes_nothing(self):
        first = self.get(14, 120, True)
        self.refresh.reset_mock()
        self.get(7, 300, False)
        self.assertEqual((first._days, first._scan_body, first._timer.interval()), (14, True, 120_000))
        self.refresh.assert_not_called()

    def test_released_by_the_last_bar(self):
        first = self.get(7, 300, True)
        self.get(7, 300, True)
        first.release()
        self.assertIs(OutlookCalendarService._instance, first)
        first.release()
        self.assertIsNone(OutlookCalendarService._instance)


class WorkerTests(unittest.TestCase):
    def run_worker(self, **fetch_patch) -> list[tuple]:
        worker = service_module._FetchWorker(7, True)
        results = []
        worker.done.connect(lambda events, failure: results.append((events, failure)))
        with mock.patch.object(service_module, "fetch", **fetch_patch):
            worker.run()
        return results

    def test_success(self):
        self.assertEqual(self.run_worker(return_value=[EVENT]), [([EVENT], "")])

    def test_not_running(self):
        self.assertEqual(self.run_worker(side_effect=OutlookNotRunning()), [(None, "closed")])

    def test_other_failure(self):
        with self.assertLogs("outlook_calendar", "WARNING"):
            results = self.run_worker(side_effect=RuntimeError("boom"))
        self.assertEqual(results, [(None, "error")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_service -v`
Expected: `FAILED (errors=1)`, with `ModuleNotFoundError: No module named 'core.widgets.services.outlook_calendar.service'`.

- [ ] **Step 3: Write the implementation**

Create `src/core/widgets/services/outlook_calendar/service.py`:

```python
"""Shared poller for the Outlook calendar widget.

One service runs per process, however many bars show the widget, so a bar on every monitor
still means one COM poll. Instances are reference-counted and released when the last widget
goes away (mirrors ``AnimeAiringService``). A widget asking for a longer window, a shorter
interval or body scanning widens the one service rather than starting another.

The last successful read is cached in the YASB data folder. At login the bar counts down
from it before Outlook is running, and while Outlook is closed it keeps counting down from
it, marked stale.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pythoncom
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.utils.system import app_data_path
from core.widgets.services.outlook_calendar.agenda import Snapshot, snapshot_from_cache, snapshot_to_cache
from core.widgets.services.outlook_calendar.outlook import OutlookNotRunning, fetch

logger = logging.getLogger("outlook_calendar")

CACHE_FILE = "outlook_calendar.json"
FAILURES_BEFORE_ERROR = 3
TICK_MS = 30_000


def cache_path() -> Path:
    return app_data_path(CACHE_FILE)


def load_cache(path: Path) -> Snapshot | None:
    try:
        with open(path, encoding="utf-8") as cache_file:
            data = json.load(cache_file)
    except (OSError, ValueError) as error:
        logger.debug("outlook calendar: no usable cache: %s", error)
        return None
    snapshot = snapshot_from_cache(data)
    if snapshot is None:
        logger.debug("outlook calendar: ignored a cache this version did not write")
    return snapshot


def write_cache(path: Path, snapshot: Snapshot) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as cache_file:
            json.dump(snapshot_to_cache(snapshot), cache_file)
        os.replace(temporary, path)
    except OSError as error:
        logger.debug("outlook calendar: failed to write the cache: %s", error)


class _FetchWorker(QThread):
    """Reads Outlook off the UI thread. ``done`` carries (events or None, failure kind)."""

    done = pyqtSignal(object, str)

    def __init__(self, days: int, scan_body: bool, parent: QObject | None = None):
        super().__init__(parent)
        self._days = days
        self._scan_body = scan_body

    def run(self) -> None:
        pythoncom.CoInitialize()
        try:
            events = fetch(datetime.now(), self._days, self._scan_body)
        except OutlookNotRunning:
            self.done.emit(None, "closed")
        except Exception as error:  # a widget must never take the bar down
            logger.warning("outlook calendar: reading Outlook failed: %s", error)
            self.done.emit(None, "error")
        else:
            self.done.emit(events, "")
        finally:
            pythoncom.CoUninitialize()


class OutlookCalendarService(QObject):
    """Polls Outlook and holds the latest ``Snapshot``."""

    # Emitted after every poll result and every 30 seconds, so widgets re-derive countdowns.
    updated = pyqtSignal()

    _instance: ClassVar[OutlookCalendarService | None] = None

    @classmethod
    def get_instance(cls, days: int, update_interval_s: int, scan_body: bool) -> OutlookCalendarService:
        instance = cls._instance
        if instance is None:
            instance = cls(days, update_interval_s, scan_body)
            cls._instance = instance
        else:
            instance._widen(days, update_interval_s, scan_body)
        instance._refcount += 1
        return instance

    def __init__(self, days: int, update_interval_s: int, scan_body: bool, cache_file: Path | None = None):
        super().__init__()
        self._refcount = 0
        self._days = int(days)
        self._scan_body = bool(scan_body)
        self._failures = 0
        self._worker: _FetchWorker | None = None
        self._cache_path = cache_file if cache_file is not None else cache_path()
        self.snapshot: Snapshot = load_cache(self._cache_path) or Snapshot()

        self._timer = QTimer(self)
        self._timer.setInterval(max(int(update_interval_s), 60) * 1000)
        self._timer.timeout.connect(self.refresh_now)
        self._timer.start()
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self.updated)
        self._tick.start()
        self.refresh_now()

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _widen(self, days: int, update_interval_s: int, scan_body: bool) -> None:
        changed = False
        if days > self._days:
            self._days = int(days)
            changed = True
        if scan_body and not self._scan_body:
            self._scan_body = True
            changed = True
        interval_ms = max(int(update_interval_s), 60) * 1000
        if interval_ms < self._timer.interval():
            self._timer.setInterval(interval_ms)
        if changed:
            self.refresh_now()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        self._timer.stop()
        self._tick.stop()
        if OutlookCalendarService._instance is self:
            OutlookCalendarService._instance = None
        if self._worker is not None and self._worker.isRunning():
            # Never block the UI thread on Outlook during a config reload.
            self._worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def refresh_now(self) -> None:
        if self._worker is not None:
            return
        worker = _FetchWorker(self._days, self._scan_body, self)
        worker.done.connect(self._on_done)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _on_done(self, events, failure: str) -> None:
        if events is not None:
            self._failures = 0
            self.snapshot = Snapshot(tuple(events), self._now(), "live")
            write_cache(self._cache_path, self.snapshot)
        elif failure == "closed":
            self._failures = 0
            self.snapshot = replace(self.snapshot, status="stale" if self.snapshot.fetched_at else "closed")
        else:
            self._failures += 1
            if self._failures >= FAILURES_BEFORE_ERROR:
                self.snapshot = replace(self.snapshot, status="error")
        self.updated.emit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_service tests.test_outlook_calendar_outlook tests.test_outlook_calendar_agenda -v`
Expected: `Ran 71 tests` … `OK`.

- [ ] **Step 5: Lint and commit**

```powershell
$py = "D:\Programming\yasb\.venv\Scripts\python.exe"; $f = "src/core/widgets/services/outlook_calendar/service.py", "tests/test_outlook_calendar_service.py"
& $py -m ruff format @f; & $py -m ruff check --fix @f; & $py -m ruff check @f
git add @f
git commit -m "wip(outlook_calendar): shared service"
```
Expected: `All checks passed!` before the commit.

---

### Task 4: Config and widget

**Files:**
- Create: `src/core/validation/widgets/yasb/outlook_calendar.py`
- Create: `src/core/widgets/yasb/outlook_calendar.py`
- Test: `tests/test_outlook_calendar_widget.py`

**Interfaces:**
- Consumes from Task 1:
  - `CalEvent`, `day_heading`, `day_start`, `format_countdown`, `format_status`, `format_time_range`
  - `group_by_day`, `row_status`, `select_event`, `shorten`, `today_count`
- Consumes from Task 2: `open_calendar`, `open_event_in_background`.
- Consumes from Task 3: `OutlookCalendarService.get_instance(days, update_interval_s, scan_body)`, plus `.snapshot`, `.updated`, `.refresh_now()` and `.release()`.
- Produces:
  - widget type `yasb.outlook_calendar.OutlookCalendarWidget`
  - `OutlookCalendarConfig`
  - widget methods the tests drive: `_update_label()`, `_toggle_label()`, `_toggle_card()`, `_fill_popup(layout)`, `_now()`
  - module helper `fit_to_width(widget)`, which Task 5's render script uses
  - module helper `_open_url(url)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outlook_calendar_widget.py`:

```python
"""Widget tests for the Outlook calendar: config, bar label states, tooltip and the popup.

The widget gets a stub service holding a snapshot, so no COM is touched. The popup body is
filled into a plain host frame, so no popup window is shown.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pydantic import ValidationError  # noqa: E402
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QPushButton, QVBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.validation.widgets.yasb.outlook_calendar import OutlookCalendarConfig  # noqa: E402
from core.widgets.services.outlook_calendar.agenda import CalEvent, Snapshot  # noqa: E402
from core.widgets.yasb import outlook_calendar as widget_module  # noqa: E402
from core.widgets.yasb.outlook_calendar import OutlookCalendarWidget  # noqa: E402

NOW = datetime(2026, 10, 1, 9, 0)
FETCHED = datetime(2026, 10, 1, 8, 12)
ZOOM = "https://us02web.zoom.us/j/81234567890?pwd=abcDEF123"


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


def ev(start: datetime, end: datetime, subject: str = "Meeting", **fields) -> CalEvent:
    return CalEvent(start=start, end=end, subject=subject, **fields)


def all_day(first: int, last: int, subject: str = "Holiday") -> CalEvent:
    return ev(at(first, 0), at(last + 1, 0), subject, all_day=True)


def live(*events: CalEvent) -> Snapshot:
    return Snapshot(tuple(events), FETCHED, "live")


def press() -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def by_class(root: QWidget, cls: str) -> list[QWidget]:
    return [child for child in root.findChildren(QWidget) if cls in (child.property("class") or "").split()]


class StubService(QObject):
    updated = pyqtSignal()

    def __init__(self, snapshot: Snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.refreshes = 0

    def refresh_now(self):
        self.refreshes += 1

    def release(self):
        pass


class _FakePopup(QFrame):
    def __init__(self, parent, *args):
        super().__init__()

    def setPosition(self, **kwargs):
        pass

    def show(self):
        pass


class WidgetTestCase(unittest.TestCase):
    def make(self, snapshot: Snapshot, now: datetime = NOW, **options) -> OutlookCalendarWidget:
        self.stub = StubService(snapshot)
        config = OutlookCalendarConfig(**options)
        with mock.patch.object(widget_module.OutlookCalendarService, "get_instance", return_value=self.stub):
            widget = OutlookCalendarWidget(config)
        widget._now = lambda: now
        widget._update_label()
        self.addCleanup(widget.deleteLater)
        return widget

    @staticmethod
    def text(widget: OutlookCalendarWidget, alt: bool = False) -> str:
        return (widget._widgets_alt if alt else widget._widgets)[1].text()

    @staticmethod
    def classes(widget: OutlookCalendarWidget) -> list[str]:
        return (widget._widgets[1].property("class") or "").split()


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = OutlookCalendarConfig()
        self.assertEqual(
            (config.days, config.update_interval, config.soon_minutes, config.max_title_length, config.scan_body),
            (7, 300, 15, 20, True),
        )
        self.assertEqual(config.callbacks.on_middle, "open_outlook")

    def test_rejects_out_of_range(self):
        for options in ({"update_interval": 30}, {"days": 0}, {"days": 32}, {"soon_minutes": -1}):
            with self.assertRaises(ValidationError):
                OutlookCalendarConfig(**options)

    def test_rejects_unknown_options(self):
        with self.assertRaises(ValidationError):
            OutlookCalendarConfig(label_empty="x")


class LabelTests(WidgetTestCase):
    def test_counts_down_to_the_next_event(self):
        widget = self.make(live(ev(at(1, 14), at(1, 15), "Weekly sync"), ev(at(1, 11), at(1, 12), "Standup")))
        self.assertEqual(self.text(widget), "in 2h · Standup")
        self.assertEqual(self.classes(widget), ["label"])

    def test_ongoing(self):
        widget = self.make(live(ev(at(1, 8, 30), at(1, 9, 30), "Vendor review")))
        self.assertEqual(self.text(widget), "now · Vendor review")
        self.assertIn("ongoing", self.classes(widget))

    def test_soon_and_tentative(self):
        widget = self.make(live(ev(at(1, 9, 10), at(1, 9, 40), "Invite", busy=1, response=5)))
        self.assertEqual(self.text(widget), "in 10m · Invite")
        self.assertEqual(self.classes(widget), ["label", "soon", "tentative"])

    def test_soon_minutes_zero_turns_soon_off(self):
        widget = self.make(live(ev(at(1, 9, 10), at(1, 9, 40))), soon_minutes=0)
        self.assertNotIn("soon", self.classes(widget))

    def test_alt_label(self):
        widget = self.make(live(ev(at(1, 11), at(1, 12), "Standup")))
        widget._toggle_label()
        self.assertEqual(self.text(widget, alt=True), "11:00–12:00 · Standup")
        self.assertFalse(widget._widgets[1].isVisibleTo(widget))

    def test_title_is_shortened(self):
        widget = self.make(live(ev(at(1, 11), at(1, 12), "Quarterly planning")), max_title_length=10)
        self.assertEqual(self.text(widget), "in 2h · Quarterly…")

    def test_states_replace_the_template(self):
        cases = [
            (live(), "No events", "empty"),
            (Snapshot(), "Outlook closed", "closed"),
            (Snapshot((), None, "error"), "Outlook unavailable", "error"),
        ]
        for snapshot, text, state in cases:
            widget = self.make(snapshot)
            self.assertEqual(self.text(widget), text)
            self.assertIn(state, self.classes(widget))

    def test_custom_state_texts(self):
        self.assertEqual(self.text(self.make(live(), empty_text="Free")), "Free")
        self.assertEqual(self.text(self.make(Snapshot(), closed_text="No Outlook")), "No Outlook")

    def test_stale_reading_still_counts_down(self):
        widget = self.make(Snapshot((ev(at(1, 11), at(1, 12), "Standup"),), FETCHED, "stale"))
        self.assertEqual(self.text(widget), "in 2h · Standup")
        self.assertIn("stale", self.classes(widget))

    def test_cache_from_yesterday_shows_no_ended_events(self):
        yesterday = ev(datetime(2026, 9, 30, 14), datetime(2026, 9, 30, 15), "Yesterday")
        widget = self.make(Snapshot((yesterday,), datetime(2026, 9, 30, 8), "stale"))
        self.assertEqual(self.text(widget), "No events")
        self.assertEqual(self.classes(widget), ["label", "empty", "stale"])

    def test_days_limits_the_bar(self):
        widget = self.make(live(ev(at(3, 10), at(3, 11), "Saturday")), days=1)
        self.assertEqual(self.text(widget), "No events")

    def test_subject_is_plain_text(self):
        widget = self.make(live(ev(at(1, 11), at(1, 12), "<b>Budget</b> & {time}")), max_title_length=0)
        label = widget._widgets[1]
        self.assertEqual(label.text(), "in 2h · <b>Budget</b> & {time}")
        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)

    def test_today_count_placeholder(self):
        widget = self.make(
            live(ev(at(1, 11), at(1, 12)), ev(at(1, 14), at(1, 15))),
            label="<span>{icon}</span> {today_count} today",
        )
        self.assertEqual(self.text(widget), "2 today")


class TooltipTests(WidgetTestCase):
    def tooltip(self, snapshot: Snapshot, **options) -> str:
        with mock.patch.object(widget_module, "set_tooltip") as set_tooltip:
            self.make(snapshot, **options)
        return set_tooltip.call_args.args[1]

    def test_event_details(self):
        event = ev(at(1, 11), at(1, 12), "Budget & plan", location="Room <4B>", busy=1, response=5)
        self.assertEqual(
            self.tooltip(live(event)),
            "<strong>Budget &amp; plan</strong><br>Today · 11:00–12:00<br>Room &lt;4B&gt;<br>Tentative",
        )

    def test_stale_reading_says_so(self):
        text = self.tooltip(Snapshot((ev(at(1, 11), at(1, 12), "Standup"),), FETCHED, "stale"))
        self.assertTrue(text.endswith("<br>Outlook closed · cached 08:12"), text)

    def test_no_event(self):
        self.assertEqual(self.tooltip(Snapshot()), "Outlook closed")

    def test_tooltip_off(self):
        with mock.patch.object(widget_module, "set_tooltip") as set_tooltip:
            self.make(live(), tooltip=False)
        set_tooltip.assert_not_called()


class PopupTests(WidgetTestCase):
    def fill(self, widget: OutlookCalendarWidget) -> QFrame:
        host = QFrame()
        self.addCleanup(host.deleteLater)
        widget._fill_popup(QVBoxLayout(host))
        return host

    @staticmethod
    def texts(root: QWidget, cls: str) -> list[str]:
        return [label.text() for label in by_class(root, cls)]

    def test_groups_rows_by_day(self):
        snapshot = live(
            ev(at(1, 14), at(1, 15), "Weekly sync"),
            all_day(1, 1, "Founders day"),
            ev(at(1, 7), at(1, 8), "Gym"),
            ev(at(2, 10), at(2, 10, 30), "1:1"),
        )
        host = self.fill(self.make(snapshot))
        self.assertEqual(self.texts(host, "day-heading"), ["Today", "Tomorrow"])
        self.assertEqual(self.texts(host, "subject"), ["Founders day", "Gym", "Weekly sync", "1:1"])
        self.assertEqual(self.texts(host, "time"), ["all day", "07:00–08:00", "14:00–15:00", "10:00–10:30"])
        self.assertEqual(self.texts(host, "when"), ["ended", "in 5h"])
        self.assertEqual(self.texts(by_class(host, "header")[0], "status"), ["updated 08:12"])

    def test_row_marks(self):
        snapshot = live(
            ev(at(1, 7), at(1, 8), "Gym"),
            ev(at(1, 8, 30), at(1, 9, 30), "Review"),
            ev(at(1, 9, 10), at(1, 9, 40), "Invite", busy=1, response=5),
        )
        host = self.fill(self.make(snapshot))
        self.assertEqual(
            [row.property("class") for row in by_class(host, "event-row")],
            ["event-row past", "event-row ongoing", "event-row soon tentative"],
        )
        self.assertEqual(self.texts(host, "tag"), ["Tentative"])
        self.assertEqual(self.texts(host, "when"), ["ended", "now", "in 10m"])

    def test_join_button_only_with_a_link(self):
        snapshot = live(ev(at(1, 11), at(1, 12), "Zoom call", join_url=ZOOM), ev(at(1, 14), at(1, 15), "In person"))
        host = self.fill(self.make(snapshot))
        buttons = host.findChildren(QPushButton)
        self.assertEqual([button.text() for button in buttons], ["Join"])
        with mock.patch.object(widget_module, "_open_url") as open_url:
            buttons[0].click()
        open_url.assert_called_once_with(ZOOM)

    def test_clicking_a_row_opens_the_event(self):
        event = ev(at(1, 11), at(1, 12), "Standup", entry_id="E1", store_id="S1")
        host = self.fill(self.make(live(event)))
        with mock.patch.object(widget_module, "open_event_in_background") as opener:
            by_class(host, "event-row")[0].mousePressEvent(press())
        opener.assert_called_once_with(event)

    def test_an_event_without_an_id_opens_the_calendar(self):
        host = self.fill(self.make(live(ev(at(1, 11), at(1, 12)))))
        with (
            mock.patch.object(widget_module, "open_calendar") as calendar,
            mock.patch.object(widget_module, "open_event_in_background") as opener,
        ):
            by_class(host, "event-row")[0].mousePressEvent(press())
        calendar.assert_called_once_with()
        opener.assert_not_called()

    def test_empty_and_closed(self):
        cases = [
            (live(), {}, "Nothing in the next 7 days"),
            (live(), {"days": 1}, "Nothing today"),
            (Snapshot(), {}, "Outlook closed"),
        ]
        for snapshot, options, text in cases:
            host = self.fill(self.make(snapshot, **options))
            self.assertEqual(self.texts(host, "placeholder"), [text])

    def test_row_cap(self):
        events = [
            ev(at(1 + i // 4, 10 + i % 4), at(1 + i // 4, 10 + i % 4, 30), f"Event {i}") for i in range(20)
        ]
        host = self.fill(self.make(live(*events), menu={"max_rows": 5}))
        self.assertEqual(len(by_class(host, "event-row")), 5)

    def test_stale_status_line(self):
        host = self.fill(self.make(Snapshot((ev(at(1, 11), at(1, 12)),), FETCHED, "stale")))
        status = by_class(host, "status")[0]
        self.assertEqual(status.text(), "Outlook closed · cached 08:12")
        self.assertEqual(status.property("class"), "status stale")

    def test_time_column_is_aligned(self):
        host = self.fill(self.make(live(all_day(1, 1), ev(at(1, 11), at(1, 12)))))
        widths = {label.minimumWidth() for label in by_class(host, "time")}
        self.assertEqual(len(widths), 1)
        self.assertGreater(widths.pop(), 0)

    def test_subject_in_popup_is_plain_text(self):
        host = self.fill(self.make(live(ev(at(1, 11), at(1, 12), "Review <draft>"))))
        subject = by_class(host, "subject")[0]
        self.assertEqual((subject.text(), subject.textFormat()), ("Review <draft>", Qt.TextFormat.PlainText))

    def test_opening_the_popup_refreshes(self):
        widget = self.make(live())
        with mock.patch.object(widget_module, "PopupWidget", _FakePopup):
            widget._toggle_card()
        self.assertEqual(self.stub.refreshes, 1)

    def test_an_update_rebuilds_an_open_popup(self):
        widget = self.make(live())
        host = QFrame()
        self.addCleanup(host.deleteLater)
        layout = QVBoxLayout(host)
        widget._fill_popup(layout)
        host.isVisible = lambda: True
        widget._popup, widget._popup_layout = host, layout
        self.stub.snapshot = live(ev(at(1, 11), at(1, 12), "New"))
        self.stub.updated.emit()
        self.assertEqual(self.texts(host, "subject"), ["New"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_widget -v`
Expected: `FAILED (errors=1)`, with `ModuleNotFoundError: No module named 'core.validation.widgets.yasb.outlook_calendar'`.

- [ ] **Step 3: Write the config model**

Create `src/core/validation/widgets/yasb/outlook_calendar.py`:

```python
from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class OutlookCalendarCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_card"
    on_middle: str = "open_outlook"
    on_right: str = "toggle_label"


class OutlookCalendarIconsConfig(CustomBaseModel):
    # Nerd Fonts v3 codepoint, outside the pre-v3 Material Design range (U+F500-U+FD46)
    # that v3 removed.
    default: str = "\uf073"  # fa-calendar


class OutlookCalendarMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    min_width: int = Field(default=340, ge=200, le=1000)
    max_rows: int = Field(default=12, ge=1, le=50)


class OutlookCalendarConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {countdown} · {title}"
    label_alt: str = "<span>{icon}</span> {time} · {title}"
    # Shown in place of the template when there is nothing to count down to.
    empty_text: str = "No events"
    closed_text: str = "Outlook closed"
    class_name: str = ""
    days: int = Field(default=7, ge=1, le=31)
    update_interval: int = Field(default=300, ge=60, le=3600)
    soon_minutes: int = Field(default=15, ge=0, le=240)
    max_title_length: int = Field(default=20, ge=0, le=200)
    time_format: str = "%H:%M"
    # Look for a Teams, Zoom or Meet link in the event body too. Turn off if Outlook ever
    # asks whether to allow a program to access it (its antivirus check has lapsed).
    scan_body: bool = True
    tooltip: bool = True
    icons: OutlookCalendarIconsConfig = OutlookCalendarIconsConfig()
    menu: OutlookCalendarMenuConfig = OutlookCalendarMenuConfig()
    callbacks: OutlookCalendarCallbacksConfig = OutlookCalendarCallbacksConfig()
    keybindings: list[KeybindingConfig] = []
```

Note: the Write and Edit tools turn the `\uf073` escape into the literal glyph. Either form is valid Python and gives the same string.

- [ ] **Step 4: Write the widget**

Create `src/core/widgets/yasb/outlook_calendar.py`:

```python
"""Outlook calendar widget: counts down to the next event on the default Outlook calendar.

The shared ``OutlookCalendarService`` reads Outlook over COM and caches what it read, so this
class only renders: the label, tooltip and popup are re-derived from the latest snapshot and
the wall clock on every service update, at least every 30 seconds.
"""

import html
import re
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.utils.tooltip import set_tooltip
from core.utils.utilities import ElidedLabel, PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.outlook_calendar import OutlookCalendarConfig
from core.widgets.base import BaseWidget
from core.widgets.services.outlook_calendar.agenda import (
    CalEvent,
    day_heading,
    day_start,
    format_countdown,
    format_status,
    format_time_range,
    group_by_day,
    row_status,
    select_event,
    shorten,
    today_count,
)
from core.widgets.services.outlook_calendar.outlook import open_calendar, open_event_in_background
from core.widgets.services.outlook_calendar.service import OutlookCalendarService

_UNAVAILABLE_TEXT = "Outlook unavailable"
_PLACEHOLDER_RE = re.compile(r"\{\w+\}")


def _label(cls: str, text: str = "", kind: type[QLabel] = QLabel) -> QLabel:
    """A plain-text popup label carrying *cls*, with QLabel's automatic indent switched off.

    Event subjects are user text: read as rich text, "Review <draft>" would lose its tag.
    The default indent of -1 becomes half an 'x' of the font as soon as a stylesheet adds
    padding, so labels in one column would no longer share a left edge.
    """
    label = kind()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("class", cls)
    label.setIndent(0)
    label.setText(text)
    return label


def fit_to_width(widget: QWidget) -> None:
    """Size *widget* to its contents, measuring wrapped text at the width it really gets."""
    widget.adjustSize()
    layout = widget.layout()
    if layout is not None and layout.hasHeightForWidth():
        widget.resize(widget.width(), layout.totalHeightForWidth(widget.width()))


def _open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class _EventRow(QFrame):
    """A popup row that hands its event to *on_click* when clicked."""

    def __init__(self, event: CalEvent, on_click, parent: QWidget | None = None):
        super().__init__(parent)
        self.event = event
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, mouse_event):
        if mouse_event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.event)
        super().mousePressEvent(mouse_event)


class OutlookCalendarWidget(BaseWidget):
    """Counts down to the next event on the default Outlook calendar; the popup lists the days."""

    validation_schema = OutlookCalendarConfig

    def __init__(self, config: OutlookCalendarConfig):
        super().__init__(class_name=f"outlook-calendar-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._service_released = False
        self._popup: QWidget | None = None
        self._popup_layout: QVBoxLayout | None = None

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        for label in (*self._widgets, *self._widgets_alt):
            label.setProperty("base_class", label.property("class") or "")
            label.setTextFormat(Qt.TextFormat.PlainText)

        self.register_callback("toggle_card", self._toggle_card)
        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("refresh", self._refresh)
        self.register_callback("open_outlook", self._open_outlook)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle

        self._service = OutlookCalendarService.get_instance(config.days, config.update_interval, config.scan_body)
        self._service.updated.connect(self._on_updated)
        self.destroyed.connect(lambda *_: self._release_service())
        self._update_label()

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    def _release_service(self) -> None:
        if getattr(self, "_service_released", False):
            return
        self._service_released = True
        try:
            self._service.release()
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._release_service()
        super().closeEvent(event)

    def _on_updated(self) -> None:
        self._update_label()
        self._sync_popup()

    def _refresh(self) -> None:
        self._service.refresh_now()

    def _open_outlook(self) -> None:
        open_calendar()

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _events(self) -> tuple[CalEvent, ...]:
        """The snapshot's events inside this widget's window. The window can be shorter than
        the service's, when another bar asked for more days."""
        start = day_start(self._now().date())
        end = start + timedelta(days=self.config.days)
        return tuple(event for event in self._service.snapshot.events if event.start < end and event.end > start)

    def _message(self) -> tuple[str, str]:
        """(state class, text) for when the bar has no event to count down to."""
        snapshot = self._service.snapshot
        if snapshot.fetched_at is None:
            if snapshot.status == "error":
                return "error", _UNAVAILABLE_TEXT
            return "closed", self.config.closed_text
        return "empty", self.config.empty_text

    def _staleness(self) -> list[str]:
        """``stale`` or ``error`` when the events shown were read earlier, else nothing."""
        snapshot = self._service.snapshot
        if snapshot.fetched_at is not None and snapshot.status in ("stale", "error"):
            return [snapshot.status]
        return []

    def _is_soon(self, event: CalEvent, now: datetime) -> bool:
        minutes = self.config.soon_minutes
        return bool(minutes) and now < event.start <= now + timedelta(minutes=minutes)

    # ------------------------------------------------------------------
    # Bar label
    # ------------------------------------------------------------------

    def _label_options(self, event: CalEvent | None, now: datetime) -> tuple[dict[str, str], list[str]]:
        time_format = self.config.time_format
        options = {
            "{icon}": self.config.icons.default,
            "{countdown}": "",
            "{title}": "",
            "{time}": "",
            "{location}": "",
            "{today_count}": str(today_count(self._events(), now)),
        }
        states: list[str] = []
        if event is None:
            state, options["{title}"] = self._message()
            states.append(state)
        else:
            options["{countdown}"] = format_countdown(event, now, time_format)
            options["{title}"] = shorten(event.subject, self.config.max_title_length)
            options["{time}"] = format_time_range(event, time_format)
            options["{location}"] = event.location
            if event.ongoing(now):
                states.append("ongoing")
            elif self._is_soon(event, now):
                states.append("soon")
            if event.tentative:
                states.append("tentative")
        states.extend(self._staleness())
        return options, states

    def _update_label(self) -> None:
        now = self._now()
        event = select_event(self._events(), now)
        options, states = self._label_options(event, now)
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_content = self.config.label_alt if self._show_alt_label else self.config.label
        label_parts = [p for p in re.split(r"(<span.*?>.*?</span>)", active_content) if p]
        # With no event, a template such as "{countdown} · {title}" would render as a stray
        # separator, so the first text label carries the state's message and others go blank.
        message = options["{title}"] if event is None else None
        widget_index = 0
        for part in label_parts:
            part = part.strip()
            if not part or widget_index >= len(active_widgets):
                continue
            widget = active_widgets[widget_index]
            widget_index += 1
            is_icon = "<span" in part and "</span>" in part
            if is_icon:
                part = re.sub(r"<span.*?>|</span>", "", part)
            if message is not None and not is_icon:
                text, message = message, ""
            else:
                # One pass, so a subject containing "{time}" is not substituted again.
                filled = _PLACEHOLDER_RE.sub(lambda m: options.get(m.group(0), m.group(0)), part)
                text = " ".join(filled.split())
            widget.setText(text)
            widget.setVisible(bool(text) and (widget in self._widgets) != self._show_alt_label)
            base = widget.property("base_class") or ""
            widget.setProperty("class", " ".join(p for p in (base, *states) if p))
            refresh_widget_style(widget)
        self._update_tooltip(event, now)

    def _update_tooltip(self, event: CalEvent | None, now: datetime) -> None:
        if not self.config.tooltip:
            return
        time_format = self.config.time_format
        if event is None:
            lines = [html.escape(self._message()[1])]
        else:
            lines = [
                f"<strong>{html.escape(event.subject)}</strong>",
                f"{day_heading(event.start.date(), now.date())} · {format_time_range(event, time_format)}",
            ]
            if event.location:
                lines.append(html.escape(event.location))
            if event.tentative:
                lines.append("Tentative")
        if self._staleness():
            lines.append(format_status(self._service.snapshot, now, time_format))
        set_tooltip(self, "<br>".join(lines))

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    # ------------------------------------------------------------------
    # Popup
    # ------------------------------------------------------------------

    def _toggle_card(self) -> None:
        self._service.refresh_now()
        m = self.config.menu
        popup = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        popup.setProperty("class", "outlook-calendar-menu")
        popup.setMinimumWidth(m.min_width)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._fill_popup(layout)
        fit_to_width(popup)
        popup.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        popup.show()
        if popup.isVisible():
            self._popup = popup
            self._popup_layout = layout
        else:
            # PopupWidget.show() found one already open and closed it instead.
            popup.deleteLater()
            self._forget_popup()

    def _forget_popup(self) -> None:
        self._popup = None
        self._popup_layout = None

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.hide()
            except RuntimeError:
                pass
        self._forget_popup()

    def _sync_popup(self) -> None:
        if self._popup is None or self._popup_layout is None:
            return
        try:
            if not self._popup.isVisible():
                self._forget_popup()
                return
            self._fill_popup(self._popup_layout)
            fit_to_width(self._popup)
        except RuntimeError:
            self._forget_popup()

    def _open_event(self, event: CalEvent) -> None:
        if event.entry_id:
            open_event_in_background(event)
        else:
            open_calendar()
        self._close_popup()

    def _join(self, url: str) -> None:
        _open_url(url)
        self._close_popup()

    def _fill_popup(self, layout: QVBoxLayout) -> None:
        while layout.count():
            old = layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        now = self._now()
        layout.addWidget(self._build_header(now))
        days = group_by_day(self._events(), now.date(), self.config.days)
        if not days:
            layout.addWidget(self._build_placeholder())
            return
        container = QFrame()
        container.setProperty("class", "days")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        layout.addWidget(container)
        time_labels: list[QLabel] = []
        rows = 0
        for day in days:
            if rows >= self.config.menu.max_rows:
                break
            container_layout.addWidget(_label("day-heading", day_heading(day.day, now.date())))
            for event in (*day.all_day, *day.timed):
                if rows >= self.config.menu.max_rows:
                    break
                row, time_label = self._build_row(event, now)
                container_layout.addWidget(row)
                time_labels.append(time_label)
                rows += 1
        self._align(time_labels)

    @staticmethod
    def _align(labels: list[QLabel]) -> None:
        """Give every time label the widest one's width, so subjects start in one column."""
        for label in labels:
            label.ensurePolished()
        width = max((label.sizeHint().width() for label in labels), default=0)
        for label in labels:
            label.setMinimumWidth(width)

    def _build_header(self, now: datetime) -> QFrame:
        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(
            _label("header-icon", self.config.icons.default), alignment=Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(_label("title", "Calendar"), alignment=Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch()
        snapshot = self._service.snapshot
        classes = ["status", *self._staleness()]
        if snapshot.fetched_at is None:
            classes.append(self._message()[0])
        status = _label(" ".join(classes), format_status(snapshot, now, self.config.time_format))
        status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(status, alignment=Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_placeholder(self) -> QLabel:
        if self._service.snapshot.fetched_at is None:
            state, text = self._message()
        elif self.config.days == 1:
            state, text = "empty", "Nothing today"
        else:
            state, text = "empty", f"Nothing in the next {self.config.days} days"
        placeholder = _label(f"placeholder {state}", text)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        return placeholder

    def _build_row(self, event: CalEvent, now: datetime) -> tuple[QFrame, QLabel]:
        time_format = self.config.time_format
        classes = ["event-row"]
        if event.all_day:
            classes.append("all-day")
        elif event.end <= now:
            classes.append("past")
        elif event.ongoing(now):
            classes.append("ongoing")
        elif self._is_soon(event, now):
            classes.append("soon")
        if event.tentative:
            classes.append("tentative")
        row = _EventRow(event, self._open_event)
        row.setProperty("class", " ".join(classes))
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        time_label = _label("time", format_time_range(event, time_format))
        row_layout.addWidget(time_label, alignment=Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(_label("subject", event.subject, ElidedLabel))
        if event.location:
            text.addWidget(_label("location", event.location, ElidedLabel))
        row_layout.addLayout(text, 1)

        if event.tentative:
            row_layout.addWidget(_label("tag", "Tentative"), alignment=Qt.AlignmentFlag.AlignVCenter)
        when = row_status(event, now, time_format)
        if when:
            when_label = _label("when", when)
            when_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(when_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        if event.join_url:
            join = QPushButton("Join")
            join.setProperty("class", "join")
            join.setCursor(Qt.CursorShape.PointingHandCursor)
            join.clicked.connect(lambda _checked=False, url=event.join_url: self._join(url))
            row_layout.addWidget(join, alignment=Qt.AlignmentFlag.AlignVCenter)
        return row, time_label
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$env:PYTHON_COLORS = "0"; & "D:\Programming\yasb\.venv\Scripts\python.exe" -m unittest tests.test_outlook_calendar_widget -v`
Expected: `Ran 32 tests` … `OK`.

If `test_groups_rows_by_day` or `test_row_marks` fail only on order, check `by_class` order first. `findChildren` walks depth-first in parenting order, and a row's subject label is parented when `row_layout.addLayout(text, 1)` runs, after the time label. Fix the widget, not the expected lists.

- [ ] **Step 6: Lint and commit**

```powershell
$py = "D:\Programming\yasb\.venv\Scripts\python.exe"; $f = "src/core/validation/widgets/yasb/outlook_calendar.py", "src/core/widgets/yasb/outlook_calendar.py", "tests/test_outlook_calendar_widget.py"
& $py -m ruff format @f; & $py -m ruff check --fix @f; & $py -m ruff check @f
git add @f
git commit -m "wip(outlook_calendar): config and widget"
```
Expected: `All checks passed!` before the commit.

---

### Task 5: Docs, visual check, and the single feature commit

**Files:**
- Create: `docs/widgets/(Widget)-Outlook-Calendar.md`
- Modify: `README.md`, adding a row after line 119 (`| [Open Meteo](...`)
- Modify: `docs/_Sidebar.md`, adding a line after line 51 (`    - [Open Meteo](./(Widget)-Open-Meteo)`)

**Interfaces:**
- Consumes everything from Tasks 1–4: the option names, defaults, placeholders, callbacks and CSS classes must match the code exactly.
- Produces the finished `feat/outlook-calendar` branch: one commit on `main`.

- [ ] **Step 1: Write the docs page**

Create `docs/widgets/(Widget)-Outlook-Calendar.md`:

````markdown
# Outlook Calendar Widget

Counts down to the next event on your Outlook calendar, and lists the coming days in a popup.

The widget reads the default calendar of **classic Outlook** (`OUTLOOK.EXE`) on this PC, over COM. It shows whatever Outlook shows: an Exchange or Microsoft 365 mailbox, an Outlook.com account, or an IMAP account whose calendar exists only inside Outlook. There is nothing to sign in to and no API key. The new Outlook for Windows has no COM interface and is not supported.

The widget never starts Outlook on its own. While Outlook is closed, the bar keeps counting down from the last events it read, which are saved in `%LOCALAPPDATA%\YASB\outlook_calendar.json`, and marks the reading as stale. It refreshes as soon as Outlook is running again. Clicking an event, or the `open_outlook` callback, does open Outlook.

The bar shows the event in progress (`now · Vendor review`) or the next one (`in 25m · Weekly sync`):
- **Counted:** invitations you have not answered, marked as tentative.
- **Not counted:** events shown as **Free**, all-day events and declined events. The popup still lists all-day events at the top of each day.

Click a row to open that event in Outlook. Events with a Microsoft Teams, Zoom or Google Meet link get a **Join** button.

| Option             | Type    | Default                                       | Description |
|--------------------|---------|-----------------------------------------------|-------------|
| `label`            | string  | `"<span>{icon}</span> {countdown} · {title}"` | The primary label format. |
| `label_alt`        | string  | `"<span>{icon}</span> {time} · {title}"`      | The alternative label format. |
| `empty_text`       | string  | `"No events"`                                 | Shown instead of the label when nothing is coming up in the window. |
| `closed_text`      | string  | `"Outlook closed"`                            | Shown instead of the label when Outlook is closed and nothing has been read yet. |
| `class_name`       | string  | `""`                                          | Additional CSS class name for the widget. |
| `days`             | integer | `7`                                           | How many days, starting today, the widget looks ahead (1-31). |
| `update_interval`  | integer | `300`                                         | Seconds between reads of the calendar (60-3600). Opening the popup also reads it. Countdowns tick every 30 seconds regardless. |
| `soon_minutes`     | integer | `15`                                          | An event starting within this many minutes gets the `soon` class. `0` turns it off. |
| `max_title_length` | integer | `20`                                          | Cut `{title}` on the bar to this many characters. `0` means no limit. |
| `time_format`      | string  | `"%H:%M"`                                     | strftime format for times, e.g. `"%I:%M %p"` for 12-hour. |
| `scan_body`        | boolean | `true`                                        | Also look for a meeting link in the event's body, not just its location. See Troubleshooting. |
| `tooltip`          | boolean | `true`                                        | Show the event's details on hover. |
| `icons`            | dict    | `{default: ""}`                              | The widget's icon, used for `{icon}` and in the popup header. |
| `menu`             | dict    | see below                                     | Popup settings. |
| `callbacks`        | dict    | `{on_left: "toggle_card", on_middle: "open_outlook", on_right: "toggle_label"}` | Mouse button actions. |
| `keybindings`      | list    | `[]`                                          | Keyboard shortcuts for the callbacks. |

### Menu options

| Option               | Type    | Default    | Description |
|----------------------|---------|------------|-------------|
| `blur`               | boolean | `true`     | Blur the popup background. |
| `round_corners`      | boolean | `true`     | Round the popup corners (Windows 11). |
| `round_corners_type` | string  | `"normal"` | `normal` or `small`. |
| `border_color`       | string  | `"System"` | `System`, `None` or a hex colour. |
| `alignment`          | string  | `"right"`  | `left`, `right` or `center`. |
| `direction`          | string  | `"down"`   | `up` or `down`. |
| `offset_top`         | integer | `6`        | Vertical offset in pixels. |
| `offset_left`        | integer | `0`        | Horizontal offset in pixels. |
| `min_width`          | integer | `340`      | Minimum popup width in pixels. Long subjects are cut to fit it. |
| `max_rows`           | integer | `12`       | How many events the popup lists. |

## Label Placeholders

| Placeholder     | Description                                                     | Example Output |
|-----------------|-----------------------------------------------------------------|----------------|
| `{icon}`        | The configured icon                                             | ``            |
| `{countdown}`   | When the event starts                                           | `now`, `in 25m`, `in 3h 20m`, `tomorrow 10:00`, `Tue 10:00`, `8 Oct 10:00` |
| `{title}`       | The event's subject, cut to `max_title_length`                  | `Weekly sync`  |
| `{time}`        | Its start and end                                               | `14:00–15:00`  |
| `{location}`    | Its location                                                    | `Room 4B`      |
| `{today_count}` | Events still to come or under way today                         | `3`            |

When there is no event to show, the first text label shows `empty_text`, `closed_text` or `Outlook unavailable`, and the rest of the template is left blank.

The bar's labels get these classes, so a theme can style each state:

| Class       | When |
|-------------|------|
| `ongoing`   | The event is under way. |
| `soon`      | It starts within `soon_minutes`. |
| `tentative` | It's an invitation you have not answered, or it's shown as Tentative. |
| `stale`     | Outlook is closed, and the events come from the last read. |
| `error`     | Outlook has refused to answer three times in a row (usually a dialog is open in it). |
| `empty`     | Nothing is coming up. |
| `closed`    | Outlook is closed and nothing has been read yet. |

## Callbacks

| Callback       | Description |
|----------------|-------------|
| `toggle_card`  | Open or close the popup. Opening it also reads the calendar. |
| `toggle_label` | Switch between `label` and `label_alt`. |
| `refresh`      | Read the calendar now. |
| `open_outlook` | Open Outlook's calendar, starting Outlook if needed. |

## Example Configuration

```yaml
outlook_calendar:
  type: "yasb.outlook_calendar.OutlookCalendarWidget"
  options:
    label: "<span>{icon}</span> {countdown} · {title}"
    label_alt: "<span>{icon}</span> {time} · {title}"
    max_title_length: 20
    soon_minutes: 15
    days: 7
    menu:
      alignment: "center"
    callbacks:
      on_left: "toggle_card"
      on_middle: "open_outlook"
      on_right: "toggle_label"
```

## Troubleshooting

- **Always "Outlook closed".** Classic Outlook is not running in your Windows session. Two other setups look the same to the widget:
  - Outlook runs as administrator and yasb does not, or the other way round.
  - You use the new Outlook. Switch the **New Outlook** toggle off in Outlook to go back to classic.
- **Outlook asks whether to allow a program to access email information.** Outlook does this when it considers your antivirus out of date. Set `scan_body: false`, so only the location is searched for meeting links, and update your antivirus.
- **A new invitation is missing.** The calendar is read every `update_interval` seconds. Opening the popup reads it at once.

## Description of Options

- **label**: The format string for the label. Use the placeholders above.
- **label_alt**: The alternative format string, shown after `toggle_label`.
- **empty_text**, **closed_text**: The text shown when there is no event to count down to.
- **days**: The look-ahead window, in days, counting today.
- **update_interval**: How often the calendar is read, in seconds.
- **soon_minutes**: How close an event must be to get the `soon` class.
- **max_title_length**: The maximum length of `{title}`.
- **time_format**: How times are written.
- **scan_body**: Whether to search the event body for meeting links.
- **tooltip**: Whether to show the tooltip.
- **icons**: The widget's icon.
- **menu**: The popup's settings.
- **callbacks**: The mouse button actions.
- **keybindings**: Keyboard shortcuts.

## Example Style

```css
.outlook-calendar-widget .icon {
    font-size: 14px;
    color: #ECEAE4;
    padding-right: 6px;
}
.outlook-calendar-widget .label {
    font-size: 13px;
    color: #ECEAE4;
}
.outlook-calendar-widget .label.soon,
.outlook-calendar-widget .icon.soon,
.outlook-calendar-widget .label.ongoing,
.outlook-calendar-widget .icon.ongoing {
    color: #E0834F;
}
.outlook-calendar-widget .label.tentative {
    font-style: italic;
}
.outlook-calendar-widget .label.empty,
.outlook-calendar-widget .label.closed,
.outlook-calendar-widget .label.error,
.outlook-calendar-widget .label.stale {
    color: rgba(236, 234, 228, 0.5);
}
.outlook-calendar-menu {
    background-color: rgba(30, 30, 32, 0.94);
}
.outlook-calendar-menu .header {
    padding: 12px 16px 10px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.outlook-calendar-menu .header-icon {
    font-size: 15px;
    color: #D4A27F;
    padding-right: 8px;
}
.outlook-calendar-menu .title {
    font-family: "Segoe UI";
    font-size: 14px;
    font-weight: 600;
    color: #ECEAE4;
}
.outlook-calendar-menu .status {
    font-family: "Segoe UI";
    font-size: 11px;
    color: rgba(236, 234, 228, 0.45);
}
.outlook-calendar-menu .status.stale,
.outlook-calendar-menu .status.error {
    color: #D4A27F;
}
.outlook-calendar-menu .day-heading {
    font-family: "Segoe UI";
    font-size: 11px;
    font-weight: 600;
    color: rgba(236, 234, 228, 0.45);
    padding: 12px 16px 4px 16px;
}
.outlook-calendar-menu .event-row {
    padding: 6px 16px;
}
.outlook-calendar-menu .event-row:hover {
    background-color: rgba(255, 255, 255, 0.05);
}
.outlook-calendar-menu .event-row .time {
    font-family: "Bahnschrift";
    font-size: 13px;
    color: #ECEAE4;
    padding-right: 12px;
}
.outlook-calendar-menu .event-row .subject {
    font-family: "Segoe UI";
    font-size: 13px;
    color: #ECEAE4;
}
.outlook-calendar-menu .event-row .location {
    font-family: "Segoe UI";
    font-size: 11px;
    color: rgba(236, 234, 228, 0.45);
}
.outlook-calendar-menu .event-row .when {
    font-family: "Bahnschrift";
    font-size: 12px;
    color: rgba(236, 234, 228, 0.6);
    padding-left: 10px;
}
.outlook-calendar-menu .event-row.soon .when,
.outlook-calendar-menu .event-row.ongoing .when {
    color: #E0834F;
}
.outlook-calendar-menu .event-row.past .time,
.outlook-calendar-menu .event-row.past .subject,
.outlook-calendar-menu .event-row.past .when {
    color: rgba(236, 234, 228, 0.35);
}
.outlook-calendar-menu .event-row .tag {
    font-family: "Segoe UI";
    font-size: 10px;
    color: #D4A27F;
    border: 1px solid rgba(212, 162, 127, 0.6);
    border-radius: 3px;
    padding: 0 4px;
    margin-left: 8px;
}
.outlook-calendar-menu .event-row .join {
    font-family: "Segoe UI";
    font-size: 12px;
    font-weight: 600;
    color: #1E1E20;
    background-color: #E0834F;
    border: none;
    border-radius: 4px;
    padding: 3px 10px;
    margin-left: 10px;
}
.outlook-calendar-menu .event-row .join:hover {
    background-color: #EF5A48;
}
.outlook-calendar-menu .placeholder {
    font-family: "Segoe UI";
    font-size: 13px;
    color: rgba(236, 234, 228, 0.5);
    padding: 28px 16px;
}
```

Popup classes:
- **Frame:** `.outlook-calendar-menu`, `.header`, `.header-icon`, `.title`, and `.status` (plus `.stale`, `.error` or `.closed`).
- **Days and rows:** `.day-heading`, and `.event-row` (plus `.all-day`, `.past`, `.ongoing`, `.soon` or `.tentative`).
- **Inside a row:** `.time`, `.subject`, `.location`, `.tag`, `.when`, `.join`.
- **Empty popup:** `.placeholder` (plus `.empty`, `.closed` or `.error`).

> Qt stylesheets apply the rule with the most classes, whatever its order in the file. The `.event-row.past .subject` rule above (four classes) therefore wins over `.event-row .subject` (three).
````

The `{icon}` example cells hold the U+F073 glyph, as the anime docs page does. In Markdown it's the literal character.

- [ ] **Step 2: Add the README row and the sidebar entry**

In `README.md`, insert after line 119 (the Open Meteo row):

```markdown
| [Outlook Calendar](https://github.com/amnweb/yasb/wiki/(Widget)-Outlook-Calendar) | Counts down to the next event on your Outlook calendar, with the coming days in a popup. |
```

In `docs/_Sidebar.md`, insert after line 51 (`    - [Open Meteo](./(Widget)-Open-Meteo)`):

```markdown
    - [Outlook Calendar](./(Widget)-Outlook-Calendar)
```

Check: `git diff README.md docs/_Sidebar.md` shows exactly these two added lines.

- [ ] **Step 3: Offscreen visual check of the popup with the example style**

1. Extract the docs page's Example Style CSS block into `<scratchpad>\outlook_example.css`. It's the block between the ```` ```css ```` fence under "## Example Style" and its closing fence.
2. Write `<scratchpad>\render_popup.py`:

```python
"""Render the Outlook calendar popup offscreen with a fixture snapshot and the docs' example style."""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, sys.argv[1])

from PyQt6.QtCore import QObject, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QVBoxLayout  # noqa: E402

app = QApplication([])
font = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts" / "JetBrainsMonoNerdFontPropo-Regular.ttf"
if font.exists():
    QFontDatabase.addApplicationFont(str(font))
app.setStyleSheet(Path(sys.argv[2]).read_text(encoding="utf-8"))

from core.validation.widgets.yasb.outlook_calendar import OutlookCalendarConfig  # noqa: E402
from core.widgets.services.outlook_calendar.agenda import CalEvent, Snapshot  # noqa: E402
from core.widgets.yasb import outlook_calendar as w  # noqa: E402

NOW = datetime(2026, 10, 1, 9, 0)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute)


EVENTS = (
    CalEvent(at(1, 0), at(2, 0), "Founders day", all_day=True),
    CalEvent(at(1, 7), at(1, 8), "Gym"),
    CalEvent(at(1, 8, 30), at(1, 9, 30), "Vendor review", location="Meeting room 3"),
    CalEvent(at(1, 9, 10), at(1, 9, 40), "Budget follow-up", busy=1, response=5,
             join_url="https://teams.microsoft.com/meet/123?p=a"),
    CalEvent(at(1, 14), at(1, 15), "Weekly sync with the warehouse team and finance", location="Teams"),
    CalEvent(at(2, 10), at(2, 10, 30), "1:1 with lead"),
)


class Stub(QObject):
    updated = pyqtSignal()
    snapshot = Snapshot(EVENTS, datetime(2026, 10, 1, 8, 12), "stale")

    def refresh_now(self):
        pass

    def release(self):
        pass


with mock.patch.object(w.OutlookCalendarService, "get_instance", return_value=Stub()):
    widget = w.OutlookCalendarWidget(OutlookCalendarConfig())
widget._now = lambda: NOW
host = QFrame()
host.setProperty("class", "outlook-calendar-menu")
host.setMinimumWidth(340)
host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
layout = QVBoxLayout(host)
layout.setContentsMargins(0, 0, 0, 0)
layout.setSpacing(0)
widget._fill_popup(layout)
w.fit_to_width(host)
host.show()
app.processEvents()
host.grab().save(sys.argv[3])
print("saved", sys.argv[3], host.width(), "x", host.height())
```

3. Run: `& "D:\Programming\yasb\.venv\Scripts\python.exe" "<scratchpad>\render_popup.py" "<wt>\src" "<scratchpad>\outlook_example.css" "<scratchpad>\outlook_popup.png"`
4. Open the PNG with the Read tool and check each of these:
   - The status reads `Outlook closed · cached 08:12` in kraft.
   - Headings read Today and Tomorrow.
   - The all-day row is first, with `all day` in the time column.
   - The time column lines up.
   - Gym is dimmed and reads `ended`.
   - Vendor review reads `now` in clay.
   - Budget follow-up shows a `Tentative` tag, `in 10m` in clay, and a Join button.
   - The long Weekly sync subject is elided with `…`.

   Fix anything that's off in the widget or the docs CSS, then re-run the tests.

- [ ] **Step 4: Full verification**

Run, from `<wt>`:
```powershell
$env:PYTHON_COLORS = "0"; $py = "D:\Programming\yasb\.venv\Scripts\python.exe"
& $py -m unittest tests.test_outlook_calendar_agenda tests.test_outlook_calendar_outlook tests.test_outlook_calendar_service tests.test_outlook_calendar_widget -v
& $py -m ruff check src/core/widgets/services/outlook_calendar src/core/widgets/yasb/outlook_calendar.py src/core/validation/widgets/yasb/outlook_calendar.py tests/test_outlook_calendar_agenda.py tests/test_outlook_calendar_outlook.py tests/test_outlook_calendar_service.py tests/test_outlook_calendar_widget.py
& $py -m ruff format --check src/core/widgets/services/outlook_calendar src/core/widgets/yasb/outlook_calendar.py src/core/validation/widgets/yasb/outlook_calendar.py tests/test_outlook_calendar_agenda.py tests/test_outlook_calendar_outlook.py tests/test_outlook_calendar_service.py tests/test_outlook_calendar_widget.py
git status --short
```
Expected:
- `Ran 103 tests` … `OK`
- `All checks passed!`
- ruff format reports every file already formatted
- `git status` lists only the docs page, `README.md` and `docs/_Sidebar.md` as uncommitted, with no `src/schema.json`.

Also confirm that the full existing suite still imports: run `& $py -m unittest $(Get-ChildItem tests -Filter "test_*.py" | ForEach-Object { "tests." + $_.BaseName }) 2>&1 | Select-Object -Last 3` and expect `OK`. If a test that is not an outlook_calendar test fails, check whether it also fails on `main` before blaming this branch.

- [ ] **Step 5: Squash the branch into one feature commit**

Write the message to `<scratchpad>\feat-msg.txt` with the Write tool, not a here-string, so its backticks and apostrophes survive:

```
feat(outlook_calendar): add Outlook Calendar widget

Counts down to the next event on the default Outlook calendar and lists the coming days in a
popup. The calendar is read from classic Outlook over COM, so it covers any account Outlook
holds, including IMAP calendars that Microsoft Graph cannot see.

The widget attaches only to an Outlook that is already running and never starts one. The
last read is cached, so the bar keeps counting down while Outlook is closed and marks the
reading stale. Unanswered invites count, shown as tentative; free, all-day and declined
events do not take the bar. Clicking a popup row opens that event in Outlook, and Teams,
Zoom and Google Meet links get a Join button. One shared service polls for every bar, off
the UI thread.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

Then:
```powershell
git add "docs/widgets/(Widget)-Outlook-Calendar.md" README.md docs/_Sidebar.md
git reset --soft main
git commit -F "<scratchpad>\feat-msg.txt"
git log --oneline main..HEAD
git log -1 --format=%B
git diff --stat main HEAD
```
Expected:
- the log shows exactly one commit, `feat(outlook_calendar): add Outlook Calendar widget`
- the body reads back intact
- the stat lists the 12 files from the File Map: 5 under `src/`, 4 tests, the docs page, `README.md` and `docs/_Sidebar.md`.

---

### Task 6: Assemble `squash`, build, install, configure (CHECKPOINT: ask the user first)

**Stop before this task and ask the user whether to go ahead.** It moves the `squash` branch, rebuilds yasb, needs a UAC prompt, restarts the running bar, and edits `~/.config/yasb/config.yaml` and `styles.css`. Their approval of the plan does not cover it.

**Files:**
- Modify (outside the repo): `%USERPROFILE%\.config\yasb\config.yaml`, `%USERPROFILE%\.config\yasb\styles.css`
- Move: the `squash` branch (local only; no push)

- [ ] **Step 1: Re-assemble `squash` without touching any working tree**

Write `<scratchpad>\assemble_squash.sh` with the Write tool:

```bash
#!/usr/bin/env bash
# Rebuild squash: main + one commit per feature (message and author from the current squash
# commits, tree from the feature branch) + the gitignore chore. Prints the new tip.
set -euo pipefail
cd /d/Programming/yasb
out="$1"
mkdir -p "$out"
pairs=(
  "c50c0f3c feature/prayer-times-widget"
  "8a40734c feature/taskbar-badge"
  "864bd1bd feat/ai-usage-widgets"
  "4e0d8bac feat/mal-airing-reminder"
  "feat/outlook-calendar feat/outlook-calendar"
)
commit_like() {
  local src="$1" tree="$2" parent="$3"
  git log -1 --format=%B "$src" > "$out/msg"
  GIT_AUTHOR_NAME="$(git log -1 --format=%an "$src")" \
  GIT_AUTHOR_EMAIL="$(git log -1 --format=%ae "$src")" \
  GIT_AUTHOR_DATE="$(git log -1 --format=%ad --date=raw "$src")" \
    git commit-tree "$tree" -p "$parent" -F "$out/msg"
}
cur=$(git rev-parse main)
for pair in "${pairs[@]}"; do
  read -r src feature <<< "$pair"
  tree=$(git merge-tree --write-tree --merge-base=main "$cur" "$feature")
  cur=$(commit_like "$src" "$tree" "$cur")
done
chore=85186241
tree=$(git merge-tree --write-tree --merge-base="$chore^" "$cur" "$chore")
cur=$(commit_like "$chore" "$tree" "$cur")
echo "$cur"
```

Run: `bash "<scratchpad>/assemble_squash.sh" "<scratchpad>/squash-msgs"`. It prints the new tip, written `<new>` below. Any `merge-tree` conflict aborts the script; if one happens, stop and report it to the user.

- [ ] **Step 2: Verify the new tip before moving anything**

```bash
cd /d/Programming/yasb
new=<new>
features=(feature/prayer-times-widget feature/taskbar-badge feat/ai-usage-widgets feat/mal-airing-reminder feat/outlook-calendar)
mapfile -t commits < <(git rev-list --reverse main.."$new")
echo "commits: ${#commits[@]}"
for i in 0 1 2 3 4; do
  a=$(git diff "${commits[$i]}^" "${commits[$i]}" | git patch-id --stable | cut -d' ' -f1)
  b=$(git diff main "${features[$i]}" | git patch-id --stable | cut -d' ' -f1)
  [ "$a" = "$b" ] && echo "OK ${features[$i]}" || echo "MISMATCH ${features[$i]}"
done
git diff 4e0d8bac "${commits[3]}" --stat | tail -1
```
Expected:
- `commits: 6`
- five `OK` lines
- the last line is empty, because the fourth new commit must have the same tree as the old squash's anime commit `4e0d8bac`.

Then, in a throwaway worktree:
```powershell
git worktree add --detach "<scratchpad>\verify-squash" <new>
Set-Location "<scratchpad>\verify-squash"; $env:PYTHON_COLORS = "0"; $py = "D:\Programming\yasb\.venv\Scripts\python.exe"
& $py -m unittest $(Get-ChildItem tests -Filter "test_*.py" | ForEach-Object { "tests." + $_.BaseName }) 2>&1 | Select-Object -Last 3
& $py -m ruff check src tests
Set-Location D:\Programming\yasb; git worktree remove "<scratchpad>\verify-squash"
```
Expected: `OK`, then `All checks passed!`.

- [ ] **Step 3: Move `squash` in the main checkout**

The main checkout `D:\Programming\yasb` has `squash` checked out, with only untracked files (`.serena/`, `PRODUCT.md`, `src/dist-v1-backup/`). Check with `git status --short`; only `??` lines are allowed. Then run `git reset --keep <new>` and `git log --oneline -7`. Expected: the outlook commit sits just below `chore: ignore .claude/settings.local.json`.

- [ ] **Step 4: Build**

```powershell
robocopy D:\Programming\yasb\src\dist "<scratchpad>\dist-before-outlook" /E /NFL /NDL /NJH /NJS
Set-Location D:\Programming\yasb\src; & ..\.venv\Scripts\python.exe build.py build
```
Expected: the build finishes in about 30 s. "Missing dependencies: api-ms-win-*.dll" warnings are normal. Then confirm the new modules made it in: open `src\dist\lib\library.zip` with `[IO.Compression.ZipFile]::OpenRead` and list entries matching `outlook_calendar`. Expect the agenda, outlook, service, validation and widget `.pyc` files.

- [ ] **Step 5: Install (UAC prompt for the user)**

1. Stop yasb: `& "C:\Program Files\YASB\yasbc.exe" stop`.
2. Write `<scratchpad>\install.ps1`, which runs `Start-Transcript "<scratchpad>\install.log"`, then `robocopy D:\Programming\yasb\src\dist "C:\Program Files\YASB" /E`, then `Stop-Transcript`.
3. Run it elevated: `Start-Process pwsh -Verb RunAs -Wait -ArgumentList '-NoProfile','-File','"<scratchpad>\install.ps1"'`. The quotes inside are needed because `-ArgumentList` does not quote elements.
4. Read the log. Robocopy exit codes up to 3 mean success.

- [ ] **Step 6: Configure and style (yasb is stopped, so the old build cannot choke on the new widget type)**

1. Edit `config.yaml`:
   - Change the centre list to `center: ["clock", "outlook_calendar", "prayer_times", "anime_airing", "weather"]`.
   - Add this under `widgets:`, next to `anime_airing`:
     ```yaml
       outlook_calendar:
         type: "yasb.outlook_calendar.OutlookCalendarWidget"
         options:
           # Reads classic Outlook over COM; never starts it. Middle-click opens the calendar.
           label: "<span>{icon}</span> {countdown} · {title}"
           label_alt: "<span>{icon}</span> {time} · {title}"
           max_title_length: 16
           menu:
             alignment: "center"
     ```
2. Edit `styles.css`:
   - Read the anime section (`/* ---- Anime airing ----`) and the fixed-stations `min-width` block (the `.yasb-bar .prayer-times-widget .label { min-width: ...; }` lines).
   - In that block, add `.yasb-bar .outlook-calendar-widget .label { min-width: Npx; max-width: Npx; }`. The two equal widths keep the centre station from moving. Pick `N` in Step 7, starting at 200.
   - After the anime section, add a `/* ---- Outlook calendar ---- */` section: the docs Example Style, with the selectors prefixed `.yasb-bar` for the bar labels, and with colours replaced by the same `var()` names the anime section uses for chalk, kraft and clay.

- [ ] **Step 7: Restart and check live**

1. Restart: `explorer.exe "C:\Program Files\YASB\yasb.exe"`. Never use Start-Process from this shell, because yasb would inherit the Claude Code environment variables.
2. Wait about 5 s, then check `%USERPROFILE%\.config\yasb\yasb.log` for new lines mentioning `outlook_calendar`, `Traceback` or `validation`. Expect no errors.
3. Take a DPI-aware screenshot of the bar, set to PER_MONITOR_AWARE_V2 first (see memory `windows-dpi-screen-capture`). Check that the widget sits right after the clock, shows the countdown to the next event or `No events`, and that the centre station's other widgets did not move between two captures a minute apart.
4. Adjust `N` until the longest realistic label fits: `tomorrow 10:00 · ` plus 16 characters. Apply each change with `& "C:\Program Files\YASB\yasbc.exe" reload`, because Edit-tool writes don't trigger the watcher.
5. Ask the user to click the widget once and confirm three things:
   - the popup lists their events
   - clicking the event opens it in Outlook
   - middle-click opens the Outlook calendar

- [ ] **Step 8: Record it**

Update the project memory (`projects/D--Programming-yasb/`):
- a new `outlook-calendar-widget.md` covering: the source of truth is `feat/outlook-calendar`; it is squashed into `squash` as the fifth feature; it was installed on the date it was installed; the IMAP/COM finding; the pywintypes UTC-label trick.
- an updated `fork-and-squash-branches.md` table and the assembly pairs (now five features).

Add the index line to the project `MEMORY.md`.

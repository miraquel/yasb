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
    except KeyError, TypeError, ValueError, AttributeError:
        return None
    return Snapshot(events, fetched_at, "stale")

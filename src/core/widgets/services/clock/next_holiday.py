"""Pure (Qt-free) helpers for the clock's next public holiday countdown.

Kept free of Qt imports so the logic can be unit tested without a QApplication.
"""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

# Beyond this the countdown is a plain day count; inside it, hours (and then minutes) show up.
_DAYS_ONLY_FROM = timedelta(days=7)


def find_next_holiday(holidays: Mapping[date, str], today: date) -> tuple[date, str] | None:
    """Return the first ``(date, name)`` on or after *today*, or ``None`` when there is none."""
    upcoming = [day for day in holidays if day >= today]
    if not upcoming:
        return None
    day = min(upcoming)
    return day, holidays[day]


def format_countdown(now: datetime, holiday: date, long: bool = False) -> str:
    """Describe the time from *now* until midnight starting *holiday*, in *now*'s timezone.

    Far off it counts calendar days (``85d``), within a week days and hours (``2d 14h``),
    under a day hours and minutes (``14h 32m``), and ``Today`` on the day itself.
    The *long* form reads as a phrase (``in 85 days``) for the calendar popup.
    """
    days = (holiday - now.date()).days
    if days <= 0:
        return "Today"

    remaining = datetime.combine(holiday, time(0), tzinfo=now.tzinfo) - now
    if remaining >= _DAYS_ONLY_FROM:
        return f"in {days} days" if long else f"{days}d"

    hours, seconds = divmod(int(remaining.total_seconds()), 3600)
    if hours >= 24:
        text = f"{hours // 24}d {hours % 24}h"
    elif hours:
        text = f"{hours}h {seconds // 60}m"
    else:
        text = f"{max(1, seconds // 60)}m"
    return f"in {text}" if long else text


def truncate_name(name: str, max_length: int) -> str:
    """Shorten *name* to *max_length* characters, ending in ``...`` when it had to be cut."""
    if len(name) <= max_length:
        return name
    return name[: max_length - 3].rstrip() + "..."

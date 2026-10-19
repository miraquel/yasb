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

import logging
import threading
from datetime import UTC, datetime, timedelta

import pythoncom
import pywintypes
import win32api
import win32com.client

from core.utils.shell_utils import shell_open
from core.utils.win32.bindings.user32 import AllowSetForegroundWindow
from core.utils.win32.constants import ASFW_ANY, DATE_SHORTDATE, LOCALE_USER_DEFAULT, TIME_NOSECONDS
from core.widgets.services.outlook_calendar.agenda import RESPONSE_DECLINED, CalEvent, day_start, find_join_url

logger = logging.getLogger("outlook_calendar")

OL_FOLDER_CALENDAR = 9
MAX_ITEMS = 500
_CANCELLED = (5, 7)  # olMeetingCanceled, olMeetingReceivedAndCanceled
# MK_E_UNAVAILABLE: not in the Running Object Table, so not running in this session (or
# running at another integrity level). CO_E_CLASSSTRING: classic Outlook is not installed.
_NOT_RUNNING = (-2147221021, -2147221005)


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
    date_text = win32api.GetDateFormat(LOCALE_USER_DEFAULT, DATE_SHORTDATE, stamp, None)
    time_text = win32api.GetTimeFormat(LOCALE_USER_DEFAULT, TIME_NOSECONDS, stamp, None)
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
    failures = 0
    last_error: Exception | None = None
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
            failures += 1
            last_error = error
            logger.debug("outlook calendar: skipped an unreadable item: %s", error)
        item = found.GetNext()
    if last_error is not None and failures == seen:
        # Not one item could be read (Outlook went busy mid-walk): that is a failure, not an empty calendar.
        raise last_error
    return events


def _allow_foreground() -> None:
    """Let Outlook take the foreground; Windows only allows it if the foreground process says so."""
    AllowSetForegroundWindow(ASFW_ANY)


def _open(entry_id: str, store_id: str, start: datetime, recurring: bool, application) -> None:
    # The COM proxies are locals here, so they are released when this returns, before the
    # caller uninitialises COM. Releasing one after CoUninitialize can crash the process.
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


def open_event(entry_id: str, store_id: str, start: datetime, recurring: bool, application=None) -> None:
    """Open one event in Outlook, starting Outlook if needed. Blocks; run it on its own thread."""
    pythoncom.CoInitialize()
    try:
        _open(entry_id, store_id, start, recurring, application)
    except Exception as error:  # a click must never take the bar down
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

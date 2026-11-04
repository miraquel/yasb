# pyright: reportPrivateUsage=false

"""Tests for the Outlook COM source, against a fake Outlook object model.

The fakes follow the real one where it matters: Start and End come back as naive local wall
time (what comtypes makes of a COM date), Restrict sees whether IncludeRecurrences was already
set, and Body counts its reads, since reading it is the access Outlook's security prompt would
guard. Nothing here needs Outlook installed.
"""

import sys
import unittest
from ctypes import WinError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import comtypes  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]

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
ZOOM = "https://us02web.zoom.us/j/81234567890?pwd=abcDEF123"
TEAMS_NEW = "https://teams.microsoft.com/meet/23456789012?p=AbCdEf"

MK_E_UNAVAILABLE = -2147221021
CO_E_CLASSSTRING = -2147221005
RPC_E_CALL_REJECTED = -2147418111


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


def com_error(hresult: int, text: str = "") -> comtypes.COMError:
    return comtypes.COMError(hresult, text, (text, None, None, 0, None))


class FakeItem:
    def __init__(
        self,
        start: datetime,
        end: datetime,
        subject: str = "Meeting",
        location: str = "",
        body: str = "",
        all_day: bool = False,
        busy: int = 2,
        response: int = 3,
        meeting_status: int = 0,
        entry_id: str = "E1",
        recurring: bool = False,
        broken: bool = False,
    ):
        self.Start = start
        self.End = end
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
    def Subject(self) -> str:
        if self._broken:
            raise com_error(-2147467259, "Unspecified error")
        return self._subject

    @property
    def Body(self) -> str:
        self.body_reads += 1
        return self._body


class FakeRestricted:
    def __init__(self, items: list[FakeItem]):
        self._items = list(items)
        self._index = 0
        self.reads = 0

    def GetFirst(self) -> FakeItem | None:
        self._index = 0
        return self._current()

    def GetNext(self) -> FakeItem | None:
        self._index += 1
        return self._current()

    def _current(self) -> FakeItem | None:
        if self._index < len(self._items):
            self.reads += 1
            return self._items[self._index]
        return None


class FakeItems:
    def __init__(self, items: list[FakeItem]):
        self._items = items
        self.IncludeRecurrences = False
        self.calls: list[tuple[object, ...]] = []
        self.query: str | None = None
        self.restricted: FakeRestricted | None = None

    def Sort(self, key: str) -> None:
        self.calls.append(("Sort", key, self.IncludeRecurrences))

    def Restrict(self, query: str) -> FakeRestricted:
        self.calls.append(("Restrict", self.IncludeRecurrences))
        self.query = query
        self.restricted = FakeRestricted(self._items)
        return self.restricted


class FakeOutlook:
    def __init__(self, items: list[FakeItem]):
        self.items = FakeItems(items)
        self.folder = mock.Mock(StoreID="S1", Items=self.items)
        self.namespace = mock.Mock()
        self.namespace.GetDefaultFolder.return_value = self.folder

    def GetNamespace(self, name: str) -> Any:
        assert name == "MAPI"
        return self.namespace


class FetchTests(unittest.TestCase):
    def fetch(self, items: list[FakeItem], scan_body: bool = True) -> tuple[list[CalEvent], FakeOutlook]:
        app = FakeOutlook(items)
        return fetch(NOW, 7, scan_body=scan_body, application=app), app

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

    def test_rounds_a_com_date_to_the_second(self):
        # A COM date is a float count of days; a whole minute can come back a hair short.
        item = FakeItem(at(1, 9, 30) - timedelta(microseconds=1), at(1, 10, 0) + timedelta(microseconds=2))
        events, _ = self.fetch([item])
        self.assertEqual((events[0].start, events[0].end), (at(1, 9, 30), at(1, 10, 0)))

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
        assert app.items.restricted is not None
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

    def test_all_items_unreadable_is_a_failure(self):
        with self.assertRaises(comtypes.COMError):
            self.fetch([FakeItem(at(1, 10), at(1, 11), broken=True), FakeItem(at(1, 12), at(1, 13), broken=True)])

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
    def attach_fails(self, hresult: int):
        # comtypes reports a failed GetActiveObject as an OSError carrying the HRESULT.
        return mock.patch.object(outlook, "get_active_dispatch", side_effect=WinError(hresult))

    def test_not_running(self):
        with self.attach_fails(MK_E_UNAVAILABLE), self.assertRaises(OutlookNotRunning):
            fetch(NOW, 7)

    def test_not_installed_counts_as_not_running(self):
        with self.attach_fails(CO_E_CLASSSTRING), self.assertRaises(OutlookNotRunning):
            fetch(NOW, 7)

    def test_busy_outlook_is_an_error_not_closed(self):
        with self.attach_fails(RPC_E_CALL_REJECTED), self.assertRaises(OSError) as caught:
            fetch(NOW, 7)
        self.assertNotIsInstance(caught.exception, OutlookNotRunning)

    def test_attaches_to_outlook_by_progid(self):
        with mock.patch.object(outlook, "get_active_dispatch", return_value=FakeOutlook([])) as attach:
            fetch(NOW, 7)
        attach.assert_called_once_with("Outlook.Application")

    def test_never_dispatches(self):
        with (
            self.attach_fails(MK_E_UNAVAILABLE),
            mock.patch.object(outlook, "create_dispatch") as dispatch,
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
        for patcher in (
            mock.patch.object(outlook, "CoInitialize", return_value=0),
            mock.patch.object(outlook, "CoUninitialize"),
            mock.patch.object(outlook, "_allow_foreground"),
        ):
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
        get_occurrence.assert_called_once_with(at(1, 10))
        (stamp,), _ = get_occurrence.call_args
        self.assertIsNone(stamp.tzinfo)
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

    def test_starts_outlook_when_none_is_given(self):
        with mock.patch.object(outlook, "create_dispatch", return_value=self.app) as dispatch:
            open_event("E1", "S1", at(1, 10), False)
        dispatch.assert_called_once_with("Outlook.Application")
        self.item.Display.assert_called_once_with()

    def test_com_is_torn_down_only_when_it_was_set_up(self):
        with (
            mock.patch.object(outlook, "CoInitialize", return_value=-2147417850),  # RPC_E_CHANGED_MODE
            mock.patch.object(outlook, "CoUninitialize") as uninitialise,
        ):
            open_event("E1", "S1", at(1, 10), False, application=self.app)
        uninitialise.assert_not_called()

    def test_proxies_are_released_before_com_is_torn_down(self):
        # Plain fakes: a Mock caches its return_value and would keep the item alive.
        events: list[str] = []

        class Item:
            def __del__(self):
                events.append("item released")

            def Display(self) -> None:
                pass

        class Namespace:
            def GetItemFromID(self, entry_id: str, store_id: str) -> Item:
                return Item()

        class Application:
            def GetNamespace(self, name: str) -> Namespace:
                return Namespace()

        with mock.patch.object(outlook, "CoUninitialize", side_effect=lambda: events.append("uninit")):
            open_event("E1", "S1", at(1, 10), False, application=Application())
        self.assertEqual(events, ["item released", "uninit"])

    def test_a_non_com_failure_is_logged_not_raised(self):
        self.app.GetNamespace.return_value.GetItemFromID.side_effect = TypeError("bad id")
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

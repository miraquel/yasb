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

    def test_all_items_unreadable_is_a_failure(self):
        with self.assertRaises(pywintypes.com_error):
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

    def test_proxies_are_released_before_com_is_torn_down(self):
        # Plain fakes: a Mock caches its return_value and would keep the item alive.
        events: list[str] = []

        class Item:
            def __del__(self):
                events.append("item released")

            def Display(self):
                pass

        class Namespace:
            def GetItemFromID(self, entry_id, store_id):
                return Item()

        class Application:
            def GetNamespace(self, name):
                return Namespace()

        with mock.patch.object(outlook.pythoncom, "CoUninitialize", side_effect=lambda: events.append("uninit")):
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

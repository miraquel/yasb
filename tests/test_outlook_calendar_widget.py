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
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

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

    def test_time_format_must_work_with_windows_strftime(self):
        with self.assertRaises(ValidationError):
            OutlookCalendarConfig(time_format="%-I:%M")
        self.assertEqual(OutlookCalendarConfig(time_format="%I:%M %p").time_format, "%I:%M %p")

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

    def test_text_fills_a_fixed_width(self):
        # A theme that reserves a fixed slot (max-width) gets the text cut to the slot in pixels,
        # instead of a character-capped title that leaves the rest of the slot empty.
        widget = self.make(
            live(ev(at(1, 11), at(1, 12), "Quarterly planning with the finance team")), max_title_length=0
        )
        label = widget._widgets[1]
        label.setStyleSheet("max-width: 120px;")
        widget._update_label()
        text = label.text()
        self.assertTrue(text.startswith("in 2h · Quarterly"), text)
        self.assertTrue(text.endswith("…"), text)
        self.assertLessEqual(label.fontMetrics().horizontalAdvance(text), 120)

    def test_text_is_untouched_without_a_fixed_width(self):
        widget = self.make(
            live(ev(at(1, 11), at(1, 12), "Quarterly planning with the finance team")), max_title_length=0
        )
        self.assertEqual(self.text(widget), "in 2h · Quarterly planning with the finance team")

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
        host.setProperty("class", "outlook-calendar-menu")
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
        events = [ev(at(1 + i // 4, 10 + i % 4), at(1 + i // 4, 10 + i % 4, 30), f"Event {i}") for i in range(20)]
        host = self.fill(self.make(live(*events), menu={"max_rows": 5}))
        self.assertEqual(len(by_class(host, "event-row")), 5)

    def test_row_cap_says_how_many_more(self):
        events = [ev(at(1 + i // 4, 10 + i % 4), at(1 + i // 4, 10 + i % 4, 30), f"Event {i}") for i in range(20)]
        host = self.fill(self.make(live(*events), menu={"max_rows": 5}))
        self.assertEqual(self.texts(host, "more"), ["+15 more"])

    def test_no_more_line_without_truncation(self):
        host = self.fill(self.make(live(ev(at(1, 11), at(1, 12)), all_day(2, 2))))
        self.assertEqual(by_class(host, "more"), [])

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

    def test_row_text_shares_a_baseline_with_its_time(self):
        # Different fonts and sizes, as in a real theme, and a Join button that makes the row taller.
        APP.setStyleSheet(
            '.outlook-calendar-menu .event-row .time { font-family: "Bahnschrift"; font-size: 13px; padding-right: 12px; }'
            '.outlook-calendar-menu .event-row .subject { font-family: "Segoe UI"; font-size: 13px; }'
            ".outlook-calendar-menu .event-row .location { font-size: 11px; }"
            ".outlook-calendar-menu .event-row .join { font-size: 12px; padding: 3px 10px; }"
        )
        self.addCleanup(APP.setStyleSheet, "")
        snapshot = live(
            ev(at(1, 11), at(1, 12), "Plain"),
            ev(at(1, 12), at(1, 13), "Located", location="Room 4"),
            ev(at(1, 14), at(1, 15), "With link", join_url=ZOOM),
        )
        host = self.fill(self.make(snapshot))
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        host.show()
        APP.processEvents()

        def baseline(row: QWidget, cls: str) -> int:
            label = by_class(row, cls)[0]
            metrics = label.fontMetrics()
            return label.mapTo(row, QPoint(0, 0)).y() + (label.height() - metrics.height()) // 2 + metrics.ascent()

        for row in by_class(host, "event-row"):
            self.assertLessEqual(abs(baseline(row, "time") - baseline(row, "subject")), 1, row.findChild(QLabel).text())

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

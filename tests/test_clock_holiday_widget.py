"""Widget-level tests for the clock's next-holiday countdown: bar placeholders and the calendar popup block.

Time is frozen by patching ``datetime`` inside the clock module, holidays come from the real
``holidays`` package, and the popup is a hidden QFrame, so no window ever reaches the screen.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

import core.widgets.yasb.clock as clock_module  # noqa: E402
from core.validation.widgets.yasb.clock import ClockConfig  # noqa: E402
from core.widgets.yasb.clock import ClockWidget  # noqa: E402

JAKARTA = ZoneInfo("Asia/Jakarta")
FROZEN = {"now": datetime(2026, 10, 1, 9, 18, tzinfo=JAKARTA)}


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN["now"].astimezone(tz) if tz else FROZEN["now"].astimezone()


class StubPopup(QFrame):
    """Stands in for PopupWidget: same constructor, never positioned, shown off screen."""

    def __init__(self, *args) -> None:
        super().__init__()

    def setPosition(self, **kwargs) -> None:
        pass

    def show(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        super().show()


def by_class(root: QWidget, cls: str) -> QLabel:
    for child in root.findChildren(QWidget):
        if cls in (child.property("class") or "").split():
            return child
    raise AssertionError(f"no descendant with class {cls!r}")


def make_widget(label: str, **calendar) -> ClockWidget:
    calendar.setdefault("country_code", "ID")
    config = ClockConfig(
        label=label, label_alt="{%H:%M}", locale="en-US", timezones=["Asia/Jakarta"], calendar=calendar
    )
    return ClockWidget(config)


class HolidayTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clock_module._get_holidays_module()

    def setUp(self) -> None:
        FROZEN["now"] = datetime(2026, 10, 1, 9, 18, tzinfo=JAKARTA)
        patcher = mock.patch.object(clock_module, "datetime", FrozenDatetime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        clock_module.ClockWidgetSharedState().unregister_widget(getattr(self, "widget", None))


class BarPlaceholderTests(HolidayTestCase):
    def test_span_shows_the_next_holiday_and_countdown(self) -> None:
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday} {holiday_countdown}</span>')
        self.widget.update_label()
        span = self.widget._widgets[1]
        self.assertEqual(span.text(), "Hari Raya Natal 85d")
        self.assertEqual(span.property("class"), "holiday")
        self.assertFalse(span.isHidden())

    def test_placeholders_work_beside_the_time(self) -> None:
        self.widget = make_widget("{%H:%M} {holiday} {holiday_countdown}")
        self.widget.update_label()
        self.assertEqual(self.widget._widgets[0].text(), "09:18 Hari Raya Natal 85d")

    def test_long_names_are_truncated_in_the_bar(self) -> None:
        FROZEN["now"] = datetime(2027, 1, 2, 12, 0, tzinfo=JAKARTA)
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>')
        self.widget.update_label()
        self.assertEqual(self.widget._widgets[1].text(), "Isra Mikraj Nabi...")

    def test_countdown_follows_the_clock(self) -> None:
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday_countdown}</span>')
        FROZEN["now"] = datetime(2026, 12, 24, 9, 28, tzinfo=JAKARTA)
        self.widget.update_label()
        self.assertEqual(self.widget._widgets[1].text(), "14h 32m")

    def test_span_hides_for_an_unsupported_country(self) -> None:
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', country_code="XX")
        self.widget.update_label()
        self.assertTrue(self.widget._widgets[1].isHidden())

    def test_works_without_calendar_show_holidays(self) -> None:
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', show_holidays=False)
        self.widget.update_label()
        self.assertEqual(self.widget._widgets[1].text(), "Hari Raya Natal")

    def test_a_placeholder_alone_detects_the_country(self) -> None:
        # No country_code and show_holidays off: only the placeholder asks Windows for the region.
        self.widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', country_code=None)
        plain = make_widget("{%H:%M}", country_code=None)
        self.addCleanup(clock_module.ClockWidgetSharedState().unregister_widget, plain)
        self.assertRegex(self.widget._country_code or "", r"^[A-Z]{2}$")
        self.assertIsNone(plain._country_code)


class PopupBlockTests(HolidayTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(clock_module, "PopupWidget", StubPopup)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        popup = getattr(getattr(self, "widget", None), "_yasb_calendar", None)
        if popup is not None:
            popup.close()
        super().tearDown()

    def test_block_names_the_holiday_and_counts_down(self) -> None:
        self.widget = make_widget("{%H:%M}", show_next_holiday=True)
        self.widget.show_calendar()
        popup = self.widget._yasb_calendar
        self.assertEqual(by_class(popup, "next-holiday-header").text(), "Next holiday")
        self.assertEqual(by_class(popup, "next-holiday-name").text(), "Hari Raya Natal")
        self.assertEqual(by_class(popup, "next-holiday-date").text(), "Fri 25 Dec · in 85 days")

    def test_open_popup_keeps_counting(self) -> None:
        self.widget = make_widget("{%H:%M}", show_next_holiday=True)
        self.widget.show_calendar()
        FROZEN["now"] = datetime(2026, 12, 24, 9, 28, tzinfo=JAKARTA)
        self.widget.update_label()
        self.assertEqual(by_class(self.widget._yasb_calendar, "next-holiday-date").text(), "Fri 25 Dec · in 14h 32m")

    def test_on_the_day_it_reads_today(self) -> None:
        FROZEN["now"] = datetime(2026, 12, 25, 8, 0, tzinfo=JAKARTA)
        self.widget = make_widget("{%H:%M}", show_next_holiday=True)
        self.widget.show_calendar()
        self.assertEqual(by_class(self.widget._yasb_calendar, "next-holiday-date").text(), "Fri 25 Dec · Today")

    def test_a_deleted_popup_does_not_break_the_tick(self) -> None:
        self.widget = make_widget("{%H:%M}", show_next_holiday=True)
        self.widget.show_calendar()
        popup, self.widget._yasb_calendar = self.widget._yasb_calendar, None
        sip.delete(popup)  # what PopupWidget's deleteLater does after it closes
        self.widget.update_label()

    def test_block_is_off_by_default(self) -> None:
        self.widget = make_widget("{%H:%M}")
        self.widget.show_calendar()
        with self.assertRaises(AssertionError):
            by_class(self.widget._yasb_calendar, "next-holiday")


if __name__ == "__main__":
    unittest.main()

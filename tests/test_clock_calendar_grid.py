"""Tests for the calendar popup's month grid: rest days in red, muted spill-over days, today's ring.

Cells are painted straight into a transparent QImage, so the assertions read real pixels.
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

from pydantic import ValidationError  # noqa: E402
from PyQt6.QtCore import QDate, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTableView  # noqa: E402

APP = QApplication.instance() or QApplication([])

import core.widgets.yasb.clock as clock_module  # noqa: E402
from core.validation.widgets.yasb.clock import ClockCalendarConfig  # noqa: E402

JAKARTA = ZoneInfo("Asia/Jakarta")
FROZEN = datetime(2026, 10, 1, 9, 18, tzinfo=JAKARTA)
CELL = 40
RED = "#ee5d5a"


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN.astimezone(tz) if tz else FROZEN.astimezone()


def paint(calendar, qdate: QDate) -> QImage:
    """Paint one cell of *calendar* into a transparent image."""
    image = QImage(CELL, CELL, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calendar.paintCell(painter, QRect(0, 0, CELL, CELL), qdate)
    painter.end()
    return image


def strongest_ink(image: QImage) -> QColor:
    """The most opaque pixel in *image*: the numeral's colour, free of anti-aliasing."""
    best = QColor(0, 0, 0, 0)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > best.alpha():
                best = pixel
    return best


def is_red(color: QColor) -> bool:
    # By hue, not brightness: a translucent pixel reads back with every channel dimmed.
    return color.red() > 1.8 * color.green() and color.red() > 1.8 * color.blue()


class GridTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clock_module._get_holidays_module()

    def setUp(self) -> None:
        patcher = mock.patch.object(clock_module, "datetime", FrozenDatetime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_calendar(self, rest_days=("sunday",)):
        calendar = clock_module.CustomCalendar(
            None,
            "Asia/Jakarta",
            "ID",
            show_holidays=True,
            holiday_color=RED,
            rest_days=list(rest_days),
        )
        calendar.setProperty("textcolor", QColor("#ece9e4"))
        self.addCleanup(calendar.deleteLater)
        return calendar


class RestDayTests(GridTestCase):
    def test_sundays_are_red(self) -> None:
        self.assertTrue(is_red(strongest_ink(paint(self.make_calendar(), QDate(2026, 10, 4)))))

    def test_weekdays_are_not(self) -> None:
        self.assertFalse(is_red(strongest_ink(paint(self.make_calendar(), QDate(2026, 10, 5)))))

    def test_sundays_stay_plain_without_rest_days(self) -> None:
        self.assertFalse(is_red(strongest_ink(paint(self.make_calendar(rest_days=()), QDate(2026, 10, 4)))))

    def test_public_holidays_are_red(self) -> None:
        calendar = self.make_calendar(rest_days=())
        calendar.setCurrentPage(2026, 12)
        self.assertTrue(is_red(strongest_ink(paint(calendar, QDate(2026, 12, 25)))))

    def test_the_sunday_header_is_red_too(self) -> None:
        calendar = self.make_calendar()
        self.assertEqual(calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color(), QColor(RED))
        self.assertNotEqual(calendar.weekdayTextFormat(Qt.DayOfWeek.Monday).foreground().color(), QColor(RED))

    def test_the_stylesheet_can_recolour_rest_days(self) -> None:
        calendar = self.make_calendar()
        calendar.setProperty("restcolor", QColor("#20c040"))
        ink = strongest_ink(paint(calendar, QDate(2026, 10, 4)))
        self.assertGreater(ink.green(), 150)
        self.assertLess(ink.red(), 100)
        self.assertEqual(calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color(), QColor("#20c040"))


class SpillOverTests(GridTestCase):
    def test_days_from_other_months_are_muted(self) -> None:
        calendar = self.make_calendar()
        october = strongest_ink(paint(calendar, QDate(2026, 10, 2)))
        september = strongest_ink(paint(calendar, QDate(2026, 9, 29)))
        self.assertLess(september.alpha(), october.alpha() * 0.6)

    def test_a_muted_sunday_keeps_its_red(self) -> None:
        ink = strongest_ink(paint(self.make_calendar(), QDate(2026, 9, 27)))
        self.assertTrue(is_red(ink))
        self.assertLess(ink.alpha(), 160)


class TodayTests(GridTestCase):
    def ring_pixel(self, image: QImage) -> QColor:
        # Left edge of the ring, level with the numeral's centre: no glyph reaches out that far.
        return max((image.pixelColor(x, CELL // 2) for x in range(6)), key=QColor.alpha)

    def test_today_is_circled(self) -> None:
        self.assertGreater(self.ring_pixel(paint(self.make_calendar(), QDate(2026, 10, 1))).alpha(), 80)

    def test_other_days_are_not(self) -> None:
        self.assertEqual(self.ring_pixel(paint(self.make_calendar(), QDate(2026, 10, 2))).alpha(), 0)


class SelectionTests(GridTestCase):
    def disc_pixel(self, image: QImage) -> QColor:
        # Inside the disc, left of the numeral.
        return image.pixelColor(8, CELL // 2)

    def test_selectcolor_fills_a_disc_behind_the_selected_date(self) -> None:
        calendar = self.make_calendar()
        calendar.setProperty("selectcolor", QColor(236, 234, 228, 40))
        calendar.setSelectedDate(QDate(2026, 10, 2))
        self.assertGreater(self.disc_pixel(paint(calendar, QDate(2026, 10, 2))).alpha(), 20)
        self.assertEqual(self.disc_pixel(paint(calendar, QDate(2026, 10, 3))).alpha(), 0)

    def green_pixels(self, calendar) -> int:
        # An application stylesheet, the way yasb applies styles.css.
        APP.setStyleSheet(".calendar-table::item:selected { color: #00ff00; }")
        self.addCleanup(APP.setStyleSheet, "")
        calendar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        calendar.resize(320, 220)
        calendar.show()
        APP.processEvents()
        image = calendar.grab().toImage()
        count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                count += pixel.green() > 200 and pixel.red() < 80 and pixel.blue() < 80
        return count

    def test_the_selected_date_keeps_the_themes_item_selected_colour(self) -> None:
        # Themes colour the selected date through ::item:selected; with no selectcolor that still works.
        self.assertGreater(self.green_pixels(self.make_calendar()), 5)

    def test_selectcolor_takes_over_from_item_selected(self) -> None:
        calendar = self.make_calendar()
        calendar.setProperty("selectcolor", QColor(236, 234, 228, 40))
        self.assertEqual(self.green_pixels(calendar), 0)


class GridStyleTests(GridTestCase):
    def test_grid_is_classed_for_the_stylesheet(self) -> None:
        self.assertIn("calendar-grid", self.make_calendar().property("class").split())

    def test_selectcolor_drops_the_windows11_selection_marker(self) -> None:
        # windows11 draws an accent bar beside the selected cell; once the grid draws the selection
        # itself, its table switches to windowsvista, which draws no bar.
        calendar = self.make_calendar()
        calendar.setProperty("selectcolor", QColor(236, 234, 228, 40))
        self.assertEqual(calendar.findChild(QTableView).style().name(), "windowsvista")

    def test_themes_without_selectcolor_keep_the_app_style(self) -> None:
        # Swapping the style would cost them their ::item:selected colours.
        table = self.make_calendar().findChild(QTableView)
        self.assertEqual(table.style().name(), APP.style().name())


class RestDaysConfigTests(unittest.TestCase):
    def test_defaults_to_none(self) -> None:
        self.assertEqual(ClockCalendarConfig().rest_days, [])

    def test_accepts_weekday_names(self) -> None:
        self.assertEqual(ClockCalendarConfig(rest_days=["sunday", "friday"]).rest_days, ["sunday", "friday"])

    def test_rejects_anything_else(self) -> None:
        with self.assertRaises(ValidationError):
            ClockCalendarConfig(rest_days=["funday"])


if __name__ == "__main__":
    unittest.main()

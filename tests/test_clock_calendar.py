"""Tests for the clock's month grid geometry.

The grid is given a fixed width by the stylesheet and stretches seven columns to fill it.
Qt will not stretch a section below the minimum it derives from the horizontal header's
font, and that font comes from the stylesheet, where a broad ``* { font-family }`` rule can
leave it a wide monospace face. When seven of those minimums outgrow the width the grid was
given, the surplus falls off the right-hand edge and Sunday's column is clipped mid-digit.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTableView  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.widgets.yasb.clock import CustomCalendar  # noqa: E402

# The width the maintainer's stylesheet pins .calendar-grid to; any fixed width does.
GRID_WIDTH = 259
DAYS_IN_WEEK = 7


class MonthGridWidthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar = CustomCalendar(None, None, "ID", show_holidays=False, holiday_color="#FF6464")
        self.calendar.setFixedWidth(GRID_WIDTH)
        self.table = self.calendar.findChild(QTableView)
        self.assertIsNotNone(self.table)

    def tearDown(self) -> None:
        self.calendar.close()
        self.calendar.deleteLater()

    def column_widths(self, header_px: int | None = None) -> list[int]:
        header = self.table.horizontalHeader()
        if header_px is not None:
            font = QFont("CaskaydiaCove NFP")
            font.setPixelSize(header_px)
            header.setFont(font)
        self.calendar.show()
        APP.processEvents()
        return [header.sectionSize(i) for i in range(header.count())]

    def test_seven_columns_fill_the_grid_exactly(self) -> None:
        widths = self.column_widths()

        self.assertEqual(len(widths), DAYS_IN_WEEK)
        self.assertEqual(sum(widths), GRID_WIDTH)

    def test_a_wide_header_font_cannot_push_sunday_off_the_edge(self) -> None:
        """At 16px the style-derived floor was 38px, and 7x38 overran 259 by half a digit."""
        for header_px in (12, 16, 22, 28):
            with self.subTest(header_px=header_px):
                self.assertEqual(sum(self.column_widths(header_px)), GRID_WIDTH)

    def test_no_column_collapses_while_the_others_take_the_room(self) -> None:
        """Dropping the floor must not let the stretch hand one column everything."""
        widths = self.column_widths(22)

        self.assertEqual(max(widths) - min(widths), 0 if GRID_WIDTH % DAYS_IN_WEEK == 0 else 1)

    def test_rows_are_free_to_fit_a_pinned_height(self) -> None:
        self.calendar.setFixedHeight(232)
        self.calendar.show()
        APP.processEvents()
        vertical = self.table.verticalHeader()
        heights = [vertical.sectionSize(i) for i in range(vertical.count())]

        self.assertLessEqual(sum(heights), self.table.viewport().height())


class ColumnsSurviveRestylingTest(unittest.TestCase):
    """The stylesheet lands on the popup after the grid is built, and paging rebuilds its model.

    Both hand the sections back to Qt's own sizing, which is where the first attempt at this
    fix leaked: the columns were divided correctly once and then quietly re-widened.
    """

    def setUp(self) -> None:
        self.calendar = CustomCalendar(None, None, "ID", show_holidays=False, holiday_color="#FF6464")
        self.calendar.setFixedWidth(GRID_WIDTH)
        self.table = self.calendar.findChild(QTableView)
        self.calendar.show()
        APP.processEvents()

    def tearDown(self) -> None:
        self.calendar.close()
        self.calendar.deleteLater()

    def total(self) -> int:
        header = self.table.horizontalHeader()
        return sum(header.sectionSize(i) for i in range(header.count()))

    def test_a_stylesheet_applied_afterwards_cannot_widen_them(self) -> None:
        self.calendar.setStyleSheet('QWidget { font-family: "CaskaydiaCove NFP"; font-size: 18px; }')
        APP.processEvents()

        self.assertEqual(self.total(), self.table.viewport().width())

    def test_paging_to_another_month_keeps_them_divided(self) -> None:
        for _ in range(3):
            self.calendar.showNextMonth()
            APP.processEvents()

        self.assertEqual(self.total(), self.table.viewport().width())

    def test_a_narrower_grid_is_redivided_rather_than_overrun(self) -> None:
        """A tighter pin in styles.css must shrink the columns, not push Sunday off the edge."""
        for width in (259, 220, 180, 140):
            with self.subTest(width=width):
                self.calendar.setFixedWidth(width)
                APP.processEvents()
                self.assertEqual(self.total(), self.table.viewport().width())

    def test_columns_stay_within_a_pixel_of_each_other(self) -> None:
        header = self.table.horizontalHeader()
        widths = [header.sectionSize(i) for i in range(header.count())]

        self.assertLessEqual(max(widths) - min(widths), 1)


if __name__ == "__main__":
    unittest.main()

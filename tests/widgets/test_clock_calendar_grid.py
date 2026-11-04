# pyright: reportPrivateUsage=false
"""The calendar popup's month grid: rest days, muted spill-over days, today's ring and the selection.

Cells are painted straight into a transparent QImage, so the assertions read real pixels.
"""

from collections.abc import Callable, Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from PyQt6.QtCore import QDate, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QTableView

import core.widgets.yasb.clock as clock_module
from core.validation.widgets.yasb.clock import ClockCalendarConfig
from core.widgets.yasb.clock import CustomCalendar
from tests.support.clock import freeze_clock

JAKARTA = ZoneInfo("Asia/Jakarta")
FROZEN = datetime(2026, 10, 1, 9, 18, tzinfo=JAKARTA)
CELL = 40
RED = "#ee5d5a"
TEXT = QColor("#ece9e4")
SELECT = QColor(236, 234, 228, 40)

type MakeCalendar = Callable[..., CustomCalendar]


@pytest.fixture
def make_calendar(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeCalendar]:
    clock_module._get_holidays_module()
    freeze_clock(monkeypatch, FROZEN)
    calendars: list[CustomCalendar] = []

    def make(rest_days: tuple[str, ...] = ("sunday",), **qproperties: QColor) -> CustomCalendar:
        calendar = CustomCalendar(
            None, "Asia/Jakarta", "ID", show_holidays=True, holiday_color=RED, rest_days=list(rest_days)
        )
        for name, value in qproperties.items():
            calendar.setProperty(name, value)
        calendars.append(calendar)
        return calendar

    yield make
    for calendar in calendars:
        calendar.close()
        calendar.deleteLater()


def _paint(calendar: CustomCalendar, qdate: QDate) -> QImage:
    """Paint one cell of *calendar* into a transparent image."""
    image = QImage(CELL, CELL, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calendar.paintCell(painter, QRect(0, 0, CELL, CELL), qdate)
    painter.end()
    return image


def _strongest_ink(image: QImage) -> QColor:
    """The most opaque pixel in *image*: the numeral's colour, free of anti-aliasing."""
    best = QColor(0, 0, 0, 0)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > best.alpha():
                best = pixel
    return best


def _is_red(color: QColor) -> bool:
    # By hue, not brightness: a translucent pixel reads back with every channel dimmed.
    return color.red() > 1.8 * color.green() and color.red() > 1.8 * color.blue()


def _ring_pixel(image: QImage) -> QColor:
    # Left edge of the ring, level with the numeral's centre: no glyph reaches out that far.
    return max((image.pixelColor(x, CELL // 2) for x in range(6)), key=QColor.alpha)


def _disc_pixel(image: QImage) -> QColor:
    # Inside the disc, left of the numeral.
    return image.pixelColor(8, CELL // 2)


def _table(calendar: CustomCalendar) -> QTableView:
    table = calendar.findChild(QTableView)
    assert table is not None
    return table


# --- rest days and holidays ----------------------------------------------------------


def test_sundays_are_red(make_calendar: MakeCalendar):
    assert _is_red(_strongest_ink(_paint(make_calendar(textcolor=TEXT), QDate(2026, 10, 4))))


def test_weekdays_are_not(make_calendar: MakeCalendar):
    assert not _is_red(_strongest_ink(_paint(make_calendar(textcolor=TEXT), QDate(2026, 10, 5))))


def test_sundays_stay_plain_without_rest_days(make_calendar: MakeCalendar):
    assert not _is_red(_strongest_ink(_paint(make_calendar(rest_days=(), textcolor=TEXT), QDate(2026, 10, 4))))


def test_public_holidays_are_red(make_calendar: MakeCalendar):
    calendar = make_calendar(rest_days=(), textcolor=TEXT)
    calendar.setCurrentPage(2026, 12)
    assert _is_red(_strongest_ink(_paint(calendar, QDate(2026, 12, 25))))


def test_public_holidays_are_red_without_any_qproperty(make_calendar: MakeCalendar):
    # holiday_color alone, as before this grid learned qproperties.
    calendar = make_calendar(rest_days=())
    calendar.setCurrentPage(2026, 12)
    assert _is_red(_strongest_ink(_paint(calendar, QDate(2026, 12, 25))))


def test_the_sunday_header_is_red_too(make_calendar: MakeCalendar):
    calendar = make_calendar()
    assert calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color() == QColor(RED)
    assert calendar.weekdayTextFormat(Qt.DayOfWeek.Monday).foreground().color() != QColor(RED)


def test_the_stylesheet_can_recolour_rest_days(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT, restcolor=QColor("#20c040"))
    ink = _strongest_ink(_paint(calendar, QDate(2026, 10, 4)))
    assert ink.green() > 150
    assert ink.red() < 100
    assert calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color() == QColor("#20c040")


# --- dates from the neighbouring months ----------------------------------------------


def test_days_from_other_months_are_muted(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT)
    october = _strongest_ink(_paint(calendar, QDate(2026, 10, 2)))
    september = _strongest_ink(_paint(calendar, QDate(2026, 9, 29)))
    assert september.alpha() < october.alpha() * 0.6


def test_mutedcolor_paints_them(make_calendar: MakeCalendar):
    ink = _strongest_ink(_paint(make_calendar(mutedcolor=QColor("#2040ff")), QDate(2026, 9, 29)))
    assert ink.blue() > 200
    assert ink.red() < 100


def test_a_muted_sunday_keeps_its_red(make_calendar: MakeCalendar):
    ink = _strongest_ink(_paint(make_calendar(textcolor=TEXT), QDate(2026, 9, 27)))
    assert _is_red(ink)
    assert ink.alpha() < 160


def test_without_grid_colours_a_neighbouring_holiday_stays_unmuted(make_calendar: MakeCalendar):
    ink = _strongest_ink(_paint(make_calendar(), QDate(2026, 9, 27)))
    assert _is_red(ink)
    assert ink.alpha() > 200


# --- today ---------------------------------------------------------------------------


def test_ringcolor_circles_today(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT, ringcolor=TEXT)
    assert _ring_pixel(_paint(calendar, QDate(2026, 10, 1))).alpha() > 80


def test_ringcolor_leaves_other_days_alone(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT, ringcolor=TEXT)
    assert _ring_pixel(_paint(calendar, QDate(2026, 10, 2))).alpha() == 0


def test_today_has_no_ring_without_ringcolor(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT)
    calendar.setSelectedDate(QDate(2026, 10, 2))
    assert _ring_pixel(_paint(calendar, QDate(2026, 10, 1))).alpha() == 0


# --- an unstyled grid paints like Qt -------------------------------------------------


def test_plain_dates_are_left_to_qt_without_grid_colours(make_calendar: MakeCalendar, monkeypatch: pytest.MonkeyPatch):
    calendar = make_calendar()
    painted: list[QDate] = []

    def base_paint(self: CustomCalendar, painter: QPainter, rect: QRect, date: QDate) -> None:
        painted.append(date)

    monkeypatch.setattr(clock_module.QCalendarWidget, "paintCell", base_paint)
    for qdate in (QDate(2026, 10, 2), QDate(2026, 9, 29), QDate(2026, 10, 4), QDate(2026, 10, 1)):
        _paint(calendar, qdate)
    # Weekdays from either month, and the selected date (today); not the red Sunday.
    assert painted == [QDate(2026, 10, 2), QDate(2026, 9, 29), QDate(2026, 10, 1)]


# --- the selection -------------------------------------------------------------------


def _green_pixels(app: QApplication, calendar: CustomCalendar) -> int:
    # An application stylesheet, the way yasb applies styles.css. The background is part of the
    # rule because the offscreen platform only applies ::item:selected's colour alongside one.
    app.setStyleSheet(".calendar-table::item:selected { background-color: transparent; color: #00ff00; }")
    try:
        calendar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        calendar.resize(320, 220)
        calendar.show()
        app.processEvents()
        image = calendar.grab().toImage()
    finally:
        app.setStyleSheet("")
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            count += pixel.green() > 200 and pixel.red() < 80 and pixel.blue() < 80
    return count


def test_selectcolor_fills_a_disc_behind_the_selected_date(make_calendar: MakeCalendar):
    calendar = make_calendar(textcolor=TEXT, selectcolor=SELECT)
    calendar.setSelectedDate(QDate(2026, 10, 2))
    assert _disc_pixel(_paint(calendar, QDate(2026, 10, 2))).alpha() > 20
    assert _disc_pixel(_paint(calendar, QDate(2026, 10, 3))).alpha() == 0


def test_the_selected_date_keeps_the_themes_item_selected_colour(qapp: QApplication, make_calendar: MakeCalendar):
    # Themes colour the selected date through ::item:selected; with no selectcolor that still works.
    assert _green_pixels(qapp, make_calendar(textcolor=TEXT)) > 5


def test_selectcolor_takes_over_from_item_selected(qapp: QApplication, make_calendar: MakeCalendar):
    assert _green_pixels(qapp, make_calendar(textcolor=TEXT, selectcolor=SELECT)) == 0


def test_grid_is_classed_for_the_stylesheet(make_calendar: MakeCalendar):
    assert "calendar-grid" in str(make_calendar().property("class")).split()


def test_selectcolor_drops_the_windows11_selection_marker(make_calendar: MakeCalendar):
    # windows11 draws an accent bar beside the selected cell; once the grid draws the selection
    # itself, its table switches to windowsvista, which draws no bar.
    calendar = make_calendar(selectcolor=SELECT)
    style = _table(calendar).style()
    assert style is not None
    assert style.name() == "windowsvista"


def test_themes_without_selectcolor_keep_the_app_style(qapp: QApplication, make_calendar: MakeCalendar):
    # Swapping the style would cost them their ::item:selected colours.
    table_style = _table(make_calendar()).style()
    app_style = qapp.style()
    assert table_style is not None
    assert app_style is not None
    assert table_style.name() == app_style.name()


# --- config --------------------------------------------------------------------------


def test_rest_days_default_to_none():
    assert ClockCalendarConfig().rest_days == []


def test_rest_days_accept_weekday_names():
    assert ClockCalendarConfig.model_validate({"rest_days": ["sunday", "friday"]}).rest_days == ["sunday", "friday"]


def test_rest_days_reject_anything_else():
    with pytest.raises(ValidationError):
        ClockCalendarConfig.model_validate({"rest_days": ["funday"]})

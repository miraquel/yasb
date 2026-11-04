# pyright: reportPrivateUsage=false
"""The clock's next-holiday countdown: the bar placeholders and the calendar popup block.

Time is frozen by patching ``datetime`` inside the clock module, holidays come from the installed
``holidays`` package (no network), and the popup is a hidden QFrame, so no window reaches the screen.
"""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QLayout, QWidget

import core.widgets.yasb.clock as clock_module
from core.validation.widgets.yasb.clock import ClockConfig
from core.widgets.yasb.clock import ClockWidget
from tests.support.clock import FrozenClock, freeze_clock

JAKARTA = ZoneInfo("Asia/Jakarta")

type MakeWidget = Callable[..., ClockWidget]


class _StubPopup(QFrame):
    """Stands in for PopupWidget: same constructor, never positioned, shown off screen."""

    def __init__(self, *args: object) -> None:
        super().__init__()

    def setPosition(self, **kwargs: object) -> None:
        pass

    def show(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        super().show()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    clock_module._get_holidays_module()
    monkeypatch.setattr(clock_module, "PopupWidget", _StubPopup)
    return freeze_clock(monkeypatch, datetime(2026, 10, 1, 9, 18, tzinfo=JAKARTA))


@pytest.fixture
def make_widget(qapp: QApplication, clock: FrozenClock) -> Iterator[MakeWidget]:
    widgets: list[ClockWidget] = []

    def make(label: str, **calendar: Any) -> ClockWidget:
        calendar.setdefault("country_code", "ID")
        config = ClockConfig.model_validate(
            {
                "label": label,
                "label_alt": "{%H:%M}",
                "locale": "en-US",
                "timezones": ["Asia/Jakarta"],
                "calendar": calendar,
            }
        )
        widget = ClockWidget(config)
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        popup: QWidget | None = getattr(widget, "_yasb_calendar", None)
        if popup is not None and not sip.isdeleted(popup):
            popup.close()
        clock_module.ClockWidgetSharedState().unregister_widget(widget)


def _by_class(root: QWidget, cls: str) -> QWidget:
    for child in root.findChildren(QWidget):
        if cls in str(child.property("class") or "").split():
            return child
    raise LookupError(f"no descendant with class {cls!r}")


def _text(root: QWidget, cls: str) -> str:
    label = _by_class(root, cls)
    assert isinstance(label, QLabel)
    return label.text()


def _has_class(root: QWidget, cls: str) -> bool:
    try:
        _by_class(root, cls)
    except LookupError:
        return False
    return True


def _popup(widget: ClockWidget) -> QWidget:
    widget.show_calendar()
    return widget._yasb_calendar


# --- bar placeholders ----------------------------------------------------------------


def test_span_shows_the_next_holiday_and_countdown(make_widget: MakeWidget):
    widget = make_widget('{%H:%M}<span class="holiday">{holiday} {holiday_countdown}</span>')
    widget.update_label()
    span = widget._widgets[1]
    assert span.text() == "Hari Raya Natal 85d"
    assert span.property("class") == "holiday"
    assert not span.isHidden()


def test_placeholders_work_beside_the_time(make_widget: MakeWidget):
    widget = make_widget("{%H:%M} {holiday} {holiday_countdown}")
    widget.update_label()
    assert widget._widgets[0].text() == "09:18 Hari Raya Natal 85d"


def test_long_names_are_truncated_in_the_bar(make_widget: MakeWidget, clock: FrozenClock):
    clock.current = datetime(2027, 1, 2, 12, 0, tzinfo=JAKARTA)
    widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>')
    widget.update_label()
    assert widget._widgets[1].text() == "Isra Mikraj Nabi..."


def test_countdown_follows_the_clock(make_widget: MakeWidget, clock: FrozenClock):
    widget = make_widget('{%H:%M}<span class="holiday">{holiday_countdown}</span>')
    clock.current = datetime(2026, 12, 24, 9, 28, tzinfo=JAKARTA)
    widget.update_label()
    assert widget._widgets[1].text() == "14h 32m"


def test_span_hides_for_an_unsupported_country(make_widget: MakeWidget):
    widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', country_code="XX")
    widget.update_label()
    assert widget._widgets[1].isHidden()


def test_works_without_calendar_show_holidays(make_widget: MakeWidget):
    widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', show_holidays=False)
    widget.update_label()
    assert widget._widgets[1].text() == "Hari Raya Natal"


def test_a_placeholder_alone_detects_the_country(make_widget: MakeWidget):
    # No country_code and show_holidays off: only the placeholder asks Windows for the region.
    widget = make_widget('{%H:%M}<span class="holiday">{holiday}</span>', country_code=None)
    plain = make_widget("{%H:%M}", country_code=None)
    assert len(widget._country_code or "") == 2
    assert plain._country_code is None


# --- the popup block -----------------------------------------------------------------


def test_block_names_the_holiday_and_counts_down(make_widget: MakeWidget):
    popup = _popup(make_widget("{%H:%M}", show_next_holiday=True))
    assert _text(popup, "next-holiday-countdown") == "85 days until"
    assert _text(popup, "next-holiday-name") == "Hari Raya Natal"
    assert _text(popup, "next-holiday-date") == "Friday 25 December"


def test_block_has_no_label_above_it(make_widget: MakeWidget):
    assert not _has_class(_popup(make_widget("{%H:%M}", show_next_holiday=True)), "next-holiday-header")


def test_open_popup_keeps_counting(make_widget: MakeWidget, clock: FrozenClock):
    widget = make_widget("{%H:%M}", show_next_holiday=True)
    popup = _popup(widget)
    clock.current = datetime(2026, 12, 24, 9, 28, tzinfo=JAKARTA)
    widget.update_label()
    assert _text(popup, "next-holiday-countdown") == "14h 32m until"


def test_on_the_day_it_reads_today(make_widget: MakeWidget, clock: FrozenClock):
    clock.current = datetime(2026, 12, 25, 8, 0, tzinfo=JAKARTA)
    popup = _popup(make_widget("{%H:%M}", show_next_holiday=True))
    assert _text(popup, "next-holiday-countdown") == "Today"
    assert _text(popup, "next-holiday-name") == "Hari Raya Natal"
    assert _text(popup, "next-holiday-date") == "Friday 25 December"


def test_on_a_holiday_the_block_looks_past_the_one_the_heading_names(make_widget: MakeWidget, clock: FrozenClock):
    # show_holidays already puts "Hari Raya Natal" under the date, so the block moves on.
    clock.current = datetime(2026, 12, 25, 8, 0, tzinfo=JAKARTA)
    popup = _popup(make_widget("{%H:%M}", show_next_holiday=True, show_holidays=True))
    assert _text(popup, "holiday-label") == "Hari Raya Natal"
    assert _text(popup, "next-holiday-countdown") == "6d 16h until"
    assert _text(popup, "next-holiday-name") == "Tahun Baru Masehi"
    assert _text(popup, "next-holiday-date") == "Friday 1 January"


def test_the_bar_still_says_today(make_widget: MakeWidget, clock: FrozenClock):
    clock.current = datetime(2026, 12, 25, 8, 0, tzinfo=JAKARTA)
    widget = make_widget(
        '{%H:%M}<span class="holiday">{holiday} {holiday_countdown}</span>',
        show_next_holiday=True,
        show_holidays=True,
    )
    widget.show_calendar()
    widget.update_label()
    assert widget._widgets[1].text() == "Hari Raya Natal Today"


def test_grid_and_date_panel_hang_from_the_top(make_widget: MakeWidget):
    widget = make_widget("{%H:%M}", show_next_holiday=True)
    widget.show_calendar()
    parent = widget.calendar.parentWidget()
    assert parent is not None
    layout = parent.layout()
    assert layout is not None
    grid = layout.itemAt(layout.indexOf(widget.calendar))
    date_panel = layout.itemAt(0)
    assert grid is not None and date_panel is not None
    assert grid.alignment() & Qt.AlignmentFlag.AlignTop
    date_layout = date_panel.layout()
    assert date_layout is not None
    assert date_layout.alignment() & Qt.AlignmentFlag.AlignTop


def test_content_sits_in_a_frame_the_stylesheet_can_pad(qapp: QApplication, make_widget: MakeWidget):
    # PopupWidget is a bare QWidget, which ignores QSS padding; a QFrame inside it takes it.
    widget = make_widget("{%H:%M}", show_next_holiday=True)
    popup = _popup(widget)
    container = _by_class(popup, "calendar-container")
    assert isinstance(container, QFrame)
    assert widget.calendar.parentWidget() is container

    def activate(layout: QLayout | None) -> None:
        assert layout is not None
        layout.activate()

    def day_label_x() -> int:
        activate(popup.layout())
        activate(container.layout())
        return widget.day_label.mapTo(popup, QPoint(0, 0)).x()

    before = day_label_x()
    qapp.setStyleSheet(".calendar-container { padding: 0 0 0 20px; }")
    try:
        qapp.processEvents()
        assert day_label_x() - before == 20
    finally:
        qapp.setStyleSheet("")


def test_a_deleted_popup_does_not_break_the_tick(make_widget: MakeWidget):
    widget = make_widget("{%H:%M}", show_next_holiday=True)
    sip.delete(_popup(widget))  # what PopupWidget's deleteLater does after it closes
    widget.update_label()


def test_block_is_off_by_default(make_widget: MakeWidget):
    assert not _has_class(_popup(make_widget("{%H:%M}")), "next-holiday")

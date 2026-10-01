"""Outlook calendar widget: counts down to the next event on the default Outlook calendar.

The shared ``OutlookCalendarService`` reads Outlook over COM and caches what it read, so this
class only renders: the label, tooltip and popup are re-derived from the latest snapshot and
the wall clock on every service update, at least every 30 seconds.
"""

import html
import re
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from core.utils.tooltip import set_tooltip
from core.utils.utilities import ElidedLabel, PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.outlook_calendar import OutlookCalendarConfig
from core.widgets.base import BaseWidget
from core.widgets.services.outlook_calendar.agenda import (
    CalEvent,
    day_heading,
    day_start,
    format_countdown,
    format_status,
    format_time_range,
    group_by_day,
    row_status,
    select_event,
    shorten,
    today_count,
)
from core.widgets.services.outlook_calendar.outlook import open_calendar, open_event_in_background
from core.widgets.services.outlook_calendar.service import OutlookCalendarService

_UNAVAILABLE_TEXT = "Outlook unavailable"
_PLACEHOLDER_RE = re.compile(r"\{\w+\}")


def _label(cls: str, text: str = "", kind: type[QLabel] = QLabel) -> QLabel:
    """A plain-text popup label carrying *cls*, with QLabel's automatic indent switched off.

    Event subjects are user text: read as rich text, "Review <draft>" would lose its tag.
    The default indent of -1 becomes half an 'x' of the font as soon as a stylesheet adds
    padding, so labels in one column would no longer share a left edge.
    """
    label = kind()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("class", cls)
    label.setIndent(0)
    label.setText(text)
    return label


def fit_to_width(widget: QWidget) -> None:
    """Size *widget* to its contents, measuring wrapped text at the width it really gets."""
    widget.adjustSize()
    layout = widget.layout()
    if layout is not None and layout.hasHeightForWidth():
        widget.resize(widget.width(), layout.totalHeightForWidth(widget.width()))


def _open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class _EventRow(QFrame):
    """A popup row that hands its event to *on_click* when clicked."""

    def __init__(self, event: CalEvent, on_click, parent: QWidget | None = None):
        super().__init__(parent)
        self.event = event
        self._on_click = on_click
        self.time_label: QLabel
        self.subject: QLabel
        self.time_gap: QSpacerItem
        self.text_gap: QSpacerItem
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, mouse_event):
        if mouse_event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.event)
        super().mousePressEvent(mouse_event)


class OutlookCalendarWidget(BaseWidget):
    """Counts down to the next event on the default Outlook calendar; the popup lists the days."""

    validation_schema = OutlookCalendarConfig

    def __init__(self, config: OutlookCalendarConfig):
        super().__init__(class_name=f"outlook-calendar-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._service_released = False
        self._popup: QWidget | None = None
        self._popup_layout: QVBoxLayout | None = None

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        for label in (*self._widgets, *self._widgets_alt):
            label.setProperty("base_class", label.property("class") or "")
            label.setTextFormat(Qt.TextFormat.PlainText)

        self.register_callback("toggle_card", self._toggle_card)
        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("refresh", self._refresh)
        self.register_callback("open_outlook", self._open_outlook)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle

        self._service = OutlookCalendarService.get_instance(config.days, config.update_interval, config.scan_body)
        self._service.updated.connect(self._on_updated)
        self.destroyed.connect(lambda *_: self._release_service())
        self._update_label()

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    def _release_service(self) -> None:
        if getattr(self, "_service_released", False):
            return
        self._service_released = True
        try:
            self._service.release()
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._release_service()
        super().closeEvent(event)

    def _on_updated(self) -> None:
        self._update_label()
        self._sync_popup()

    def _refresh(self) -> None:
        self._service.refresh_now()

    def _open_outlook(self) -> None:
        open_calendar()

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _events(self) -> tuple[CalEvent, ...]:
        """The snapshot's events inside this widget's window. The window can be shorter than
        the service's, when another bar asked for more days."""
        start = day_start(self._now().date())
        end = start + timedelta(days=self.config.days)
        return tuple(event for event in self._service.snapshot.events if event.start < end and event.end > start)

    def _message(self) -> tuple[str, str]:
        """(state class, text) for when the bar has no event to count down to."""
        snapshot = self._service.snapshot
        if snapshot.fetched_at is None:
            if snapshot.status == "error":
                return "error", _UNAVAILABLE_TEXT
            return "closed", self.config.closed_text
        return "empty", self.config.empty_text

    def _staleness(self) -> list[str]:
        """``stale`` or ``error`` when the events shown were read earlier, else nothing."""
        snapshot = self._service.snapshot
        if snapshot.fetched_at is not None and snapshot.status in ("stale", "error"):
            return [snapshot.status]
        return []

    def _is_soon(self, event: CalEvent, now: datetime) -> bool:
        minutes = self.config.soon_minutes
        return bool(minutes) and now < event.start <= now + timedelta(minutes=minutes)

    # ------------------------------------------------------------------
    # Bar label
    # ------------------------------------------------------------------

    def _label_options(self, event: CalEvent | None, now: datetime) -> tuple[dict[str, str], list[str]]:
        time_format = self.config.time_format
        options = {
            "{icon}": self.config.icons.default,
            "{countdown}": "",
            "{title}": "",
            "{time}": "",
            "{location}": "",
            "{today_count}": str(today_count(self._events(), now)),
        }
        states: list[str] = []
        if event is None:
            state, options["{title}"] = self._message()
            states.append(state)
        else:
            options["{countdown}"] = format_countdown(event, now, time_format)
            options["{title}"] = shorten(event.subject, self.config.max_title_length)
            options["{time}"] = format_time_range(event, time_format)
            options["{location}"] = event.location
            if event.ongoing(now):
                states.append("ongoing")
            elif self._is_soon(event, now):
                states.append("soon")
            if event.tentative:
                states.append("tentative")
        states.extend(self._staleness())
        return options, states

    def _update_label(self) -> None:
        now = self._now()
        event = select_event(self._events(), now)
        options, states = self._label_options(event, now)
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_content = self.config.label_alt if self._show_alt_label else self.config.label
        label_parts = [p for p in re.split(r"(<span.*?>.*?</span>)", active_content) if p]
        # With no event, a template such as "{countdown} · {title}" would render as a stray
        # separator, so the first text label carries the state's message and others go blank.
        message = options["{title}"] if event is None else None
        widget_index = 0
        for part in label_parts:
            part = part.strip()
            if not part or widget_index >= len(active_widgets):
                continue
            widget = active_widgets[widget_index]
            widget_index += 1
            is_icon = "<span" in part and "</span>" in part
            if is_icon:
                part = re.sub(r"<span.*?>|</span>", "", part)
            if message is not None and not is_icon:
                text, message = message, ""
            else:
                # One pass, so a subject containing "{time}" is not substituted again.
                filled = _PLACEHOLDER_RE.sub(lambda m: options.get(m.group(0), m.group(0)), part)
                text = " ".join(filled.split())
            # Classes first: the theme's font and max-width for this state decide how much fits.
            base = widget.property("base_class") or ""
            widget.setProperty("class", " ".join(p for p in (base, *states) if p))
            refresh_widget_style(widget)
            widget.setText(self._fit(widget, text))
            widget.setVisible(bool(text) and (widget in self._widgets) != self._show_alt_label)
        self._update_tooltip(event, now)

    @staticmethod
    def _fit(label: QLabel, text: str) -> str:
        """*text* cut to the label's width when a theme gives it a fixed slot (max-width).

        The title is also capped at max_title_length characters, but a fixed slot is better filled
        to its edge than capped short and left half empty.
        """
        limit = label.maximumWidth()
        if not text or limit >= QWIDGETSIZE_MAX:
            return text
        margins = label.contentsMargins()
        width = max(limit - margins.left() - margins.right(), 0)
        return label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)

    def _update_tooltip(self, event: CalEvent | None, now: datetime) -> None:
        if not self.config.tooltip:
            return
        time_format = self.config.time_format
        if event is None:
            lines = [html.escape(self._message()[1])]
        else:
            lines = [
                f"<strong>{html.escape(event.subject)}</strong>",
                f"{day_heading(event.start.date(), now.date())} · {format_time_range(event, time_format)}",
            ]
            if event.location:
                lines.append(html.escape(event.location))
            if event.tentative:
                lines.append("Tentative")
        if self._staleness():
            lines.append(format_status(self._service.snapshot, now, time_format))
        set_tooltip(self, "<br>".join(lines))

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    # ------------------------------------------------------------------
    # Popup
    # ------------------------------------------------------------------

    def _toggle_card(self) -> None:
        self._service.refresh_now()
        m = self.config.menu
        popup = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        popup.setProperty("class", "outlook-calendar-menu")
        popup.setMinimumWidth(m.min_width)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._fill_popup(layout)
        fit_to_width(popup)
        popup.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        popup.show()
        if popup.isVisible():
            self._popup = popup
            self._popup_layout = layout
        else:
            # PopupWidget.show() found one already open and closed it instead.
            popup.deleteLater()
            self._forget_popup()

    def _forget_popup(self) -> None:
        self._popup = None
        self._popup_layout = None

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.hide()
            except RuntimeError:
                pass
        self._forget_popup()

    def _sync_popup(self) -> None:
        if self._popup is None or self._popup_layout is None:
            return
        try:
            if not self._popup.isVisible():
                self._forget_popup()
                return
            self._fill_popup(self._popup_layout)
            fit_to_width(self._popup)
        except RuntimeError:
            self._forget_popup()

    def _open_event(self, event: CalEvent) -> None:
        if event.entry_id:
            open_event_in_background(event)
        else:
            open_calendar()
        self._close_popup()

    def _join(self, url: str) -> None:
        _open_url(url)
        self._close_popup()

    def _fill_popup(self, layout: QVBoxLayout) -> None:
        while layout.count():
            old = layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        now = self._now()
        layout.addWidget(self._build_header(now))
        days = group_by_day(self._events(), now.date(), self.config.days)
        if not days:
            layout.addWidget(self._build_placeholder())
            return
        container = QFrame()
        container.setProperty("class", "days")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        layout.addWidget(container)
        time_labels: list[QLabel] = []
        built: list[_EventRow] = []
        rows = 0
        for day in days:
            if rows >= self.config.menu.max_rows:
                break
            container_layout.addWidget(_label("day-heading", day_heading(day.day, now.date())))
            for event in (*day.all_day, *day.timed):
                if rows >= self.config.menu.max_rows:
                    break
                row, time_label = self._build_row(event, now)
                container_layout.addWidget(row)
                time_labels.append(time_label)
                built.append(row)
                rows += 1
        hidden = sum(len(day.all_day) + len(day.timed) for day in days) - rows
        if hidden > 0:
            container_layout.addWidget(_label("more", f"+{hidden} more"))
        self._align(time_labels)
        for row in built:
            self._align_baselines(row)

    @staticmethod
    def _baseline(label: QLabel) -> int:
        """Where a label's first text line sits below its top, once the theme's font applies."""
        label.ensurePolished()
        metrics = label.fontMetrics()
        return (label.sizeHint().height() - metrics.height()) // 2 + metrics.ascent()

    @classmethod
    def _align_baselines(cls, row: _EventRow) -> None:
        """The time and subject use different fonts, so equal tops are not equal baselines.

        Push the one with the shorter ascent down by the difference. This runs once the row is in
        the popup, because the theme's descendant selectors only match a widget with a parent.
        """
        shift = cls._baseline(row.subject) - cls._baseline(row.time_label)
        row.time_gap.changeSize(0, max(shift, 0))
        row.text_gap.changeSize(0, max(-shift, 0))
        row.layout().invalidate()

    @staticmethod
    def _align(labels: list[QLabel]) -> None:
        """Give every time label the widest one's width, so subjects start in one column."""
        for label in labels:
            label.ensurePolished()
        width = max((label.sizeHint().width() for label in labels), default=0)
        for label in labels:
            label.setMinimumWidth(width)

    def _build_header(self, now: datetime) -> QFrame:
        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(
            _label("header-icon", self.config.icons.default), alignment=Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(_label("title", "Calendar"), alignment=Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch()
        snapshot = self._service.snapshot
        classes = ["status", *self._staleness()]
        if snapshot.fetched_at is None:
            classes.append(self._message()[0])
        status = _label(" ".join(classes), format_status(snapshot, now, self.config.time_format))
        status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(status, alignment=Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_placeholder(self) -> QLabel:
        if self._service.snapshot.fetched_at is None:
            state, text = self._message()
        elif self.config.days == 1:
            state, text = "empty", "Nothing today"
        else:
            state, text = "empty", f"Nothing in the next {self.config.days} days"
        placeholder = _label(f"placeholder {state}", text)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        return placeholder

    def _build_row(self, event: CalEvent, now: datetime) -> tuple[QFrame, QLabel]:
        time_format = self.config.time_format
        classes = ["event-row"]
        if event.all_day:
            classes.append("all-day")
        elif event.end <= now:
            classes.append("past")
        elif event.ongoing(now):
            classes.append("ongoing")
        elif self._is_soon(event, now):
            classes.append("soon")
        if event.tentative:
            classes.append("tentative")
        row = _EventRow(event, self._open_event)
        row.time_gap, row.text_gap = QSpacerItem(0, 0), QSpacerItem(0, 0)
        row.setProperty("class", " ".join(classes))
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        time_label = _label("time", format_time_range(event, time_format))
        subject = _label("subject", event.subject, ElidedLabel)
        row.time_label, row.subject = time_label, subject
        time_column = QVBoxLayout()
        time_column.setContentsMargins(0, 0, 0, 0)
        time_column.setSpacing(0)
        time_column.addItem(row.time_gap)
        time_column.addWidget(time_label)
        time_column.addStretch()
        row_layout.addLayout(time_column)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addItem(row.text_gap)
        text.addWidget(subject)
        if event.location:
            text.addWidget(_label("location", event.location, ElidedLabel))
        text.addStretch()
        row_layout.addLayout(text, 1)

        if event.tentative:
            row_layout.addWidget(_label("tag", "Tentative"), alignment=Qt.AlignmentFlag.AlignVCenter)
        when = row_status(event, now, time_format)
        if when:
            when_label = _label("when", when)
            when_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(when_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        if event.join_url:
            join = QPushButton("Join")
            join.setProperty("class", "join")
            join.setCursor(Qt.CursorShape.PointingHandCursor)
            join.clicked.connect(lambda _checked=False, url=event.join_url: self._join(url))
            row_layout.addWidget(join, alignment=Qt.AlignmentFlag.AlignVCenter)
        return row, time_label

"""The rain bars, painted: the pill's six-hour strip, the card's twelve hours and the days' mini
strips. Heights are data, so they are drawn rather than laid out; every colour arrives from the
stylesheet as a ``-qproperty-``, and the defaults only hold until styles.css says otherwise.
"""

import math
from collections.abc import Callable, Sequence

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPaintEvent
from PyQt6.QtWidgets import QFrame, QSizePolicy, QWidget

from core.utils.widgets.ai_usage.scene import colour_property
from core.utils.widgets.local_weather.rain import Bar

LABEL_GAP = 2  # between a bar's top and its chance label
LABEL_ROOM = 2  # kept clear between neighbouring labels


def fit_labels(labels: Sequence[str], width: Callable[[str], float], room: float) -> list[str]:
    """The chance labels as drawn: if any is wider than its column (a "100%" in a 25px column),
    every label drops its "%", so the row stays even and no two labels touch."""
    if all(width(label) <= room for label in labels if label):
        return list(labels)
    return [label.removesuffix("%") for label in labels]


class RainBars(QFrame):
    """``count`` bottom-aligned bars. Packed bars sit ``gap`` apart in a fixed-size strip; spread
    bars are centred in equal columns across the width, so labels laid out in equal cells below
    line up with them. QSS padding moves the bars, as it does a label's text."""

    def __init__(
        self,
        count: int,
        bar_width: float,
        gap: float,
        radius: float,
        height: int,
        *,
        spread: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._count = count
        self._bar_width = bar_width
        self._gap = gap
        self._radius = radius
        self._height = height
        self._spread = spread
        self._bars: tuple[Bar, ...] = ()
        self._wet = QColor("#89dceb")
        self._heavy = QColor("#74c7ec")
        self._dry = QColor("#45475a")
        self._none = QColor("#6c7086")
        self._label = QColor("#bac2de")
        horizontal = QSizePolicy.Policy.Expanding if spread else QSizePolicy.Policy.Fixed
        self.setSizePolicy(horizontal, QSizePolicy.Policy.Fixed)

    wetcolor = colour_property("_wet")
    heavycolor = colour_property("_heavy")
    drycolor = colour_property("_dry")
    nonecolor = colour_property("_none")
    labelcolor = colour_property("_label")

    @property
    def bars(self) -> tuple[Bar, ...]:
        return self._bars

    def set_bars(self, bars: Sequence[Bar]) -> None:
        bars = tuple(bars)
        if bars != self._bars:
            self._bars = bars
            self.update()

    def sizeHint(self) -> QSize:
        m = self.contentsMargins()
        width = 0 if self._spread else math.ceil(self._count * self._bar_width + (self._count - 1) * self._gap)
        return QSize(width + m.left() + m.right(), self._height + m.top() + m.bottom())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _colour(self, bar: Bar) -> QColor:
        return {"wet": self._wet, "heavy": self._heavy, "dry": self._dry}.get(bar.level, self._none)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        if not self._bars:
            return
        area = self.contentsRect()
        bottom = area.top() + area.height()
        pitch = area.width() / self._count if self._spread else self._bar_width + self._gap
        metrics = QFontMetricsF(self.font())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        bars = self._bars[: self._count]
        labels = fit_labels([bar.label for bar in bars], metrics.horizontalAdvance, pitch - LABEL_ROOM)
        for i, (bar, label) in enumerate(zip(bars, labels, strict=True)):
            offset = (pitch - self._bar_width) / 2 if self._spread else 0
            x = area.left() + i * pitch + offset
            height = min(bar.height, area.height())
            radius = min(self._radius, self._bar_width / 2, height / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._colour(bar))
            painter.drawRoundedRect(QRectF(x, bottom - height, self._bar_width, height), radius, radius)
            if label:
                centre = x + self._bar_width / 2
                text = QRectF(
                    centre - pitch / 2, bottom - height - LABEL_GAP - metrics.height(), pitch, metrics.height()
                )
                painter.setPen(self._label)
                painter.drawText(text, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom), label)
        painter.end()

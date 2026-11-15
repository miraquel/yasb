"""Paints the traffic sparkline from the rectangles ``SparklineModel`` hands it.

Every colour arrives from the stylesheet as a ``-qproperty-`` on ``.traffic-sparkline``
(``downloadcolor``, ``uploadcolor``, ``baselinecolor``); the defaults only apply until styles.css
says otherwise. Plain whole-pixel fills, no antialiasing, nothing painted behind the bars.
"""

from collections.abc import Callable
from typing import Any, override

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QRect, QSize
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QFrame, QSizePolicy, QWidget

from core.utils.widgets.traffic.sparkline import SparklineModel

# pyqtProperty exists at runtime but is missing from the PyQt6 type stubs
pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")


def colour_property(attr: str) -> Any:
    # Same as ai_usage.scene.colour_property; importing it from there would drag the AI usage
    # popups' tooltip and sky modules into the traffic widget.
    def getter(self: QWidget) -> QColor:
        return getattr(self, attr)

    def setter(self: QWidget, value: QColor) -> None:
        setattr(self, attr, QColor(value))
        self.update()

    return pyqtProperty(QColor, getter, setter)


class TrafficSparkline(QFrame):
    """A fixed-size strip of bars: download above the baseline, upload below it."""

    def __init__(self, model: SparklineModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("class", "traffic-sparkline")
        self.model = model
        self._download = QColor("#89dceb")
        self._upload = QColor("#cba6f7")
        self._baseline = QColor("#45475a")
        # The model's size, plus any margin, border or padding the stylesheet adds around it.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # All lowercase: YASB's stylesheet engine lowercases every declaration name, so a camelCase
    # property could never be reached. -qproperty-downloadColor in styles.css still lands here.
    downloadcolor: QColor = colour_property("_download")
    uploadcolor: QColor = colour_property("_upload")
    baselinecolor: QColor = colour_property("_baseline")

    @override
    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        return QSize(
            self.model.width + margins.left() + margins.right(),
            self.model.height + margins.top() + margins.bottom(),
        )

    @override
    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def push(self, download: float, upload: float) -> None:
        self.model.push(download, upload)
        self.update()

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        rects = self.model.rects()
        painter = QPainter(self)
        painter.translate(self.contentsRect().topLeft())
        painter.fillRect(QRect(*rects.baseline), self._baseline)
        for rect in rects.download:
            painter.fillRect(QRect(*rect), self._download)
        for rect in rects.upload:
            painter.fillRect(QRect(*rect), self._upload)
        painter.end()

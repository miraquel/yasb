"""The fill painted behind each half of the AI pill; ``gauge.py`` decides what it shows.

The gauge is a sibling *beneath* the widget's ``.widget-container`` rather than a child inside it.
Qt paints a container's own border before its children, so a fill inside the Codex container
would cover the 1px seam between the halves; beneath it, the seam and the labels paint over the
fill and the container's background stays transparent. Every colour, opacity and radius arrives
from the stylesheet as a ``-qproperty-``; the defaults only apply until styles.css says otherwise.
"""

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from core.utils.widgets.ai_usage.gauge import Step
from core.utils.widgets.ai_usage.scene import colour_property

# Matches the ring it replaces (core.utils.progress_bar), so the pill moves the way it always has.
ANIMATION_MS = 400
# From here on the edge line would sit against the half's far edge and read as a border.
EDGE_HIDDEN_FROM = 99.0


def _int_property(attr: str) -> pyqtProperty:
    def getter(self) -> int:
        return getattr(self, attr)

    def setter(self, value: int) -> None:
        setattr(self, attr, int(value))
        self.update()

    return pyqtProperty(int, getter, setter)


def _share_property(attr: str) -> pyqtProperty:
    # The animated share; None (nothing painted) reads as 0 so an animation can start from it.
    def getter(self) -> float:
        value = getattr(self, attr)
        return 0.0 if value is None else value

    def setter(self, value: float) -> None:
        setattr(self, attr, float(value))
        self.update()

    return pyqtProperty(float, getter, setter)


class UsageGauge(QWidget):
    """A tank-style fill from the left edge, a 1px edge line where it ends, and a thin line along
    the bottom for the other window. Shares are percentages of the gauge's width."""

    def __init__(self, host: QWidget, target: QWidget, animate: bool = True):
        super().__init__(host)
        self.setProperty("class", "gauge")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._target = target
        self._animate = animate
        self._reading: tuple[float | None, Step | None, float | None, Step | None] = (None, None, None, None)
        self._fill_share: float | None = None
        self._line_share: float | None = None
        self._fill_step: Step | None = None
        self._line_step: Step | None = None

        self._low = QColor("#fab387")
        self._medium = QColor("#f9e2af")
        self._high = QColor("#f38ba8")
        self._low_alpha = 20
        self._medium_alpha = 24
        self._high_alpha = 30
        self._edge_alpha = 45
        self._line_height = 2
        self._left_radius = 8
        self._right_radius = 8

        self._fill_animation = self._make_animation(b"fillshare")
        self._line_animation = self._make_animation(b"lineshare")

        self.setGeometry(target.geometry())
        target.installEventFilter(self)
        self.lower()

    lowcolor = colour_property("_low")
    mediumcolor = colour_property("_medium")
    highcolor = colour_property("_high")
    lowalpha = _int_property("_low_alpha")
    mediumalpha = _int_property("_medium_alpha")
    highalpha = _int_property("_high_alpha")
    edgealpha = _int_property("_edge_alpha")
    lineheight = _int_property("_line_height")
    leftradius = _int_property("_left_radius")
    rightradius = _int_property("_right_radius")
    fillshare = _share_property("_fill_share")
    lineshare = _share_property("_line_share")

    def _make_animation(self, prop: bytes) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(ANIMATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        return animation

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._target and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self.setGeometry(self._target.geometry())
        return False

    def set_reading(
        self, fill: float | None, fill_step: Step | None, line: float | None, line_step: Step | None
    ) -> None:
        self._reading = (fill, fill_step, line, line_step)
        self._fill_step = fill_step
        self._line_step = line_step
        self._move_to(self._fill_animation, "_fill_share", fill)
        self._move_to(self._line_animation, "_line_share", line)
        self.update()

    def reading(self) -> tuple[float | None, Step | None, float | None, Step | None]:
        return self._reading

    def _move_to(self, animation: QPropertyAnimation, attr: str, target: float | None) -> None:
        """Slide to a new share; a missing reading snaps away rather than draining to nothing."""
        animation.stop()
        start = getattr(self, attr)
        if target is None or not self._animate or start == target:
            setattr(self, attr, None if target is None else float(target))
            return
        animation.setStartValue(0.0 if start is None else float(start))
        animation.setEndValue(float(target))
        animation.start()

    def _hue(self, step: Step) -> QColor:
        return {"low": self._low, "medium": self._medium, "high": self._high}[step]

    def _tint(self, step: Step, alpha_percent: int) -> QColor:
        colour = QColor(self._hue(step))
        colour.setAlpha(max(0, min(255, round(255 * alpha_percent / 100))))
        return colour

    def _outline(self) -> QPainterPath:
        """The half's shape: rounded only on the corners that are the pill's outer corners."""
        w, h = float(self.width()), float(self.height())
        left = min(float(self._left_radius), h / 2, w / 2)
        right = min(float(self._right_radius), h / 2, w / 2)
        path = QPainterPath()
        path.moveTo(left, 0)
        path.lineTo(w - right, 0)
        if right:
            path.arcTo(QRectF(w - 2 * right, 0, 2 * right, 2 * right), 90, -90)
        path.lineTo(w, h - right)
        if right:
            path.arcTo(QRectF(w - 2 * right, h - 2 * right, 2 * right, 2 * right), 0, -90)
        path.lineTo(left, h)
        if left:
            path.arcTo(QRectF(0, h - 2 * left, 2 * left, 2 * left), 270, -90)
        path.lineTo(0, left)
        if left:
            path.arcTo(QRectF(0, 0, 2 * left, 2 * left), 180, -90)
        path.closeSubpath()
        return path

    def _fill_rect(self, painter: QPainter, outline: QPainterPath, rect: QRectF, colour: QColor) -> None:
        # Intersect rather than clip: a clip path is not antialiased, the rounded corners would be.
        piece = QPainterPath()
        piece.addRect(rect)
        painter.fillPath(outline.intersected(piece), colour)

    def paintEvent(self, event) -> None:
        fill = self._fill_share if self._fill_step is not None else None
        line = self._line_share if self._line_step is not None else None
        if fill is None and line is None:
            return
        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = self._outline()
        if fill is not None:
            width = round(w * fill / 100)
            if width > 0:
                alpha = {"low": self._low_alpha, "medium": self._medium_alpha, "high": self._high_alpha}
                self._fill_rect(
                    painter, outline, QRectF(0, 0, width, h), self._tint(self._fill_step, alpha[self._fill_step])
                )
                if fill < EDGE_HIDDEN_FROM:
                    self._fill_rect(
                        painter, outline, QRectF(width - 1, 0, 1, h), self._tint(self._fill_step, self._edge_alpha)
                    )
        if line is not None and line > 0:
            # Measured from where a rounded left end's curve meets the bottom: from x=0 a small
            # share would sit wholly inside the curve and never show. 100% still reaches the end.
            start = min(float(self._left_radius), h / 2, w / 2)
            width = round(start + (w - start) * line / 100)
            height = min(self._line_height, h)
            if height > 0:
                self._fill_rect(
                    painter, outline, QRectF(0, h - height, width, height), QColor(self._hue(self._line_step))
                )
        painter.end()

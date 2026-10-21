"""Painters shared by the AI usage popups: the hearts in the header and the sky behind the
hero reading, plus the helpers the pets' painters use.

Each draws rectangles a Qt-free model hands it, scaled up from logical units, so the behaviour
lives (and is tested) in the models. Every colour arrives from the stylesheet as a
``-qproperty-``; the defaults only apply until styles.css says otherwise.
"""

from collections.abc import Callable, Iterable
from typing import Any

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QHideEvent,
    QImage,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QRadialGradient,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QFrame, QWidget

from core.utils.tooltip import set_tooltip
from core.utils.widgets.ai_usage import hearts
from core.utils.widgets.ai_usage.sky import Colour, Sky, SkyFrame

# pyqtProperty exists at runtime but is missing from the PyQt6 type stubs
pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")

# The pets' and the sky's animation tick.
FRAME_MS = 90
HEART_GAP = 2.5


def colour_property(attr: str) -> Any:
    def getter(self: QWidget) -> QColor:
        return getattr(self, attr)

    def setter(self: QWidget, value: QColor) -> None:
        setattr(self, attr, QColor(value))
        self.update()

    return pyqtProperty(QColor, getter, setter)


def percent_property(attr: str) -> Any:
    # Whole percentages rather than floats: an int -qproperty- is what QSS reliably converts.
    def getter(self: SkyScene) -> int:
        return getattr(self, attr)

    def setter(self: SkyScene, value: int) -> None:
        setattr(self, attr, max(0, min(100, int(value))))
        self._render()  # pyright: ignore[reportPrivateUsage]
        self.update()

    return pyqtProperty(int, getter, setter)


def qcolor(colour: Colour, alpha_scale: float = 1.0) -> QColor:
    a, r, g, b = colour
    return QColor(r, g, b, max(0, min(255, round(a * alpha_scale))))


def fill_rects(painter: QPainter, rects: Iterable[hearts.Rect], dx: float, dy: float, colour: QColor) -> None:
    for x, y, w, h in rects:
        painter.fillRect(QRectF(dx + x, dy + y, w, h), colour)


class HeartsView(QFrame):
    """Three pixel hearts with halves: how much of a limit window is left, tamagotchi-style."""

    def __init__(self, scale: float = 1.35, parent: QFrame | None = None):
        super().__init__(parent)
        self.setProperty("class", "hearts")
        self._scale = scale
        self._halves: int | None = None
        self._beat = 1.0
        self._tip = ""
        self._on = QColor("#F87171")
        self._off = QColor("#3F3F46")
        # Room around the hearts for the beat to swell into without clipping.
        self._pad = hearts.HEART_H * 0.15
        width = 3 * hearts.HEART_W + 2 * HEART_GAP + 2 * self._pad
        height = hearts.HEART_H + 2 * self._pad
        self.setFixedSize(round(width * scale), round(height * scale))
        self.setVisible(False)

    heartcolor = colour_property("_on")
    emptycolor = colour_property("_off")

    def set_state(
        self, halves: int | None, beat: float = 1.0, percent: float | None = None, window: str = "5-hour"
    ) -> None:
        if percent is not None and halves is not None:
            health = hearts.HEALTH_NAMES.get(halves, "")
            tip = f"{health} · {max(0, round(100 - percent))}% of the {window} limit left"
            # Called every animation tick; only touch the tooltip when its text changes.
            if tip != self._tip:
                self._tip = tip
                set_tooltip(self, tip)
        self.setVisible(halves is not None)
        if halves == self._halves and beat == self._beat:
            return
        self._halves = halves
        self._beat = beat
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        if self._halves is None:
            return
        painter = QPainter(self)
        painter.scale(self._scale, self._scale)
        full = hearts.heart_rects()
        half = hearts.heart_rects(4)
        for i in range(3):
            x = self._pad + i * (hearts.HEART_W + HEART_GAP)
            y = self._pad
            painter.save()
            # Beat around each heart's own centre.
            painter.translate(x + hearts.HEART_W / 2, y + hearts.HEART_H / 2)
            painter.scale(self._beat, self._beat)
            painter.translate(-hearts.HEART_W / 2, -hearts.HEART_H / 2)
            fill_rects(painter, full, 0, 0, self._off)
            remaining = self._halves - 2 * i
            if remaining >= 2:
                fill_rects(painter, full, 0, 0, self._on)
            elif remaining == 1:
                fill_rects(painter, half, 0, 0, self._on)
            painter.restore()
        painter.end()


class SkyScene(QFrame):
    """The hero row's backdrop: the reading and Clawd are laid out inside it, on top of the sky.

    Each tick renders the sky once into an image, and paintEvent only copies it out. Clawd
    repaints faster than the sky moves, and every one of his repaints also repaints the strip
    of sky under him.
    """

    def __init__(self, scale: float = 1.35, parent: QFrame | None = None):
        super().__init__(parent)
        self.setProperty("class", "hero-top sky")
        self._scale = scale
        self.model = Sky()
        self._frame: SkyFrame | None = None
        self._image: QImage | None = None
        # How strong the gradient is, how opaque the sun, moon, clouds and weather are (0.7
        # in the original), and how much of each side fades out into the panel.
        self._strength = 100
        self._fx_opacity = 70
        self._edge_fade = 10

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    strength = percent_property("_strength")
    fxopacity = percent_property("_fx_opacity")
    edgefade = percent_property("_edge_fade")

    def set_tip(self, text: str) -> None:
        set_tooltip(self, text)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._tick()
        self._timer.start()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        self._timer.stop()
        super().hideEvent(a0)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        if self.isVisible():
            self._tick()

    def _tick(self) -> None:
        self._frame = self.model.step(self.width() / self._scale, self.height() / self._scale)
        self._render()
        self.update()

    def _render(self) -> None:
        frame = self._frame
        w, h = self.width(), self.height()
        if frame is None or w <= 0 or h <= 0:
            self._image = None
            return
        dpr = self.devicePixelRatioF()
        image = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)

        strength = self._strength / 100
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0, qcolor(frame.top, strength))
        sky.setColorAt(1, qcolor(frame.bottom, strength))
        painter.fillRect(QRectF(0, 0, w, h), sky)

        painter.scale(self._scale, self._scale)
        painter.setPen(Qt.PenStyle.NoPen)
        fx = self._fx_opacity / 100
        for sprite in frame.sprites:
            painter.setOpacity(fx * sprite.opacity)
            if sprite.kind == "glow":
                x, y, size, _ = sprite.rects[0]
                glow = QRadialGradient(QPointF(x + size / 2, y + size / 2), size / 2)
                glow.setColorAt(0, qcolor(sprite.colour))
                glow.setColorAt(1, qcolor(sprite.colour, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QRectF(x, y, size, size))
            elif sprite.kind == "fog":
                x, y, fw, fh = sprite.rects[0]
                band = QLinearGradient(x, 0, x + fw, 0)
                band.setColorAt(0, qcolor(sprite.colour, 0))
                band.setColorAt(0.5, qcolor(sprite.colour))
                band.setColorAt(1, qcolor(sprite.colour, 0))
                painter.fillRect(QRectF(x, y, fw, fh), band)
            else:
                colour = qcolor(sprite.colour)
                for rect in sprite.rects:
                    painter.fillRect(QRectF(*rect), colour)
        painter.setOpacity(1.0)
        painter.resetTransform()

        fade = self._edge_fade / 100
        if fade > 0:
            # Fade both sides into the panel, so the sky has no hard edge.
            mask = QLinearGradient(0, 0, w, 0)
            mask.setColorAt(0, QColor(0, 0, 0, 0))
            mask.setColorAt(min(fade, 0.5), QColor(0, 0, 0, 255))
            mask.setColorAt(max(1 - fade, 0.5), QColor(0, 0, 0, 255))
            mask.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.fillRect(QRectF(0, 0, w, h), mask)
        painter.end()
        self._image = image

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        if self._image is None:
            return
        painter = QPainter(self)
        painter.drawImage(QPointF(0, 0), self._image)
        painter.end()

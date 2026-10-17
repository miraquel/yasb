"""Painters for the Claude popup's Clawd and his hearts.

Both draw rectangles the Qt-free ``clawd`` model hands them, scaled up from its logical
units, so all behaviour lives (and is tested) there. Every colour arrives from the stylesheet
as a ``-qproperty-``, the same way the prayer day ribbon takes its palette; the defaults below
are the original widget's own, and only apply until styles.css says otherwise.
"""

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QFrame, QSizePolicy

from core.utils.tooltip import set_tooltip
from core.utils.widgets.claude_usage import clawd
from core.utils.widgets.claude_usage.clawd import Clawd, Frame

# Logical height of the play area: room above his head for the "?" bubble, the floating
# heart and the confetti, which all start a little over 20 units up.
SCENE_HEIGHT = 50.0
GROUND_PAD = 2.0
HEART_GAP = 2.5


def _colour_property(attr: str) -> pyqtProperty:
    def getter(self) -> QColor:
        return getattr(self, attr)

    def setter(self, value: QColor) -> None:
        setattr(self, attr, QColor(value))
        self.update()

    return pyqtProperty(QColor, getter, setter)


def _fill(painter: QPainter, rects, dx: float, dy: float, colour: QColor) -> None:
    for x, y, w, h in rects:
        painter.fillRect(QRectF(dx + x, dy + y, w, h), colour)


class ClawdScene(QFrame):
    """The strip Clawd lives in. Animates only while visible, so a closed popup costs nothing."""

    stepped = pyqtSignal(object)

    def __init__(self, scale: float = 1.35, crit_percent: float = 85, parent: QFrame | None = None):
        super().__init__(parent)
        self.setProperty("class", "clawd")
        self._scale = scale
        self.model = Clawd(crit_percent=crit_percent)
        self._frame: Frame | None = None
        self._mouse_x: float | None = None
        self._entered = False

        self._body = QColor("#D77757")
        self._eyes = QColor("#141416")
        self._fx = QColor("#6B7280")
        self._sand = QColor("#B8955E")
        self._sweat = QColor("#7DD3FC")
        self._dust = QColor("#8B8B94")
        self._zzz = QColor("#8B8B94")
        self._love = QColor("#F87171")
        self._soul = QColor("#F4F4F5")
        self._ask = QColor("#FBBF24")
        self._cheer = QColor("#4ADE80")
        self._note = QColor("#93C5FD")
        self._confetti = [QColor(c) for c in clawd.CONFETTI_COLORS]

        self._timer = QTimer(self)
        self._timer.setInterval(clawd.FRAME_MS)
        self._timer.timeout.connect(self._tick)

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(round(SCENE_HEIGHT * scale))
        self.setMinimumWidth(round((clawd.WIDTH + 40) * scale))

    bodycolor = _colour_property("_body")
    eyecolor = _colour_property("_eyes")
    fxcolor = _colour_property("_fx")
    sandcolor = _colour_property("_sand")
    sweatcolor = _colour_property("_sweat")
    dustcolor = _colour_property("_dust")
    zzzcolor = _colour_property("_zzz")
    lovecolor = _colour_property("_love")
    soulcolor = _colour_property("_soul")
    askcolor = _colour_property("_ask")
    cheercolor = _colour_property("_cheer")
    notecolor = _colour_property("_note")

    def sizeHint(self) -> QSize:
        return QSize(round(140 * self._scale), round(SCENE_HEIGHT * self._scale))

    # ------------------------------------------------------------------ driving ----
    def set_inputs(self, percent, busy: int, waiting: int, total: int, reset_at: float | None) -> None:
        self.model.set_inputs(percent, busy, waiting, total, reset_at)
        set_tooltip(self, f"Clawd is {self.model.mood_text()}")

    def showEvent(self, event):
        super().showEvent(event)
        if not self._entered:
            # An entrance the first time he is seen, like Claude Code's welcome screen.
            self._entered = True
            self.model.start_entrance()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        frame = self.model.step(self.width() / self._scale, self._mouse_x)
        self._frame = frame
        if self._timer.interval() != frame.interval_ms:
            self._timer.setInterval(frame.interval_ms)
        self.stepped.emit(frame)
        self.update()

    def _body_rect(self) -> QRectF | None:
        """Where his body is, in widget pixels, for the click target and the cursor."""
        if self._frame is None:
            return None
        s = self._scale
        top = self._ground() - self._frame.lift - (clawd.HEIGHT - clawd.SINK)
        return QRectF(self._frame.x * s, top * s, clawd.WIDTH * s, clawd.HEIGHT * s).adjusted(-6, -6, 6, 6)

    def mouseMoveEvent(self, event):
        self._mouse_x = event.position().x() / self._scale
        body = self._body_rect()
        over = body is not None and body.contains(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._mouse_x = None
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        body = self._body_rect()
        if event.button() == Qt.MouseButton.LeftButton and body is not None and body.contains(event.position()):
            self.model.click()
            # Taken here, so a pinned popup does not start a window drag from a pet.
            event.accept()
            return
        super().mousePressEvent(event)

    # ----------------------------------------------------------------- painting ----
    def _ground(self) -> float:
        return self.height() / self._scale - GROUND_PAD

    def paintEvent(self, event):
        super().paintEvent(event)
        frame = self._frame
        if frame is None:
            return
        painter = QPainter(self)
        painter.scale(self._scale, self._scale)
        ground = self._ground()
        left = frame.x
        top = ground - frame.lift - (clawd.HEIGHT - clawd.SINK)
        geo = frame.geometry

        _fill(painter, geo.body, left, top, self._body)
        _fill(painter, geo.eyes, left, top, self._eyes)
        _fill(painter, geo.fx, left, top, self._fx)
        _fill(painter, geo.sand, left, top, self._sand)

        if frame.sweat is not None:
            sx, sy, opacity = frame.sweat
            painter.setOpacity(opacity)
            painter.fillRect(QRectF(left + sx, top + sy, 3, 4.5), self._sweat)
            painter.setOpacity(1.0)

        if frame.zzz is not None:
            zx, zb, size, opacity = frame.zzz
            font = QFont("Segoe UI")
            font.setPointSizeF(size * 0.75)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setOpacity(opacity)
            painter.setPen(self._zzz)
            painter.drawText(
                QRectF(zx, ground - zb - size * 1.4, size * 1.2, size * 1.4), Qt.AlignmentFlag.AlignCenter, "z"
            )
            painter.setOpacity(1.0)

        if frame.bubble:
            colour = {"?": self._ask, "!": self._cheer}.get(frame.bubble, self._note)
            font = QFont("Segoe UI")
            font.setPointSizeF(11 * 0.75)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(colour)
            bx = left + clawd.WIDTH / 2 - 6
            painter.drawText(
                QRectF(bx, ground - frame.bubble_bottom - 15, 12, 15), Qt.AlignmentFlag.AlignCenter, frame.bubble
            )

        if frame.love is not None:
            lx, lb, opacity = frame.love
            painter.setOpacity(opacity)
            _fill(painter, clawd.heart_rects(), lx, ground - lb - clawd.HEART_H, self._love)
            painter.setOpacity(1.0)

        if frame.soul is not None:
            rects, mx, mb, opacity = frame.soul
            painter.setOpacity(opacity)
            _fill(painter, rects, mx, ground - mb, self._soul)
            painter.setOpacity(1.0)

        for flake_x, flake_b, width, colour_index in frame.confetti:
            painter.fillRect(QRectF(flake_x, ground - flake_b - 2.5, width, 2.5), self._confetti[colour_index])

        for dust_x, dust_b, opacity in frame.dust:
            painter.setOpacity(opacity)
            painter.fillRect(QRectF(dust_x, ground - dust_b - 2, 2, 2), self._dust)
        painter.setOpacity(1.0)
        painter.end()


class HeartsView(QFrame):
    """Three pixel hearts with halves: how much of the 5-hour window is left, tamagotchi-style."""

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
        self._pad = clawd.HEART_H * 0.15
        width = 3 * clawd.HEART_W + 2 * HEART_GAP + 2 * self._pad
        height = clawd.HEART_H + 2 * self._pad
        self.setFixedSize(round(width * scale), round(height * scale))
        self.setVisible(False)

    heartcolor = _colour_property("_on")
    emptycolor = _colour_property("_off")

    def set_state(self, halves: int | None, beat: float = 1.0, percent: float | None = None) -> None:
        if percent is not None and halves is not None:
            health = clawd.HEALTH_NAMES.get(halves, "")
            tip = f"{health} · {max(0, round(100 - percent))}% of the 5-hour limit left"
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

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._halves is None:
            return
        painter = QPainter(self)
        painter.scale(self._scale, self._scale)
        full = clawd.heart_rects()
        half = clawd.heart_rects(4)
        for i in range(3):
            x = self._pad + i * (clawd.HEART_W + HEART_GAP)
            y = self._pad
            painter.save()
            # Beat around each heart's own centre.
            painter.translate(x + clawd.HEART_W / 2, y + clawd.HEART_H / 2)
            painter.scale(self._beat, self._beat)
            painter.translate(-clawd.HEART_W / 2, -clawd.HEART_H / 2)
            _fill(painter, full, 0, 0, self._off)
            remaining = self._halves - 2 * i
            if remaining >= 2:
                _fill(painter, full, 0, 0, self._on)
            elif remaining == 1:
                _fill(painter, half, 0, 0, self._on)
            painter.restore()
        painter.end()

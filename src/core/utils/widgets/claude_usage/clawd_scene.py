"""The painter for the Claude popup's Clawd.

It draws the rectangles the Qt-free ``clawd`` model hands it, scaled up from its logical
units, so all behaviour lives (and is tested) there. Every colour arrives from the
stylesheet as a ``-qproperty-``, the same way the prayer day ribbon takes its palette; the
defaults below are the original widget's own, and only apply until styles.css says otherwise.
"""

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QFrame, QSizePolicy

from core.utils.tooltip import set_tooltip
from core.utils.widgets.ai_usage import hearts
from core.utils.widgets.ai_usage.scene import colour_property, fill_rects
from core.utils.widgets.claude_usage import clawd
from core.utils.widgets.claude_usage.clawd import Clawd, Frame

# Logical height of the play area: room above his head for the "?" bubble, the floating
# heart and the confetti, which all start a little over 20 units up.
SCENE_HEIGHT = 50.0
GROUND_PAD = 2.0


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
        self._tip_extra = ""

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

    bodycolor = colour_property("_body")
    eyecolor = colour_property("_eyes")
    fxcolor = colour_property("_fx")
    sandcolor = colour_property("_sand")
    sweatcolor = colour_property("_sweat")
    dustcolor = colour_property("_dust")
    zzzcolor = colour_property("_zzz")
    lovecolor = colour_property("_love")
    soulcolor = colour_property("_soul")
    askcolor = colour_property("_ask")
    cheercolor = colour_property("_cheer")
    notecolor = colour_property("_note")

    def sizeHint(self) -> QSize:
        return QSize(round(140 * self._scale), round(SCENE_HEIGHT * self._scale))

    # ------------------------------------------------------------------ driving ----
    def set_inputs(self, percent, busy: int, waiting: int, total: int, reset_at: float | None) -> None:
        self.model.set_inputs(percent, busy, waiting, total, reset_at)
        self._sync_tip()

    def set_tip_extra(self, text: str) -> None:
        """Lines under Clawd's own: the sky's weather, since he covers most of the sky."""
        if text != self._tip_extra:
            self._tip_extra = text
            self._sync_tip()

    def _sync_tip(self) -> None:
        tip = f"Clawd is {self.model.mood_text()}"
        if self._tip_extra:
            tip += f"\n{self._tip_extra}"
        set_tooltip(self, tip)

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

        fill_rects(painter, geo.body, left, top, self._body)
        fill_rects(painter, geo.eyes, left, top, self._eyes)
        fill_rects(painter, geo.fx, left, top, self._fx)
        fill_rects(painter, geo.sand, left, top, self._sand)

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
            fill_rects(painter, hearts.heart_rects(), lx, ground - lb - hearts.HEART_H, self._love)
            painter.setOpacity(1.0)

        if frame.soul is not None:
            rects, mx, mb, opacity = frame.soul
            painter.setOpacity(opacity)
            fill_rects(painter, rects, mx, ground - mb, self._soul)
            painter.setOpacity(1.0)

        for flake_x, flake_b, width, colour_index in frame.confetti:
            painter.fillRect(QRectF(flake_x, ground - flake_b - 2.5, width, 2.5), self._confetti[colour_index])

        for dust_x, dust_b, opacity in frame.dust:
            painter.setOpacity(opacity)
            painter.fillRect(QRectF(dust_x, ground - dust_b - 2, 2, 2), self._dust)
        painter.setOpacity(1.0)
        painter.end()

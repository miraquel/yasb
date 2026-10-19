"""Painters for the Claude popup's Clawd, his hearts and the sky behind him.

Each draws rectangles the Qt-free ``clawd`` and ``sky`` models hand it, scaled up from their
logical units, so all behaviour lives (and is tested) there. Every colour arrives from the
stylesheet as a ``-qproperty-``, the same way the prayer day ribbon takes its palette; the
defaults below are the original widget's own, and only apply until styles.css says otherwise.
"""

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QFrame, QSizePolicy

from core.utils.tooltip import set_tooltip
from core.utils.widgets.claude_usage import clawd
from core.utils.widgets.claude_usage.clawd import Clawd, Frame
from core.utils.widgets.claude_usage.sky import Colour, Sky, SkyFrame

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


def _percent_property(attr: str) -> pyqtProperty:
    # Whole percentages rather than floats: an int -qproperty- is what QSS reliably converts.
    def getter(self) -> int:
        return getattr(self, attr)

    def setter(self, value: int) -> None:
        setattr(self, attr, max(0, min(100, int(value))))
        self._render()
        self.update()

    return pyqtProperty(int, getter, setter)


def _qcolor(colour: Colour, alpha_scale: float = 1.0) -> QColor:
    a, r, g, b = colour
    return QColor(r, g, b, max(0, min(255, round(a * alpha_scale))))


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
        self._timer.setInterval(clawd.FRAME_MS)
        self._timer.timeout.connect(self._tick)

    strength = _percent_property("_strength")
    fxopacity = _percent_property("_fx_opacity")
    edgefade = _percent_property("_edge_fade")

    def set_tip(self, text: str) -> None:
        set_tooltip(self, text)

    def showEvent(self, event):
        super().showEvent(event)
        self._tick()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
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
        sky.setColorAt(0, _qcolor(frame.top, strength))
        sky.setColorAt(1, _qcolor(frame.bottom, strength))
        painter.fillRect(QRectF(0, 0, w, h), sky)

        painter.scale(self._scale, self._scale)
        painter.setPen(Qt.PenStyle.NoPen)
        fx = self._fx_opacity / 100
        for sprite in frame.sprites:
            painter.setOpacity(fx * sprite.opacity)
            if sprite.kind == "glow":
                x, y, size, _ = sprite.rects[0]
                glow = QRadialGradient(QPointF(x + size / 2, y + size / 2), size / 2)
                glow.setColorAt(0, _qcolor(sprite.colour))
                glow.setColorAt(1, _qcolor(sprite.colour, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QRectF(x, y, size, size))
            elif sprite.kind == "fog":
                x, y, fw, fh = sprite.rects[0]
                band = QLinearGradient(x, 0, x + fw, 0)
                band.setColorAt(0, _qcolor(sprite.colour, 0))
                band.setColorAt(0.5, _qcolor(sprite.colour))
                band.setColorAt(1, _qcolor(sprite.colour, 0))
                painter.fillRect(QRectF(x, y, fw, fh), band)
            else:
                colour = _qcolor(sprite.colour)
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

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._image is None:
            return
        painter = QPainter(self)
        painter.drawImage(QPointF(0, 0), self._image)
        painter.end()

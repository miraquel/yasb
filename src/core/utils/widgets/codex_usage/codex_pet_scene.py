"""The painter for the Codex popup's pet.

It draws the rectangles ``codex_pet_art`` hands it for each frame ``codex_pet`` steps, scaled up
from logical units, so all behaviour lives (and is tested) in the models. Colours arrive from the
stylesheet as ``-qproperty-``s on ``.codex-usage-menu .codex-pet``; the defaults are the pet's own
blue, navy and cyan, and only apply until styles.css says otherwise.
"""

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QFrame, QSizePolicy

from core.utils.tooltip import set_tooltip
from core.utils.widgets.ai_usage.scene import colour_property, fill_rects
from core.utils.widgets.codex_usage.codex_pet import FRAME_MS, CodexPet, PetFrame
from core.utils.widgets.codex_usage.codex_pet_art import HEIGHT, WIDTH, pose_rects

# Logical height of the strip: the pet stands about twice Clawd's height, with Clawd's headroom
# over it for the "?" and the jump.
PET_SCENE_HEIGHT = 72.0
GROUND_PAD = 2.0


class CodexPetScene(QFrame):
    """The strip the pet lives in. Animates only while visible, so a closed popup costs nothing."""

    def __init__(self, scale: float = 1.35, parent: QFrame | None = None):
        super().__init__(parent)
        self.setProperty("class", "codex-pet")
        self._scale = scale
        self.model = CodexPet()
        self._frame: PetFrame | None = None
        self._mouse_x: float | None = None
        self._tip_extra = ""

        self._body = QColor("#5478E6")
        self._screen = QColor("#181C46")
        self._face = QColor("#8CF0F5")
        self._ask = QColor("#FBBF24")

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(round(PET_SCENE_HEIGHT * scale))
        self.setMinimumWidth(round((WIDTH + 40) * scale))

    bodycolor = colour_property("_body")
    screencolor = colour_property("_screen")
    facecolor = colour_property("_face")
    askcolor = colour_property("_ask")

    def sizeHint(self) -> QSize:
        return QSize(round(140 * self._scale), round(PET_SCENE_HEIGHT * self._scale))

    # ------------------------------------------------------------------ driving ----
    def set_inputs(self, percent: float | None, working: int, waiting: int, total: int, events: list[str]) -> None:
        self.model.set_inputs(percent, working, waiting, total, events)
        self._sync_tip()

    def set_tip_extra(self, text: str) -> None:
        """Lines under the pet's own: the sky's weather, since the pet covers part of the sky."""
        if text != self._tip_extra:
            self._tip_extra = text
            self._sync_tip()

    def _sync_tip(self) -> None:
        tip = f"Codex pet is {self.model.mood_text()}"
        if self._tip_extra:
            tip += f"\n{self._tip_extra}"
        set_tooltip(self, tip)

    def showEvent(self, event):
        super().showEvent(event)
        self._tick()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        frame = self.model.step(self.width() / self._scale, self._mouse_x)
        self._frame = frame
        if self._timer.interval() != frame.interval_ms:
            self._timer.setInterval(frame.interval_ms)
        self.update()

    def _ground(self) -> float:
        return self.height() / self._scale - GROUND_PAD

    def _body_rect(self) -> QRectF | None:
        """Where the pet is, in widget pixels, for the click target and the cursor."""
        if self._frame is None:
            return None
        s = self._scale
        top = self._ground() - self._frame.lift - HEIGHT
        return QRectF(self._frame.x * s, top * s, WIDTH * s, HEIGHT * s).adjusted(-6, -6, 6, 6)

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
    def paintEvent(self, event):
        super().paintEvent(event)
        frame = self._frame
        if frame is None:
            return
        painter = QPainter(self)
        painter.scale(self._scale, self._scale)
        ground = self._ground()
        left = frame.x
        top = ground - frame.lift - HEIGHT
        rects = pose_rects(frame.pose, frame.look, frame.cursor)

        fill_rects(painter, rects.body, left, top, self._body)
        fill_rects(painter, rects.screen, left, top, self._screen)
        painter.setOpacity(frame.face_opacity)
        fill_rects(painter, rects.face, left, top, self._face)
        painter.setOpacity(1.0)

        if frame.bubble:
            font = QFont("Segoe UI")
            font.setPointSizeF(11 * 0.75)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(self._ask)
            bx = left + WIDTH / 2 - 6
            painter.drawText(
                QRectF(bx, ground - frame.bubble_bottom - 15, 12, 15), Qt.AlignmentFlag.AlignCenter, frame.bubble
            )
        painter.end()

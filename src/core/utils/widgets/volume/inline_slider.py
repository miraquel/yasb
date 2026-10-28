"""The volume slider that slides out of the bar beside the speaker icon."""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStyle,
    QStyleOptionSlider,
)

from core.validation.widgets.yasb.volume import VolumeInlineSliderConfig


class _BarSlider(QSlider):
    """A horizontal 0-100 slider that jumps to a click and leaves the wheel to the widget."""

    def __init__(self, step: int):
        super().__init__(Qt.Orientation.Horizontal)
        self.setProperty("class", "inline-slider")
        self.setRange(0, 100)
        self.setSingleStep(step)
        self.setPageStep(step)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Only the windows11 style jumps to a left click; windowsvista (Windows 10) and Fusion
        # step toward it a page at a time. Move the handle under the pointer first, then the
        # press lands on it and can drag on from there.
        if event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            style = self.style()
            handle = style.subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
            )
            if not handle.contains(event.position().toPoint()):
                groove = style.subControlRect(
                    QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
                )
                span = groove.width() - handle.width()
                offset = round(event.position().x()) - groove.x() - handle.width() // 2
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), offset, span))
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Pass the wheel on, so it steps the volume by scroll_step exactly as it does over the icon
        event.ignore()


class InlineVolumeSlider(QFrame):
    """A slider plus an optional value label, revealed by animating the frame's width.

    It only reports what the user does (`level_changed`, `released`); the volume widget sets the
    volume and pushes outside changes back in through `set_level`, which emits nothing.
    """

    level_changed = pyqtSignal(int)
    released = pyqtSignal()

    def __init__(self, config: VolumeInlineSliderConfig, step: int):
        super().__init__()
        self.setProperty("class", "inline-slider-container")
        self._expanded = False
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.slider = _BarSlider(max(1, step))
        self.slider.setFixedWidth(config.width)
        layout.addWidget(self.slider)

        self.value_label: QLabel | None = None
        if config.show_value:
            self.value_label = QLabel("0")
            self.value_label.setProperty("class", "inline-value")
            # Left, so the gap to the slider stays the stylesheet's; the room kept for a third
            # digit goes at the end of the pill instead
            self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(self.value_label)

        self._animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._animation.setDuration(config.animation_duration)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)

        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(config.auto_close)
        self._close_timer.timeout.connect(self._on_close_timer)

        self.slider.valueChanged.connect(self._on_value_changed)
        self.slider.sliderPressed.connect(self.postpone_close)
        self.slider.sliderReleased.connect(self._on_released)

        self.setMaximumWidth(0)
        self.hide()

    @property
    def is_expanded(self) -> bool:
        """True from expand() until collapse(), animation or not."""
        return self._expanded

    def target_width(self) -> int:
        """The width the frame opens to: the slider, the value label and their stylesheet gaps."""
        self.ensurePolished()
        self._reserve_value_width()
        return self.sizeHint().width()

    def expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self._slide(self._current_width(), self.target_width())
        self.postpone_close()

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self._close_timer.stop()
        self._slide(self._current_width(), 0)

    def set_level(self, level: int) -> None:
        """Show a level that changed elsewhere, without reporting it back as a user change."""
        if self.slider.isSliderDown():
            # Late notifications for earlier drag positions would pull the handle back
            return
        self.slider.blockSignals(True)
        self.slider.setValue(level)
        self.slider.blockSignals(False)
        self._show_value(self.slider.value())

    def postpone_close(self) -> None:
        """Restart the auto-close countdown; it stays stopped while the pointer is over the slider."""
        if self._expanded and self._close_timer.interval() > 0 and not self._hovered:
            self._close_timer.start()

    def _slide(self, start: int, end: int) -> None:
        self._animation.stop()
        if self._animation.duration() <= 0:
            self.setMaximumWidth(end)
            self._on_animation_finished()
            return
        self.setMaximumWidth(start)
        self.show()
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.start()

    def _current_width(self) -> int:
        # Closed it is capped at 0, mid-slide at the animated width, open it is uncapped
        return min(self.maximumWidth(), self.target_width())

    def _on_animation_finished(self) -> None:
        if self._expanded:
            # Let the layout size it from here on, so a stylesheet change can't leave it clipped
            self.setMaximumWidth(QWIDGETSIZE_MAX)
            self.show()
        else:
            self.hide()
            self._hovered = False

    def _reserve_value_width(self) -> None:
        """Size the value label for "100", so the bar doesn't shift as the level gains a digit."""
        if self.value_label is None:
            return
        self.value_label.ensurePolished()
        text = self.value_label.text()
        self.value_label.setMinimumWidth(0)
        self.value_label.setText("100")
        self.value_label.setMinimumWidth(self.value_label.sizeHint().width())
        self.value_label.setText(text)

    def _show_value(self, level: int) -> None:
        if self.value_label is not None:
            self.value_label.setText(str(level))

    def _on_value_changed(self, level: int) -> None:
        self._show_value(level)
        self.postpone_close()
        self.level_changed.emit(level)

    def _on_released(self) -> None:
        self.postpone_close()
        self.released.emit()

    def _on_close_timer(self) -> None:
        if self.slider.isSliderDown():
            self._close_timer.start()
            return
        self.collapse()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.postpone_close()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # A left click in the gaps or on the value is not a click on the speaker: keep it open
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.postpone_close()
        else:
            event.ignore()

# pyright: reportPrivateUsage=false

"""Tests for the volume widget's inline slider: the slider that slides out of the bar beside the
speaker icon.

The audio service is replaced by a fake endpoint, so no test ever reads or changes the real
system volume. Widgets that must be laid out are shown with WA_DontShowOnScreen, so nothing
appears on the desktop.
"""

import sys
import time
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast, override
from unittest.mock import patch

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QEnterEvent, QWheelEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStyleFactory,
    QWidget,
)

APP = QApplication.instance() or QApplication([])

from core.bar_style import AdaptiveBarFrame  # noqa: E402
from core.utils.widgets.volume.inline_slider import InlineVolumeSlider  # noqa: E402
from core.validation.widgets.yasb.grouper import GrouperWidgetConfig  # noqa: E402
from core.validation.widgets.yasb.volume import VolumeConfig  # noqa: E402
from core.widgets.yasb.grouper import GrouperWidget  # noqa: E402
from core.widgets.yasb.volume import VolumeWidget  # noqa: E402


class QTestFunctions(Protocol):
    """The QTest functions these tests call, typed as they are called. QTest is a C++ namespace
    and its functions are static, but PyQt6's stubs declare them as instance methods of a class
    that cannot be instantiated, so a call on QTest would miss the `self` they declare."""

    def qWait(self, ms: int) -> None: ...

    def mouseClick(self, widget: QWidget | None, button: Qt.MouseButton, *, pos: QPoint = ...) -> None: ...


qtest = cast(QTestFunctions, QTest)


class FakeEndpoint:
    """Stands in for pycaw's IAudioEndpointVolume and records every write."""

    def __init__(self, level: float = 0.45, muted: bool = False):
        self.level = level
        self.muted = int(muted)
        self.level_writes: list[float] = []
        self.mute_writes: list[bool] = []

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.level

    def SetMasterVolumeLevelScalar(self, level: float, context: object) -> None:
        self.level_writes.append(round(level, 4))
        self.level = level

    def GetMute(self) -> int:
        return self.muted

    def SetMute(self, muted: bool, context: object) -> None:
        self.mute_writes.append(bool(muted))
        self.muted = int(bool(muted))


class FakeService:
    """Stands in for AudioOutputService, so the real endpoint is never opened."""

    def __init__(self, endpoint: FakeEndpoint | None):
        self.endpoint = endpoint

    def register_widget(self, widget: object) -> None:
        pass

    def unregister_widget(self, widget: object) -> None:
        pass

    def get_volume_interface(self) -> FakeEndpoint | None:
        return self.endpoint


def make_widget(
    endpoint: FakeEndpoint | None, inline: Mapping[str, int | bool] | None = None, **options: str | dict[str, str]
) -> VolumeWidget:
    """A volume widget on a fake endpoint; `inline` turns the inline slider on with those options."""
    config: dict[str, object] = {"label": "<span>{icon}</span>", "tooltip": False, "slider_beep": False, **options}
    if inline is not None:
        config["inline_slider"] = {"enabled": True, **inline}
    with patch("core.widgets.yasb.volume.AudioOutputService", return_value=FakeService(endpoint)):
        return VolumeWidget(VolumeConfig.model_validate(config))


def inline_slider(widget: VolumeWidget) -> InlineVolumeSlider:
    """The widget's inline slider, which exists whenever the widget was built with `inline`."""
    area = widget._inline_slider
    assert area is not None, "the inline slider is off"
    return area


def value_label(area: InlineVolumeSlider) -> QLabel:
    """The value beside the slider, which exists unless show_value is off."""
    label = area.value_label
    assert label is not None, "show_value is off"
    return label


def fake_service(widget: VolumeWidget) -> FakeService:
    """The fake service make_widget gave the widget in place of AudioOutputService."""
    service = widget._service
    assert isinstance(service, FakeService)
    return service


def show_offscreen(test: unittest.TestCase, widget: QWidget) -> QFrame:
    """Lay the widget out in a shown host that never reaches the screen, kept alive for the test."""
    host = QFrame()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    layout = QHBoxLayout(host)
    layout.addWidget(widget)
    layout.addStretch(1)  # like a bar column, so the widget gets its own width back on closing
    host.show()
    flush()
    test.addCleanup(host.deleteLater)
    return host


def flush() -> None:
    """Deliver posted events until none are left. Each layout level posts the next one's
    LayoutRequest, and Qt holds events posted during a pass until the next pass."""
    for _ in range(20):
        APP.processEvents()


def settle(area: InlineVolumeSlider) -> None:
    """Let a held slide run on, wait for it to stop, then for the layout to catch up."""
    if area._animation.state() == QAbstractAnimation.State.Paused:
        area._animation.resume()
    assert wait_until(lambda: area._animation.state() != QAbstractAnimation.State.Running), "still sliding"
    flush()


def hold_halfway(area: InlineVolumeSlider) -> None:
    """Pause the running slide at its midpoint. A test that polls the width instead can miss
    the whole slide if one event loop pass stalls for longer than the animation."""
    animation = area._animation
    animation.pause()
    animation.setCurrentTime(animation.duration() // 2)
    flush()


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 2000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate():
        if time.monotonic() > deadline:
            return False
        qtest.qWait(5)
    return True


class InlineSliderConfigTest(unittest.TestCase):
    def test_defaults_keep_the_feature_off(self):
        config = VolumeConfig()
        inline = config.inline_slider
        self.assertFalse(inline.enabled)
        self.assertEqual(
            (inline.width, inline.auto_close, inline.show_value, inline.animation_duration),
            (150, 4000, True, 220),
        )
        # The left click still opens the big menu unless the user rebinds it
        self.assertEqual(config.callbacks.on_left, "toggle_volume_menu")

    def test_options_are_validated(self):
        for field, bad in (("width", 0), ("auto_close", -1), ("animation_duration", -1), ("speed", 1)):
            with self.assertRaises(ValidationError, msg=field) as caught:
                VolumeConfig.model_validate({"inline_slider": {field: bad}})
            self.assertEqual(caught.exception.errors()[0]["loc"], ("inline_slider", field))

    def test_zero_auto_close_is_allowed(self):
        self.assertEqual(VolumeConfig.model_validate({"inline_slider": {"auto_close": 0}}).inline_slider.auto_close, 0)


class DisabledInlineSliderTest(unittest.TestCase):
    def test_widget_is_built_as_before(self):
        widget = make_widget(FakeEndpoint(), label="<span>{icon}</span> {level}")
        self.assertIsNone(widget._inline_slider)
        self.assertEqual(widget.findChildren(QSlider), [])
        container = widget._widget_container
        children = container.findChildren(QFrame, options=Qt.FindChildOption.FindDirectChildrenOnly)
        self.assertTrue(children and all(isinstance(child, QLabel) for child in children))

    def test_callback_is_a_no_op(self):
        widget = make_widget(FakeEndpoint())
        widget._run_callback("toggle_inline_slider")
        self.assertEqual(widget.findChildren(QSlider), [])


class InlineSliderOpenCloseTest(unittest.TestCase):
    def test_parts_carry_their_classes(self):
        widget = make_widget(FakeEndpoint(), inline={"width": 120})
        area = inline_slider(widget)
        self.assertEqual(area.slider.property("class"), "inline-slider")
        self.assertEqual((area.slider.minimum(), area.slider.maximum()), (0, 100))
        self.assertEqual(area.slider.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(area.slider.width(), 120)
        self.assertEqual(value_label(area).property("class"), "inline-value")
        self.assertIs(area.parentWidget(), widget._widget_container)

    def test_value_label_is_optional(self):
        widget = make_widget(FakeEndpoint(), inline={"show_value": False})
        self.assertIsNone(inline_slider(widget).value_label)
        self.assertFalse([label for label in widget.findChildren(QLabel) if label.property("class") == "inline-value"])

    def test_starts_closed(self):
        widget = make_widget(FakeEndpoint(), inline={})
        show_offscreen(self, widget)
        self.assertFalse(inline_slider(widget).is_expanded)
        self.assertTrue(inline_slider(widget).isHidden())

    def test_toggle_opens_to_its_width_and_closes(self):
        widget = make_widget(FakeEndpoint(), inline={"animation_duration": 0})
        show_offscreen(self, widget)
        area = inline_slider(widget)
        closed_width = widget.width()

        widget._run_callback("toggle_inline_slider")
        flush()
        self.assertTrue(area.is_expanded)
        self.assertTrue(area.isVisible())
        self.assertGreaterEqual(area.target_width(), 150)
        self.assertEqual(area.width(), area.target_width())
        self.assertGreaterEqual(widget.width(), closed_width + 150)

        widget._run_callback("toggle_inline_slider")
        flush()
        self.assertFalse(area.is_expanded)
        self.assertTrue(area.isHidden())
        self.assertEqual(widget.width(), closed_width)

    def test_opening_and_closing_slide(self):
        widget = make_widget(FakeEndpoint(), inline={"animation_duration": 220})
        show_offscreen(self, widget)
        area = inline_slider(widget)
        target = area.target_width()

        widget._run_callback("toggle_inline_slider")
        self.assertEqual(area.width(), 0)
        hold_halfway(area)
        self.assertTrue(0 < area.width() < target, area.width())
        settle(area)
        self.assertEqual(area.width(), target)

        widget._run_callback("toggle_inline_slider")
        hold_halfway(area)
        self.assertTrue(area.isVisible())  # still sliding shut
        self.assertTrue(0 < area.width() < target, area.width())
        settle(area)
        self.assertTrue(area.isHidden())

    def test_reopening_while_closing_reverses_from_where_it_is(self):
        widget = make_widget(FakeEndpoint(), inline={"animation_duration": 400})
        show_offscreen(self, widget)
        area = inline_slider(widget)
        target = area.target_width()
        widget._run_callback("toggle_inline_slider")
        settle(area)

        widget._run_callback("toggle_inline_slider")
        hold_halfway(area)
        part_shut = area.width()
        self.assertTrue(0 < part_shut < target, part_shut)
        widget._run_callback("toggle_inline_slider")
        flush()
        self.assertEqual(area.width(), part_shut)  # no jump back to zero
        settle(area)
        self.assertEqual(area.width(), target)

    def test_no_device_keeps_it_closed(self):
        widget = make_widget(None, inline={"animation_duration": 0})
        show_offscreen(self, widget)
        widget._run_callback("toggle_inline_slider")
        self.assertFalse(inline_slider(widget).is_expanded)
        self.assertTrue(inline_slider(widget).isHidden())


def open_slider(test: unittest.TestCase, endpoint: FakeEndpoint, **inline: int) -> VolumeWidget:
    """A shown widget with its inline slider opened, no animation unless asked for."""
    inline.setdefault("animation_duration", 0)
    widget = make_widget(endpoint, inline=inline, callbacks={"on_left": "toggle_inline_slider"})
    show_offscreen(test, widget)
    widget._run_callback("toggle_inline_slider")
    flush()
    return widget


def wheel(target: QWidget, steps: int = 1) -> QWheelEvent:
    """Deliver a wheel notch to target. Qt only passes spontaneous wheel events up to the
    parent, so a test delivers to the widget it means; returns the event to check acceptance."""
    point = QPointF(5, 5)
    event = QWheelEvent(
        point,
        point,
        QPoint(0, 0),
        QPoint(0, 120 * steps),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(target, event)
    return event


class InlineSliderVolumeTest(unittest.TestCase):
    def test_opening_shows_the_current_level_without_writing_it(self):
        endpoint = FakeEndpoint(level=0.3)
        area = inline_slider(open_slider(self, endpoint))
        self.assertEqual((area.slider.value(), value_label(area).text()), (30, "30"))
        self.assertEqual(endpoint.level_writes, [])

    def test_moving_the_slider_sets_the_master_volume(self):
        endpoint = FakeEndpoint(level=0.45)
        area = inline_slider(open_slider(self, endpoint))
        area.slider.setValue(30)
        self.assertEqual(endpoint.level_writes, [0.3])
        self.assertEqual(value_label(area).text(), "30")

    def test_zero_mutes_and_moving_up_unmutes(self):
        endpoint = FakeEndpoint(level=0.45)
        area = inline_slider(open_slider(self, endpoint))
        area.slider.setValue(0)
        self.assertEqual(endpoint.mute_writes, [True])
        area.slider.setValue(10)
        self.assertEqual(endpoint.mute_writes, [True, False])

    def test_clicking_the_groove_jumps_there(self):
        endpoint = FakeEndpoint(level=0.1)
        area = inline_slider(open_slider(self, endpoint, width=200))
        slider = area.slider
        # Fusion steps toward a click a page at a time, as windowsvista does on Windows 10
        style = QStyleFactory.create("Fusion")
        slider.setStyle(style)
        self.addCleanup(lambda: slider.setStyle(None))
        point = QPoint(round(slider.width() * 0.75), slider.height() // 2)
        qtest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=point)
        self.assertAlmostEqual(slider.value(), 75, delta=4)
        self.assertEqual(endpoint.level_writes[-1], slider.value() / 100)

    def test_an_outside_change_is_shown_without_writing_back(self):
        endpoint = FakeEndpoint(level=0.45)
        widget = open_slider(self, endpoint)
        endpoint.level = 0.62  # keyboard keys, the popup, another app
        widget._update_label()
        area = inline_slider(widget)
        self.assertEqual((area.slider.value(), value_label(area).text()), (62, "62"))
        self.assertEqual(endpoint.level_writes, [])
        self.assertEqual(endpoint.mute_writes, [])

    def test_an_outside_change_does_not_pull_the_handle_mid_drag(self):
        endpoint = FakeEndpoint(level=0.45)
        widget = open_slider(self, endpoint)
        area = inline_slider(widget)
        area.slider.setSliderDown(True)
        endpoint.level = 0.2  # a late notification for an earlier drag position
        widget._update_label()
        self.assertEqual(area.slider.value(), 45)
        area.slider.setSliderDown(False)

    def test_the_slider_leaves_the_wheel_to_the_widget(self):
        endpoint = FakeEndpoint(level=0.45)
        area = inline_slider(open_slider(self, endpoint))
        event = wheel(area.slider)
        self.assertFalse(event.isAccepted())  # so Qt passes it on up to the volume widget
        self.assertEqual(area.slider.value(), 45)
        self.assertEqual(endpoint.level_writes, [])

    def test_wheel_steps_the_volume_and_the_slider_follows(self):
        endpoint = FakeEndpoint(level=0.45)
        widget = open_slider(self, endpoint)
        wheel(widget)
        self.assertEqual(endpoint.level_writes, [0.47])  # scroll_step 2
        area = inline_slider(widget)
        self.assertEqual((area.slider.value(), value_label(area).text()), (47, "47"))

    def test_wheel_still_works_while_closed(self):
        endpoint = FakeEndpoint(level=0.45)
        widget = make_widget(endpoint, inline={})
        show_offscreen(self, widget)
        wheel(widget, -1)
        self.assertEqual(endpoint.level_writes, [0.43])

    def test_losing_the_device_closes_it(self):
        widget = open_slider(self, FakeEndpoint())
        fake_service(widget).endpoint = None
        widget._reinitialize_audio()
        self.assertFalse(inline_slider(widget).is_expanded)


class InlineSliderAutoCloseTest(unittest.TestCase):
    def test_closes_after_the_quiet_interval(self):
        started = time.monotonic()
        area = inline_slider(open_slider(self, FakeEndpoint(), auto_close=150))
        self.assertTrue(area.is_expanded)
        self.assertTrue(wait_until(lambda: not area.is_expanded))
        self.assertGreaterEqual(time.monotonic() - started, 0.14)

    def test_moving_the_slider_restarts_the_countdown(self):
        area = inline_slider(open_slider(self, FakeEndpoint(), auto_close=1000))
        qtest.qWait(400)
        area.slider.setValue(20)
        self.assertGreater(area._close_timer.remainingTime(), 900)

    def test_wheel_restarts_the_countdown(self):
        widget = open_slider(self, FakeEndpoint(), auto_close=1000)
        qtest.qWait(400)
        wheel(widget)
        self.assertGreater(inline_slider(widget)._close_timer.remainingTime(), 900)

    def test_hovering_holds_it_open(self):
        area = inline_slider(open_slider(self, FakeEndpoint(), auto_close=100))
        QApplication.sendEvent(area, QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2)))
        qtest.qWait(250)
        self.assertTrue(area.is_expanded)
        QApplication.sendEvent(area, QEvent(QEvent.Type.Leave))
        self.assertTrue(wait_until(lambda: not area.is_expanded))

    def test_a_drag_holds_it_open(self):
        area = inline_slider(open_slider(self, FakeEndpoint(), auto_close=100))
        area.slider.setSliderDown(True)
        qtest.qWait(250)
        self.assertTrue(area.is_expanded)
        area.slider.setSliderDown(False)
        self.assertTrue(wait_until(lambda: not area.is_expanded))

    def test_zero_never_closes(self):
        area = inline_slider(open_slider(self, FakeEndpoint(), auto_close=0))
        QApplication.sendEvent(area, QEvent(QEvent.Type.Leave))
        area.slider.setValue(20)
        qtest.qWait(150)
        self.assertTrue(area.is_expanded)
        self.assertFalse(area._close_timer.isActive())


class InlineSliderClicksTest(unittest.TestCase):
    def test_clicking_the_speaker_closes_it(self):
        widget = open_slider(self, FakeEndpoint())
        qtest.mouseClick(widget._widgets[0], Qt.MouseButton.LeftButton)
        self.assertFalse(inline_slider(widget).is_expanded)

    def test_clicking_the_value_keeps_it_open(self):
        widget = open_slider(self, FakeEndpoint())
        qtest.mouseClick(value_label(inline_slider(widget)), Qt.MouseButton.LeftButton)
        self.assertTrue(inline_slider(widget).is_expanded)

    def test_right_click_still_mutes(self):
        endpoint = FakeEndpoint()
        widget = open_slider(self, endpoint)
        qtest.mouseClick(value_label(inline_slider(widget)), Qt.MouseButton.RightButton)
        self.assertEqual(endpoint.mute_writes, [True])


class VisibilityRecorder(QObject):
    """Records the show and hide events a grouper's hide_empty filter reacts to."""

    WATCHED = (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.ShowToParent, QEvent.Type.HideToParent)

    def __init__(self, watched: QObject):
        super().__init__()
        self.events: list[QEvent.Type] = []
        watched.installEventFilter(self)

    @override
    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() in self.WATCHED:
            self.events.append(a1.type())
        return False


class InlineSliderGrouperTest(unittest.TestCase):
    def test_sliding_never_shows_or_hides_the_widget_itself(self):
        widget = make_widget(FakeEndpoint(), inline={"animation_duration": 60})
        show_offscreen(self, widget)
        recorder = VisibilityRecorder(widget)
        widget._run_callback("toggle_inline_slider")
        settle(inline_slider(widget))
        widget._run_callback("toggle_inline_slider")
        settle(inline_slider(widget))
        self.assertEqual(recorder.events, [])

    def test_collapsed_grouper_with_volume_excluded(self):
        volume = {
            "type": "yasb.volume.VolumeWidget",
            "options": {
                "label": "<span>{icon}</span>",
                "tooltip": False,
                "slider_beep": False,
                "inline_slider": {"enabled": True, "animation_duration": 0},
            },
        }
        config = GrouperWidgetConfig.model_validate(
            {
                "widgets": ["volume"],
                "hide_empty": True,
                "collapse_options": {"enabled": True, "exclude_widgets": ["volume"]},
            }
        )
        with patch("core.widgets.yasb.volume.AudioOutputService", return_value=FakeService(FakeEndpoint())):
            grouper = GrouperWidget(config, widget_configs={"volume": volume})
        widget = grouper._child_widgets[0]
        assert isinstance(widget, VolumeWidget)
        show_offscreen(self, grouper)
        self.assertTrue(widget.isVisible())

        widget._run_callback("toggle_inline_slider")
        flush()
        self.assertTrue(grouper.isVisible() and widget.isVisible() and inline_slider(widget).isVisible())

        grouper._toggle_collapsed()  # expand the group, then collapse it again
        grouper._toggle_collapsed()
        flush()
        self.assertTrue(grouper.isVisible() and widget.isVisible())
        self.assertTrue(inline_slider(widget).is_expanded)

        widget._run_callback("toggle_inline_slider")
        flush()
        self.assertTrue(grouper.isVisible() and widget.isVisible())


class InlineSliderIslandTest(unittest.TestCase):
    """On the adaptive bar the island under a group is cut from the widgets' geometry."""

    def build_bar(self, widget: QWidget) -> tuple[AdaptiveBarFrame, QLabel]:
        """The bar's frame and three columns as Bar._add_widgets builds them, the volume widget
        last in the right column, after another pill."""
        window = QWidget()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        frame = AdaptiveBarFrame(window, "top")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        columns: list[QHBoxLayout] = []
        for column in range(3):
            container = QFrame()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            grid.addWidget(container, 0, column)
            columns.append(layout)
        right = columns[2]
        right.insertStretch(0, 1)
        neighbour = QLabel("neighbour")
        right.addWidget(neighbour)
        right.addWidget(widget)
        frame.setLayout(grid)
        window.resize(900, 32)
        frame.setGeometry(0, 0, 900, 32)
        window.show()
        flush()
        self.addCleanup(window.deleteLater)
        return frame, neighbour

    def test_island_follows_the_slide_once_per_frame(self):
        widget = make_widget(FakeEndpoint(), inline={"animation_duration": 220})
        frame, neighbour = self.build_bar(widget)
        area = inline_slider(widget)
        padding = frame.grouppadding

        frames: list[object] = []
        area._animation.valueChanged.connect(frames.append)
        spans = patch.object(frame, "_island_spans", wraps=frame._island_spans)
        counter = spans.start()
        self.addCleanup(spans.stop)

        def island_left_matches() -> bool:
            # The neighbour pill is pushed left as the volume pill grows; the island must follow
            return frame._islands[0][0] == neighbour.mapTo(frame, QPoint(0, 0)).x() - padding

        closed_left = frame._islands[0][0]
        animation = area._animation
        for _ in range(2):  # open, then close
            widget._run_callback("toggle_inline_slider")
            # Step the slide one 16 ms frame at a time, as the animation timer would
            animation.pause()
            seen: set[int] = set()
            for time_ms in range(16, animation.duration(), 16):
                animation.setCurrentTime(time_ms)
                flush()
                self.assertTrue(island_left_matches(), (frame._islands, area.width()))
                seen.add(frame._islands[0][0])
            settle(area)
            self.assertTrue(island_left_matches())
            self.assertGreater(len(seen), 8, "the island jumped instead of sliding")
            if area.is_expanded:
                self.assertLessEqual(frame._islands[0][0], closed_left - 150)

        self.assertEqual(frame._islands[0][0], closed_left)
        # Recomputed on the layout requests the slide causes: no more than once per frame
        self.assertLessEqual(counter.call_count, len(frames) + 2)


if __name__ == "__main__":
    unittest.main()

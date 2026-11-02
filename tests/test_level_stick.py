# pyright: reportPrivateUsage=false

"""Tests for the level stick: a vertical progress_bar beside the icon of the microphone, volume and
battery widgets, coloured by the widget's state (muted, battery level, charging).

Each test reads the colours the stick actually paints, from a 4x20 linear_vertical bar with no
animation, so a level and a colour are checked as the bar shows them: the fill grows up from the
bottom edge and the track shows above it.

The audio services and the battery API are replaced by fakes, so no test reads or changes the
real system volume or battery.
"""

import sys
import unittest
from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QAbstractAnimation, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.utils.progress_bar import ProgressWidget  # noqa: E402
from core.utils.widgets.volume.inline_slider import InlineVolumeSlider  # noqa: E402
from core.validation.widgets.yasb.battery import BatteryConfig  # noqa: E402
from core.validation.widgets.yasb.microphone import MicrophoneConfig  # noqa: E402
from core.validation.widgets.yasb.volume import VolumeConfig  # noqa: E402
from core.widgets.services.battery.battery_api import POWER_TIME_UNKNOWN, BatteryData  # noqa: E402
from core.widgets.yasb.battery import BatteryWidget  # noqa: E402
from core.widgets.yasb.microphone import MicrophoneWidget  # noqa: E402
from core.widgets.yasb.volume import VolumeWidget  # noqa: E402


class QTestFunctions(Protocol):
    """The QTest function these tests call, typed as it is called. QTest is a C++ namespace and
    its functions are static, but PyQt6's stubs declare them as instance methods of a class that
    cannot be instantiated, so a call on QTest would miss the `self` they declare."""

    def qWait(self, ms: int) -> None: ...


qtest = cast(QTestFunctions, QTest)

TRACK = "#45475a"
PINK = "#f5c2e7"
GREEN = "#a6e3a1"
GREY = "#6c7086"
YELLOW = "#f9e2af"
CYAN = "#00bcd4"
RED = "#ff4444"

STICK = {
    "enabled": True,
    "progress_type": "linear_vertical",
    "size": 20,
    "thickness": 4,
    "radius": 0,
    "background_color": TRACK,
    "position": "right",
    "animation": False,
}

StickOption = str | dict[str, str]
"""A progress_bar option a test sets on top of STICK: muted_color, or level_colors."""

StickWidget = MicrophoneWidget | VolumeWidget | BatteryWidget


class FakeEndpoint:
    """Stands in for pycaw's IAudioEndpointVolume (speaker or microphone)."""

    def __init__(self, level: float, muted: bool = False):
        self.level = level
        self.muted = int(muted)

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.level

    def SetMasterVolumeLevelScalar(self, level: float, context: object) -> None:
        self.level = level

    def GetMute(self) -> int:
        return self.muted

    def SetMute(self, muted: bool, context: object) -> None:
        self.muted = int(bool(muted))


class FakeAudioService:
    """Stands in for AudioOutputService and AudioInputService, so no real endpoint is opened."""

    def __init__(self, endpoint: FakeEndpoint):
        self.endpoint = endpoint

    def register_widget(self, widget: object) -> None:
        pass

    def unregister_widget(self, widget: object) -> None:
        pass

    def get_volume_interface(self) -> FakeEndpoint:
        return self.endpoint

    def get_microphone_interface(self) -> FakeEndpoint:
        return self.endpoint


class FakeBatteryAPI:
    def __init__(self, data: BatteryData):
        self.data = data

    def get_status(self) -> BatteryData:
        return self.data


def battery_data(
    percent: int, is_charging: bool = False, power_plugged: bool = False, time_remaining: int = POWER_TIME_UNKNOWN
) -> BatteryData:
    return BatteryData(
        percent=percent,
        is_charging=is_charging,
        power_plugged=power_plugged,
        time_remaining=time_remaining,
        rate=None,
        voltage=None,
        capacity=None,
        full_capacity=None,
        designed_capacity=None,
        temperature=None,
        cycle_count=None,
        chemistry=None,
        health_percent=None,
    )


def make_mic(endpoint: FakeEndpoint, **stick: StickOption) -> MicrophoneWidget:
    config = MicrophoneConfig.model_validate(
        {"label": "<span>{icon}</span>", "tooltip": False, "progress_bar": {**STICK, "color": PINK, **stick}}
    )
    with patch("core.widgets.yasb.microphone.AudioInputService", return_value=FakeAudioService(endpoint)):
        return MicrophoneWidget(config)


def make_volume(endpoint: FakeEndpoint, inline: bool = False, **stick: StickOption) -> VolumeWidget:
    options: dict[str, object] = {
        "label": "<span>{icon}</span>",
        "tooltip": False,
        "slider_beep": False,
        "progress_bar": {**STICK, "color": GREEN, **stick},
    }
    if inline:
        options["inline_slider"] = {"enabled": True, "animation_duration": 60, "auto_close": 0}
    with patch("core.widgets.yasb.volume.AudioOutputService", return_value=FakeAudioService(endpoint)):
        return VolumeWidget(VolumeConfig.model_validate(options))


def make_battery(data: BatteryData, tooltip: bool | None = None, **stick: StickOption) -> BatteryWidget:
    options: dict[str, object] = {
        "label": "<span>{icon}</span>",
        "update_interval": 0,
        "charging_options": {"blink_charging_icon": False},
        "progress_bar": {**STICK, "color": RED, **stick},
    }
    if tooltip is not None:
        options["tooltip"] = tooltip
    with patch("core.widgets.yasb.battery.BatteryAPI.instance", return_value=FakeBatteryAPI(data)):
        widget = BatteryWidget(BatteryConfig.model_validate(options))
    widget._update_label()
    return widget


def fake_battery_api(battery: BatteryWidget) -> FakeBatteryAPI:
    """The fake API make_battery gave the widget in place of BatteryAPI."""
    api = battery._battery_api
    assert isinstance(api, FakeBatteryAPI)
    return api


def level_stick(widget: StickWidget) -> ProgressWidget:
    """The widget's stick, which every widget here is built with."""
    stick = widget.progress_widget
    assert stick is not None, "the progress_bar is off"
    return stick


def inline_slider(volume: VolumeWidget) -> InlineVolumeSlider:
    """The volume widget's inline slider, which make_volume builds when asked for `inline`."""
    slider = volume._inline_slider
    assert slider is not None, "the inline slider is off"
    return slider


def stick_at(widget: StickWidget, height_from_bottom: int) -> str:
    """The colour the stick paints this many pixels up from its bottom edge (1 = bottom row)."""
    image = level_stick(widget).grab().toImage()
    return image.pixelColor(1, image.height() - height_from_bottom).name()


class MicrophoneStickTest(unittest.TestCase):
    def test_unmuted_stick_fills_to_the_level_in_its_colour(self):
        mic = make_mic(FakeEndpoint(0.70), muted_color=GREY)
        self.assertEqual(stick_at(mic, 1), PINK)
        self.assertEqual(stick_at(mic, 13), PINK)  # 70% of 20px
        self.assertEqual(stick_at(mic, 16), TRACK)

    def test_muted_stick_keeps_its_level_in_the_muted_colour(self):
        mic = make_mic(FakeEndpoint(0.70, muted=True), muted_color=GREY)
        self.assertEqual(stick_at(mic, 1), GREY)
        self.assertEqual(stick_at(mic, 13), GREY)
        self.assertEqual(stick_at(mic, 16), TRACK)

    def test_unmuting_brings_the_colour_back(self):
        endpoint = FakeEndpoint(0.70, muted=True)
        mic = make_mic(endpoint, muted_color=GREY)
        endpoint.muted = 0
        mic._update_label()
        self.assertEqual(stick_at(mic, 13), PINK)

    def test_without_muted_color_a_muted_stick_is_empty_as_before(self):
        mic = make_mic(FakeEndpoint(0.70, muted=True))
        self.assertEqual(stick_at(mic, 1), TRACK)


class VolumeStickTest(unittest.TestCase):
    def test_muted_stick_keeps_its_level_in_the_muted_colour(self):
        volume = make_volume(FakeEndpoint(0.45, muted=True), muted_color=GREY)
        self.assertEqual(stick_at(volume, 1), GREY)
        self.assertEqual(stick_at(volume, 8), GREY)  # 45% of 20px = 9px
        self.assertEqual(stick_at(volume, 11), TRACK)

    def test_toggling_mute_switches_the_colour(self):
        volume = make_volume(FakeEndpoint(0.45), muted_color=GREY)
        self.assertEqual(stick_at(volume, 8), GREEN)
        volume.toggle_mute()
        self.assertEqual(stick_at(volume, 8), GREY)
        volume.toggle_mute()
        self.assertEqual(stick_at(volume, 8), GREEN)

    def test_without_muted_color_a_muted_stick_is_empty_as_before(self):
        volume = make_volume(FakeEndpoint(0.45, muted=True))
        self.assertEqual(stick_at(volume, 1), TRACK)


def show_offscreen(test: unittest.TestCase, widget: QWidget) -> QFrame:
    host = QFrame()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    layout = QHBoxLayout(host)
    layout.addWidget(widget)
    layout.addStretch(1)
    host.show()
    for _ in range(20):
        APP.processEvents()
    test.addCleanup(host.deleteLater)
    return host


def wait_for_slide(slider: InlineVolumeSlider) -> None:
    for _ in range(400):
        if slider._animation.state() != QAbstractAnimation.State.Running:
            break
        qtest.qWait(5)
    for _ in range(20):
        APP.processEvents()


class VolumeStickBesideInlineSliderTest(unittest.TestCase):
    def test_stick_hides_while_the_slider_is_out(self):
        volume = make_volume(FakeEndpoint(0.45), inline=True)
        show_offscreen(self, volume)
        self.assertTrue(level_stick(volume).isVisible())

        volume._toggle_inline_slider()
        self.assertFalse(level_stick(volume).isVisible())
        wait_for_slide(inline_slider(volume))
        volume._update_label()  # a level change while open must not bring it back
        self.assertFalse(level_stick(volume).isVisible())

    def test_stick_comes_back_once_the_slider_has_slid_in(self):
        volume = make_volume(FakeEndpoint(0.45), inline=True)
        show_offscreen(self, volume)
        volume._toggle_inline_slider()
        wait_for_slide(inline_slider(volume))

        volume._toggle_inline_slider()
        wait_for_slide(inline_slider(volume))
        self.assertTrue(level_stick(volume).isVisible())
        self.assertFalse(inline_slider(volume).isVisible())


LEVEL_COLORS = {"medium": YELLOW, "charging": CYAN}


class BatteryStickTest(unittest.TestCase):
    def test_stick_takes_the_colour_of_its_level(self):
        battery = make_battery(battery_data(59), level_colors=LEVEL_COLORS)
        self.assertEqual(stick_at(battery, 1), YELLOW)
        self.assertEqual(stick_at(battery, 11), YELLOW)  # 59% of 20px = 11.8px
        self.assertEqual(stick_at(battery, 14), TRACK)

    def test_charging_takes_the_charging_colour(self):
        battery = make_battery(battery_data(59, is_charging=True, power_plugged=True), level_colors=LEVEL_COLORS)
        self.assertEqual(stick_at(battery, 1), CYAN)

    def test_plugged_in_but_not_charging_keeps_the_level_colour(self):
        battery = make_battery(battery_data(59, power_plugged=True), level_colors=LEVEL_COLORS)
        self.assertEqual(stick_at(battery, 1), YELLOW)

    def test_a_level_left_out_keeps_color(self):
        battery = make_battery(battery_data(90), level_colors=LEVEL_COLORS)  # "high" has no entry
        self.assertEqual(stick_at(battery, 1), RED)

    def test_colour_follows_the_level_as_it_changes(self):
        battery = make_battery(battery_data(59), level_colors=LEVEL_COLORS)
        api = fake_battery_api(battery)
        api.data = battery_data(59, is_charging=True, power_plugged=True)
        battery._update_label()
        self.assertEqual(stick_at(battery, 1), CYAN)
        api.data = battery_data(90)
        battery._update_label()
        self.assertEqual(stick_at(battery, 1), RED)


class BatteryTooltipTest(unittest.TestCase):
    def tooltip(self, battery: BatteryWidget) -> str | None:
        tooltip_filter = getattr(battery, "_tooltip_filter", None)
        return tooltip_filter.tooltip_text if tooltip_filter else None

    def test_no_tooltip_unless_asked(self):
        self.assertIsNone(self.tooltip(make_battery(battery_data(59))))

    def test_tooltip_shows_the_percent_and_state(self):
        cases = [
            (battery_data(59), "Battery 59%"),
            (battery_data(59, power_plugged=True), "Battery 59%, plugged in"),
            (battery_data(59, is_charging=True, power_plugged=True), "Battery 59%, charging"),
            (battery_data(42, time_remaining=2 * 3600 + 5 * 60), "Battery 42%, 2:05:00 left"),
        ]
        for data, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.tooltip(make_battery(data, tooltip=True)), expected)


if __name__ == "__main__":
    unittest.main()

# pyright: reportPrivateUsage=false
"""Level-coloured rings and container state classes for the cpu, memory, gpu and disk widgets.

Each widget already sorts its reading into low / medium / high / critical by its thresholds. With
`progress_bar.level_colors` set, the whole ring takes that level's colour instead of `color`, and
the level always lands on the `.widget-container` as `status-<level>`, so a stylesheet can colour
the icon with `.memory-widget .widget-container.status-high .icon`.

The widgets are built for real with their shared worker threads stubbed out, fed readings through
the same slots their workers use, and the ring is read back from its own painted pixels.
"""

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from core.utils import utilities
from core.utils.progress_bar import ProgressBar
from core.utils.utilities import level_color, set_container_level
from core.validation.widgets.yasb.cpu import CpuConfig
from core.validation.widgets.yasb.disk import DiskConfig
from core.validation.widgets.yasb.gpu import GpuConfig
from core.validation.widgets.yasb.memory import MemoryConfig
from core.widgets.services.cpu.cpu_api import CpuData, CpuFreq, CpuWorker
from core.widgets.services.gpu.gpu_api import GpuData, GpuWorker
from core.widgets.services.memory.memory_api import MemoryData, MemoryWorker, SwapMemory, VirtualMemory
from core.widgets.yasb import disk
from core.widgets.yasb.cpu import CpuWidget
from core.widgets.yasb.disk import DiskWidget
from core.widgets.yasb.gpu import GpuWidget
from core.widgets.yasb.memory import MemoryWidget

GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
GREY = "#a6adc8"
TRACK = "#313244"
GRADIENT = [RED, "#fab387", YELLOW, GREEN, GREEN]
# Green under 60, yellow 60-85, red over 85.
THRESHOLDS = {"low": 25, "medium": 60, "high": 85}
LEVEL_COLORS = {"low": GREEN, "medium": GREEN, "high": YELLOW, "critical": RED}
CONFIGS = (CpuConfig, MemoryConfig, GpuConfig, DiskConfig)

type HwmonConfig = type[CpuConfig] | type[MemoryConfig] | type[GpuConfig] | type[DiskConfig]
type HwmonWidget = CpuWidget | MemoryWidget | GpuWidget | DiskWidget
type _Feed = Callable[[float], None]


def _ring_options(**extra: object) -> dict[str, object]:
    """A 16px ring, 3px thick, without animation so a reading paints at once."""
    return {
        "enabled": True,
        "position": "right",
        "size": 16,
        "thickness": 3,
        "color": GRADIENT,
        "background_color": TRACK,
        "animation": False,
        **extra,
    }


def _ring_colors(bar: ProgressBar, angles: tuple[float, ...] = (10, 90, 180, 270, 300)) -> list[QColor]:
    """Sample the painted ring on the middle of its stroke, clockwise from 12 o'clock."""
    image = bar.grab().toImage()
    scale = image.width() / bar.width()
    margin = (bar._thickness + 1) // 2 + 1
    radius = (bar.width() - 2 * margin) / 2
    centre = bar.width() / 2
    samples: list[QColor] = []
    for angle in angles:
        theta = math.radians(angle)
        x = centre + radius * math.sin(theta)
        y = centre - radius * math.cos(theta)
        samples.append(image.pixelColor(int(x * scale), int(y * scale)))
    return samples


def _close_to(color: QColor, hex_color: str, tolerance: int = 10) -> bool:
    want = QColor(hex_color)
    return (
        abs(color.red() - want.red()) <= tolerance
        and abs(color.green() - want.green()) <= tolerance
        and abs(color.blue() - want.blue()) <= tolerance
        and color.alpha() >= 250
    )


def _find_class(root: QWidget, cls: str) -> QWidget:
    """The first descendant whose class list contains *cls*."""
    for child in root.findChildren(QWidget):
        if cls in str(child.property("class") or "").split():
            return child
    raise AssertionError(f"nothing under {root!r} has the class {cls!r}")


# --- the ring and the helpers on their own --------------------------------------------


def test_a_single_colour_fills_the_whole_arc(qapp: QApplication):
    bar = ProgressBar(size=16, thickness=3, color=RED, background_color=TRACK, animation=False)
    bar.set_value(90)
    for sample in _ring_colors(bar):
        assert _close_to(sample, RED), sample.name()


def test_set_color_swaps_a_gradient_for_one_colour(qapp: QApplication):
    bar = ProgressBar(size=16, thickness=3, color=GRADIENT, background_color=TRACK, animation=False)
    bar.set_value(90)
    before = _ring_colors(bar)
    assert before[0].name() != before[2].name(), "a gradient should vary along the arc"
    bar.set_color(YELLOW)
    for sample in _ring_colors(bar):
        assert _close_to(sample, YELLOW), sample.name()


def test_level_color_picks_the_levels_colour():
    colors = MemoryConfig.model_validate({"progress_bar": _ring_options(level_colors=LEVEL_COLORS)})
    level_colors = colors.progress_bar.level_colors
    assert level_color(level_colors, "high", GRADIENT) == YELLOW
    assert level_color(level_colors, "critical", GRADIENT) == RED


def test_level_color_falls_back_to_color_without_level_colors():
    assert level_color(None, "critical", GRADIENT) == GRADIENT
    assert level_color(None, "low", "#00c800") == "#00c800"


def test_level_color_falls_back_to_color_for_a_level_left_out():
    config = MemoryConfig.model_validate({"progress_bar": _ring_options(level_colors={"critical": RED})})
    level_colors = config.progress_bar.level_colors
    assert level_color(level_colors, "low", GRADIENT) == GRADIENT
    assert level_color(level_colors, "critical", GRADIENT) == RED


# --- config ---------------------------------------------------------------------------


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_level_colors_are_off_by_default(config_cls: HwmonConfig):
    assert config_cls().progress_bar.level_colors is None


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_level_colors_take_the_widgets_level_names(config_cls: HwmonConfig):
    config = config_cls.model_validate({"progress_bar": _ring_options(level_colors=LEVEL_COLORS)})
    colors = config.progress_bar.level_colors
    assert colors is not None
    assert (colors.low, colors.medium, colors.high, colors.critical) == (GREEN, GREEN, YELLOW, RED)


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_level_colors_reject_an_unknown_level(config_cls: HwmonConfig):
    with pytest.raises(ValidationError):
        config_cls.model_validate({"progress_bar": _ring_options(level_colors={"warning": YELLOW})})


def test_disk_thresholds_match_cpu_and_memory():
    for thresholds in (CpuConfig().cpu_thresholds, MemoryConfig().memory_thresholds, DiskConfig().disk_thresholds):
        assert (thresholds.low, thresholds.medium, thresholds.high) == (25, 50, 90)


# --- set_container_level --------------------------------------------------------------

_ICON_CSS = (
    f".host .widget-container .icon {{ color: {GREY}; }}"
    f".host .widget-container.status-high .icon {{ color: {YELLOW}; }}"
    f".host .widget-container.status-critical .icon {{ color: {RED}; }}"
)


@dataclass
class _Styled:
    host: QWidget
    container: QWidget
    icon: QLabel

    def icon_color(self) -> str:
        return self.icon.palette().color(QPalette.ColorRole.WindowText).name()


@pytest.fixture
def styled(qapp: QApplication) -> _Styled:
    host = QWidget()
    host.setProperty("class", "host")
    container = QWidget(host)
    container.setProperty("class", "widget-container")
    icon = QLabel("x", container)
    icon.setProperty("class", "icon")
    host.setStyleSheet(_ICON_CSS)
    host.ensurePolished()
    icon.ensurePolished()
    return _Styled(host, container, icon)


def test_set_container_level_keeps_the_other_classes(styled: _Styled):
    styled.container.setProperty("class", "widget-container extra")
    set_container_level(styled.container, "high")
    assert styled.container.property("class") == "widget-container extra status-high"
    set_container_level(styled.container, "low")
    assert styled.container.property("class") == "widget-container extra status-low"


def test_descendant_selectors_follow_the_level(styled: _Styled):
    assert styled.icon_color() == GREY
    set_container_level(styled.container, "high")
    assert styled.icon_color() == YELLOW
    set_container_level(styled.container, "critical")
    assert styled.icon_color() == RED
    set_container_level(styled.container, "low")
    assert styled.icon_color() == GREY


def test_set_container_level_repolishes_only_when_the_level_changes(styled: _Styled, monkeypatch: pytest.MonkeyPatch):
    refreshed: list[tuple[QWidget | None, ...]] = []
    original = utilities.refresh_widget_style

    def refresh(*widgets: QWidget | None) -> None:
        refreshed.append(widgets)
        original(*widgets)

    monkeypatch.setattr(utilities, "refresh_widget_style", refresh)
    assert set_container_level(styled.container, "high")
    assert len(refreshed) == 1
    assert not set_container_level(styled.container, "high")
    assert len(refreshed) == 1
    assert set_container_level(styled.container, "critical")
    assert len(refreshed) == 2


# --- the four widgets -----------------------------------------------------------------


@dataclass
class _Rig:
    """One widget in a host frame, and how to hand it a reading."""

    host: QWidget
    widget: HwmonWidget
    feed: _Feed

    def ring(self) -> ProgressBar:
        progress = self.widget.progress_widget
        assert progress is not None
        return progress._progress_bar

    def container(self) -> QWidget:
        return self.widget._widget_container

    def assert_ring(self, hex_color: str, percent: float) -> None:
        # The start of the arc and the middle of the painted span; past its end is the track.
        for sample in _ring_colors(self.ring(), (10, percent * 3.6 / 2)):
            assert _close_to(sample, hex_color), f"{sample.name()} != {hex_color}"


type _Build = Callable[[pytest.MonkeyPatch, dict[str, object]], tuple[HwmonWidget, _Feed]]
type MakeRig = Callable[..., _Rig]

_LABEL = "<span>R</span> {}"


def _fake_worker(*_args: object) -> MagicMock:
    return MagicMock()


def _cpu(monkeypatch: pytest.MonkeyPatch, progress_bar: dict[str, object]) -> tuple[CpuWidget, _Feed]:
    monkeypatch.setattr(CpuWidget, "_instances", [])
    monkeypatch.setattr(CpuWidget, "_worker", None)
    monkeypatch.setattr(CpuWorker, "get_instance", _fake_worker)
    config = {"label": _LABEL.format("{info[percent][total]}%"), "cpu_thresholds": THRESHOLDS}
    widget = CpuWidget(CpuConfig.model_validate({**config, "progress_bar": progress_bar}))

    def feed(percent: float) -> None:
        freq = CpuFreq(current=3000, min=0, max=4000)
        data = CpuData(freq=freq, percent=percent, percent_per_core=[percent], cores_physical=1, cores_logical=1)
        CpuWidget._on_data_ready(data)

    return widget, feed


def _memory(monkeypatch: pytest.MonkeyPatch, progress_bar: dict[str, object]) -> tuple[MemoryWidget, _Feed]:
    monkeypatch.setattr(MemoryWidget, "_instances", [])
    monkeypatch.setattr(MemoryWidget, "_worker", None)
    monkeypatch.setattr(MemoryWorker, "get_instance", _fake_worker)
    config = {"label": _LABEL.format("{virtual_mem_percent}%"), "memory_thresholds": THRESHOLDS}
    widget = MemoryWidget(MemoryConfig.model_validate({**config, "progress_bar": progress_bar}))

    def feed(percent: float) -> None:
        used = round(percent)
        virtual = VirtualMemory(total=100, available=100 - used, percent=percent, used=used, free=100 - used)
        MemoryWidget._on_data_ready(MemoryData(virtual=virtual, swap=SwapMemory(total=0, used=0, free=0, percent=0)))

    return widget, feed


def _gpu(monkeypatch: pytest.MonkeyPatch, progress_bar: dict[str, object]) -> tuple[GpuWidget, _Feed]:
    monkeypatch.setattr(GpuWidget, "_instances", [])
    monkeypatch.setattr(GpuWidget, "_worker", None)
    monkeypatch.setattr(GpuWorker, "get_instance", _fake_worker)
    config = {"label": _LABEL.format("{info[utilization]}%"), "gpu_thresholds": THRESHOLDS}
    widget = GpuWidget(GpuConfig.model_validate({**config, "progress_bar": progress_bar}))

    def feed(percent: float) -> None:
        data = GpuData(
            gpu_index=0,
            name="Test GPU",
            utilization=percent,
            mem_total=0,
            mem_used=0,
            mem_free=0,
            mem_shared_total=0,
            mem_shared_used=0,
            temp=0,
            fan_speed=0,
            power_draw=0.0,
        )
        GpuWidget._on_gpu_data([data])

    return widget, feed


def _disk(monkeypatch: pytest.MonkeyPatch, progress_bar: dict[str, object]) -> tuple[DiskWidget, _Feed]:
    total = 1000
    free = [total]

    def free_space(_root: str) -> tuple[int, int, int]:
        return free[0], total, free[0]

    monkeypatch.setattr(disk, "GetDiskFreeSpaceEx", free_space)
    config = {"label": _LABEL.format("{space[used][percent]}"), "update_interval": 0, "disk_thresholds": THRESHOLDS}
    widget = DiskWidget(DiskConfig.model_validate({**config, "progress_bar": progress_bar}))

    def feed(percent: float) -> None:
        free[0] = total - round(percent * total / 100)
        widget._update_label()

    return widget, feed


_BUILDERS: dict[str, _Build] = {"cpu": _cpu, "memory": _memory, "gpu": _gpu, "disk": _disk}


@pytest.fixture(params=list(_BUILDERS))
def make_rig(request: pytest.FixtureRequest, qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeRig]:
    build = _BUILDERS[request.param]
    rigs: list[_Rig] = []

    def make(**progress_bar: object) -> _Rig:
        widget, feed = build(monkeypatch, _ring_options(**progress_bar))
        host = QWidget()
        QVBoxLayout(host).addWidget(widget)
        rig = _Rig(host, widget, feed)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.widget.timer.stop()
        rig.host.close()


def test_level_colors_pick_one_colour_per_level_at_the_boundaries(make_rig: MakeRig):
    rig = make_rig(level_colors=LEVEL_COLORS)
    # Each threshold is the top of its level: 60 is still medium, 85 still high.
    for percent, level, color in (
        (25, "low", GREEN),
        (60, "medium", GREEN),
        (61, "high", YELLOW),
        (85, "high", YELLOW),
        (86, "critical", RED),
        (40, "medium", GREEN),
    ):
        rig.feed(percent)
        assert rig.container().property("class") == f"widget-container status-{level}", percent
        rig.assert_ring(color, percent)


def test_without_level_colors_the_ring_keeps_its_gradient(make_rig: MakeRig):
    rig = make_rig()
    rig.feed(90)
    first, _, middle, *_ = _ring_colors(rig.ring())
    assert first.name() != middle.name()
    assert rig.container().property("class") == "widget-container status-critical"


def test_a_level_left_out_keeps_color(make_rig: MakeRig):
    rig = make_rig(level_colors={"high": YELLOW, "critical": RED}, color=GREEN)
    rig.feed(40)
    rig.assert_ring(GREEN, 40)
    rig.feed(90)
    rig.assert_ring(RED, 90)


def test_text_labels_keep_their_status_class(make_rig: MakeRig):
    rig = make_rig(level_colors=LEVEL_COLORS)
    rig.feed(70)
    assert _find_class(rig.widget, "label").property("class") == "label status-high"


def test_container_repolishes_only_when_the_level_changes(make_rig: MakeRig, monkeypatch: pytest.MonkeyPatch):
    rig = make_rig(level_colors=LEVEL_COLORS)
    rig.feed(70)
    container = rig.container()
    repolished: list[QWidget] = []
    original = utilities.refresh_widget_style

    def refresh(*widgets: QWidget | None) -> None:
        if container in widgets:
            repolished.append(container)
        original(*widgets)

    monkeypatch.setattr(utilities, "refresh_widget_style", refresh)
    rig.feed(72)
    rig.feed(80)
    assert repolished == []
    rig.feed(90)
    assert len(repolished) == 1

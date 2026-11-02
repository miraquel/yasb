# pyright: reportPrivateUsage=false
"""The traffic widget's sparkline and its compact speed placeholders.

The formatter and the bar model are Qt-free. The widget tests build a real TrafficWidget with the
IO counters, the internet checker and the data file all faked, so nothing touches the network or
the traffic totals stored on disk.
"""

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QRegion
from PyQt6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget
from qt_css_engine import extract_rules

from core.utils.css_processor import CSSProcessor
from core.utils.widgets.traffic.sparkline import SparklineModel, log_speed
from core.utils.widgets.traffic.sparkline_view import TrafficSparkline
from core.validation.widgets.yasb.traffic import TrafficSparklineConfig, TrafficWidgetConfig
from core.widgets.services.traffic.network_api import IOCounters
from core.widgets.services.traffic.traffic_manager import NetworkData, TrafficDataManager
from core.widgets.yasb import traffic
from core.widgets.yasb.traffic import TrafficWidget

KIB = 1024
MIB = 1024 * 1024

compact = TrafficDataManager.format_speed_compact


def _io(sent: int = 0, recv: int = 0) -> IOCounters:
    return IOCounters(sent, recv, 0, 0, 0, 0, 0, 0)


# --- compact speed placeholders --------------------------------------------------------


@pytest.mark.parametrize(
    ("bytes_per_sec", "expected"),
    [
        (0, ("  0", "K")),
        (7.4 * KIB, ("7.4", "K")),
        (56 * KIB, (" 56", "K")),
        (562 * KIB, ("562", "K")),
        (9.96 * KIB, (" 10", "K")),
        (999.4 * KIB, ("999", "K")),
        (999.5 * KIB, ("1.0", "M")),
        (1000 * KIB, ("1.0", "M")),
        (23 * MIB, (" 23", "M")),
        (2.5 * 1024 * MIB, ("2.5", "G")),
    ],
)
def test_compact_in_bytes(bytes_per_sec: float, expected: tuple[str, str]):
    assert compact(bytes_per_sec, "bytes", 0) == expected


@pytest.mark.parametrize(
    ("bytes_per_sec", "expected"),
    [
        # bits: bytes * 8 / 1000, rolling over every 1000.
        (925, ("7.4", "K")),
        (7_000, (" 56", "K")),
        (124_925, ("999", "K")),
        (124_937.5, ("1.0", "M")),
        (2_875_000, (" 23", "M")),
        (125_000_000, ("1.0", "G")),
    ],
)
def test_compact_in_bits(bytes_per_sec: float, expected: tuple[str, str]):
    assert compact(bytes_per_sec, "bits", 0) == expected


@pytest.mark.parametrize("speed_unit", ["bits", "bytes"])
def test_compact_value_is_always_three_characters(speed_unit: str):
    for value in (0, 1, 500, 5 * KIB, 50 * KIB, 500 * KIB, 5 * MIB, 50 * MIB, 500 * MIB, 5000 * MIB):
        assert len(compact(value, speed_unit, 0)[0]) == 3, value


def test_compact_below_the_threshold_is_zero():
    assert compact(999, "bytes", 1000) == ("  0", "K")
    assert compact(999, "bits", 1000) == ("  0", "K")
    assert compact(1000, "bytes", 1000) == ("1.0", "K")


def _network_data(monkeypatch: pytest.MonkeyPatch, io: IOCounters, previous: int, **kwargs: Any) -> NetworkData | None:
    def io_counters(interface: str) -> IOCounters:
        return io

    def should_save(interface: str) -> bool:
        return False

    monkeypatch.setattr(TrafficDataManager, "get_interface_io_counters", staticmethod(io_counters))
    monkeypatch.setattr(TrafficDataManager, "should_save_data", staticmethod(should_save))
    monkeypatch.setattr(TrafficDataManager, "_interface_data", {})
    return TrafficDataManager.calculate_network_data(
        interface="spark-calc",
        previous_sent=previous,
        previous_recv=previous,
        session_sent=previous,
        session_recv=previous,
        interval_seconds=1.0,
        speed_unit="bytes",
        hide_decimal=False,
        **kwargs,
    )


def test_network_data_has_compact_and_raw_speeds(monkeypatch: pytest.MonkeyPatch):
    data = _network_data(
        monkeypatch,
        _io(10_000 + 2 * KIB, 10_000 + 56 * KIB),
        10_000,
        speed_threshold={"min_upload": 1000, "min_download": 1000},
        max_label_length=12,
        max_label_length_align="left",
    )

    assert data is not None
    assert (data["download_compact_value"], data["download_compact_unit"]) == (" 56", "K")
    assert (data["upload_compact_value"], data["upload_compact_unit"]) == ("2.0", "K")
    assert data["download_bytes_per_sec"] == 56 * KIB
    assert data["upload_bytes_per_sec"] == 2 * KIB
    # max_label_length still pads the old keys, but never the compact ones.
    assert data["download_speed"] == "56.0 KB/s   "


def test_counter_reset_reports_zero_raw_speed(monkeypatch: pytest.MonkeyPatch):
    data = _network_data(monkeypatch, _io(5, 5), 100, speed_threshold={"min_upload": 0, "min_download": 0})

    assert data is not None
    assert (data["download_bytes_per_sec"], data["upload_bytes_per_sec"]) == (0.0, 0.0)


# --- the bar model ---------------------------------------------------------------------


@pytest.fixture
def model() -> SparklineModel:
    return SparklineModel(download_threshold=1000, upload_threshold=1000)


def test_default_geometry(model: SparklineModel):
    assert (model.width, model.height) == (38, 16)
    assert (model.up_max, model.down_max) == (6, 9)
    assert [model.bar_x(i) for i in (0, 1, 11)] == [1, 4, 34]


def test_starts_empty_with_only_the_baseline(model: SparklineModel):
    rects = model.rects()

    assert model.samples == [(0.0, 0.0)] * 12
    assert rects.baseline == (0, 9, 38, 1)
    assert (rects.download, rects.upload) == ((), ())


def test_full_scale_sample_fills_both_directions(model: SparklineModel):
    model.push(65536, 65536)
    rects = model.rects()

    # Download rows 0..8 above the baseline, upload rows 10..15 below it, newest bar on the right.
    assert rects.download == ((34, 0, 2, 9),)
    assert rects.upload == ((34, 10, 2, 6),)


def test_tiny_but_active_sample_gets_one_pixel(model: SparklineModel):
    model.push(1000, 1000)
    rects = model.rects()

    assert model.heights()[-1] == (1, 1)
    assert rects.download == ((34, 8, 2, 1),)
    assert rects.upload == ((34, 10, 2, 1),)


def test_below_the_threshold_draws_nothing(model: SparklineModel):
    model.push(999, 999)

    assert model.heights()[-1] == (0, 0)


def test_zero_draws_nothing_even_with_no_threshold():
    model = SparklineModel()
    model.push(0, 0)

    assert model.heights() == [(0, 0)] * 12


def test_peak_never_drops_below_the_floor(model: SparklineModel):
    assert model.peak() == log_speed(65536)
    model.push(10 * KIB, 0)
    assert model.peak() == log_speed(65536)
    # 9 KiB/s is exactly 1 on the log scale: round(1 / lg(64 KiB) * 9) = 5.
    model.push(9 * KIB, 0)
    assert model.heights()[-1][0] == round(1 / log_speed(65536) * 9)


def test_peak_follows_the_busiest_sample_in_either_direction(model: SparklineModel):
    model.push(1 * MIB, 0)
    model.push(0, 10 * MIB)
    peak = log_speed(10 * MIB)

    assert model.peak() == peak
    assert model.heights()[-2][0] == round(log_speed(1 * MIB) / peak * 9)
    assert model.heights()[-1][1] == 6


def test_window_scrolls_left(model: SparklineModel):
    model.push(65536, 0)
    for _ in range(11):
        model.push(0, 0)
    assert model.heights()[0] == (9, 0)

    model.push(0, 0)
    assert model.heights() == [(0, 0)] * 12
    assert len(model.samples) == 12


def test_custom_geometry():
    model = SparklineModel(bars=5, bar_width=3, bar_gap=0, height=11)
    model.push(65536, 65536)
    rects = model.rects()

    assert (model.width, model.up_max, model.down_max) == (17, 4, 6)
    assert rects.baseline == (0, 6, 17, 1)
    assert rects.download == ((13, 0, 3, 6),)
    assert rects.upload == ((13, 7, 3, 4),)


# --- config ----------------------------------------------------------------------------


def test_sparkline_is_off_by_default():
    spark = TrafficWidgetConfig().sparkline

    assert not spark.enabled
    assert (spark.bars, spark.bar_width, spark.bar_gap, spark.height, spark.scale_floor) == (12, 2, 1, 16, 65536)


def test_unknown_keys_are_still_rejected():
    with pytest.raises(ValidationError):
        TrafficWidgetConfig.model_validate({"sparkline": {"enabled": True, "colour": "red"}})
    with pytest.raises(ValidationError):
        TrafficWidgetConfig.model_validate({"not_an_option": True})


@pytest.mark.parametrize(
    ("field", "value"),
    [("bars", 0), ("bar_width", 0), ("bar_gap", -1), ("height", 2), ("scale_floor", 0)],
)
def test_sizes_must_be_positive(field: str, value: int):
    with pytest.raises(ValidationError):
        TrafficSparklineConfig.model_validate({field: value})


# --- the painter -----------------------------------------------------------------------


def _pixel(image: QImage, x: int, y: int) -> QColor:
    return QColor(image.pixelColor(x, y))


def test_paints_the_bars_at_the_defaults(qapp: QApplication):
    spark = TrafficSparkline(SparklineModel(download_threshold=1000, upload_threshold=1000))
    spark.push(65536, 65536)
    spark.resize(spark.sizeHint())
    assert (spark.width(), spark.height()) == (38, 16)

    image = QImage(38, 16, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    spark.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)

    down, up, base = QColor("#89dceb"), QColor("#cba6f7"), QColor("#45475a")
    for x in range(38):
        assert _pixel(image, x, 9) == base, x
    for x in (34, 35):
        for y in range(9):
            assert _pixel(image, x, y) == down, (x, y)
        for y in range(10, 16):
            assert _pixel(image, x, y) == up, (x, y)
    for x, y in ((33, 0), (36, 5), (0, 15), (31, 12)):
        assert _pixel(image, x, y).alpha() == 0, (x, y)
    spark.deleteLater()


def test_colours_and_margin_come_from_the_stylesheet(qapp: QApplication, tmp_path: Path):
    # Through YASB's real pipeline, which lowercases names: camelCase in styles.css still works.
    styles = tmp_path / "styles.css"
    styles.write_text(
        ".traffic-widget .traffic-sparkline {\n"
        "    -qproperty-downloadColor: #ff0000;\n"
        "    -qproperty-uploadcolor: #00ff00;\n"
        "    -qproperty-baselinecolor: #0000ff;\n"
        "    margin-left: 4px;\n"
        "}\n",
        encoding="utf-8",
    )
    stylesheet = extract_rules(CSSProcessor(str(styles)).process())[0]

    host = QFrame()
    host.setProperty("class", "traffic-widget")
    spark = TrafficSparkline(SparklineModel())
    QVBoxLayout(host).addWidget(spark)
    host.setStyleSheet(stylesheet)
    spark.ensurePolished()

    assert spark.downloadcolor == QColor("#ff0000")
    assert spark.uploadcolor == QColor("#00ff00")
    assert spark.baselinecolor == QColor("#0000ff")
    assert (spark.sizeHint().width(), spark.sizeHint().height()) == (42, 16)
    host.deleteLater()


# --- the widget ------------------------------------------------------------------------


class _FakeInternetChecker(QObject):
    connection_changed = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None, interface: str | None = None) -> None:
        super().__init__(parent)


@dataclass
class _Network:
    """What the faked IO counters report; a test sets ``io`` and then runs an update."""

    interface: str
    io: IOCounters


type MakeWidget = Callable[..., TrafficWidget]

ALT_LABEL = (
    '<span></span><span class="dn">↓</span>{download_compact_value}<span class="unit">{download_compact_unit}'
    '</span><span class="up">↑</span>{upload_compact_value}<span class="unit">{upload_compact_unit}</span>'
)

_interfaces = itertools.count(1)


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Network]:
    net = _Network(f"spark-test-{next(_interfaces)}", _io())

    def io_counters(interface: str) -> IOCounters:
        return net.io

    def should_save(interface: str) -> bool:
        return False

    def setup_storage() -> None:
        pass

    monkeypatch.setattr(traffic, "InternetChecker", _FakeInternetChecker)
    monkeypatch.setattr(TrafficDataManager, "get_interface_io_counters", staticmethod(io_counters))
    monkeypatch.setattr(TrafficDataManager, "should_save_data", staticmethod(should_save))
    monkeypatch.setattr(TrafficDataManager, "setup_global_data_storage", staticmethod(setup_storage))
    monkeypatch.setattr(TrafficDataManager, "_global_data_folder", None)
    yield net

    timer = TrafficWidget._shared_timers.pop(net.interface, None)
    if timer is not None:
        timer.stop()
    TrafficWidget._instances_by_interface.pop(net.interface, None)
    TrafficWidget._shared_data.pop(net.interface, None)
    TrafficDataManager._interface_data.pop(net.interface, None)
    TrafficDataManager._interface_last_save_times.pop(net.interface, None)


@pytest.fixture
def make_widget(qapp: QApplication, network: _Network) -> Iterator[MakeWidget]:
    widgets: list[TrafficWidget] = []

    def make(**options: Any) -> TrafficWidget:
        config = {"label": "<span></span>", "label_alt": ALT_LABEL, **options, "interface": network.interface}
        widget = TrafficWidget(TrafficWidgetConfig.model_validate(config))
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.close()
        widget.deleteLater()


def _sparkline(widget: TrafficWidget) -> TrafficSparkline:
    assert widget._sparkline is not None
    return widget._sparkline


def _layout_widgets(widget: TrafficWidget) -> list[QWidget | None]:
    layout = widget._widget_container_layout
    items = [layout.itemAt(i) for i in range(layout.count())]
    return [item.widget() if item is not None else None for item in items]


def test_sparkline_sits_right_after_the_primary_label(make_widget: MakeWidget):
    widget = make_widget(label="<span></span> {download_speed}", sparkline={"enabled": True})
    spark = _sparkline(widget)

    assert _layout_widgets(widget) == [*widget._widgets, spark, *widget._widgets_alt]
    assert spark.property("class") == "traffic-sparkline"
    assert (spark.sizeHint().width(), spark.sizeHint().height()) == (38, 16)


def test_sparkline_hides_while_the_alt_label_shows(make_widget: MakeWidget):
    widget = make_widget(sparkline={"enabled": True})
    spark = _sparkline(widget)
    assert not spark.isHidden()

    widget._run_callback("toggle_label")
    assert spark.isHidden()
    assert all(not label.isHidden() for label in widget._widgets_alt)

    widget._run_callback("toggle_label")
    assert not spark.isHidden()
    assert all(label.isHidden() for label in widget._widgets_alt)


def test_no_sparkline_when_disabled(make_widget: MakeWidget, network: _Network):
    widget = make_widget()

    assert widget._sparkline is None
    assert widget.findChildren(TrafficSparkline) == []
    assert _layout_widgets(widget) == [*widget._widgets, *widget._widgets_alt]
    # Updates and toggles still work without one.
    network.io = _io(2 * KIB, 64 * KIB)
    TrafficWidget._update_interface_data(network.interface)
    widget._run_callback("toggle_label")


def test_every_instance_gets_one_sample_per_update(make_widget: MakeWidget, network: _Network):
    first = make_widget(sparkline={"enabled": True})
    second = make_widget(sparkline={"enabled": True, "bars": 4})
    network.io = _io(2 * KIB, 64 * KIB)
    TrafficWidget._update_interface_data(network.interface)

    for widget in (first, second):
        samples = _sparkline(widget).model.samples
        assert samples[-1] == (64 * KIB, 2 * KIB)
        assert samples[-2] == (0.0, 0.0)

    # Toggling only redraws the same data; it must not add a sample.
    before = _sparkline(first).model.samples
    first._run_callback("toggle_label")
    first._run_callback("toggle_label")
    assert _sparkline(first).model.samples == before


def test_compact_placeholders_fill_the_alt_label(make_widget: MakeWidget, network: _Network):
    widget = make_widget(speed_unit="bytes", sparkline={"enabled": True})
    network.io = _io(2 * KIB, 64 * KIB)
    TrafficWidget._update_interface_data(network.interface)
    widget._run_callback("toggle_label")

    assert [label.text() for label in widget._widgets_alt] == ["", "↓", " 64", "K", "↑", "2.0", "K"]
    assert [label.property("class") for label in widget._widgets_alt] == [
        "icon",
        "dn",
        "label alt",
        "unit",
        "up",
        "label alt",
        "unit",
    ]

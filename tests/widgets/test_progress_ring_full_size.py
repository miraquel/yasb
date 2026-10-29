# pyright: reportPrivateUsage=false
"""`progress_bar.full_size`: a circular ring drawn out to the edge of its box.

By default the ring's stroke is inset by a pixel more than half its thickness, so a 16px ring
with thickness 3 paints 13px across and its edges land on half pixels. With `full_size` the
stroke is centred half a thickness in from the edge: 16px across, edges on whole pixels.
Linear bars ignore the flag, and leaving it out changes nothing.
"""

import pytest
from PyQt6.QtCore import QPointF, QRect, QRectF
from PyQt6.QtGui import QConicalGradient
from PyQt6.QtWidgets import QApplication, QWidget

from core.utils.progress_bar import ProgressBar
from core.utils.utilities import build_progress_widget
from core.validation.widgets.yasb.cpu import CpuProgressBarConfig
from core.validation.widgets.yasb.disk import DiskProgressBarConfig
from core.validation.widgets.yasb.gpu import GpuProgressBarConfig
from core.validation.widgets.yasb.memory import MemoryProgressBarConfig

GREEN = "#a6e3a1"
RED = "#f38ba8"
TRACK = "#313244"
MODELS = (CpuProgressBarConfig, MemoryProgressBarConfig, GpuProgressBarConfig, DiskProgressBarConfig)

type ProgressBarModel = (
    type[CpuProgressBarConfig]
    | type[MemoryProgressBarConfig]
    | type[GpuProgressBarConfig]
    | type[DiskProgressBarConfig]
)


def _ring(
    *,
    size: int = 16,
    thickness: int = 3,
    color: str | list[str] = GREEN,
    progress_type: str = "circular",
    full_size: bool = False,
) -> ProgressBar:
    return ProgressBar(
        size=size,
        thickness=thickness,
        color=color,
        background_color=TRACK,
        animation=False,
        progress_type=progress_type,
        full_size=full_size,
    )


def _painted_columns(bar: ProgressBar) -> tuple[int, int]:
    """First column and one past the last column the ring touches along its horizontal midline.

    grab() fills the box with the window background first, so "painted" means differing from
    the box's top-left corner, which a circle never reaches.
    """
    image = bar.grab().toImage()
    scale = image.width() / bar.width()
    row = int(bar.height() / 2 * scale)
    background = image.pixelColor(0, 0)

    def differs(x: int) -> bool:
        c = image.pixelColor(x, row)
        distance = (
            abs(c.red() - background.red()) + abs(c.green() - background.green()) + abs(c.blue() - background.blue())
        )
        return distance > 24

    painted = [x for x in range(image.width()) if differs(x)]
    return int(painted[0] / scale), int(painted[-1] / scale) + 1


# --- the ring's geometry --------------------------------------------------------------


def test_default_keeps_the_legacy_inset(qapp: QApplication):
    # (3 + 1) // 2 + 1 = 3px in from each edge of the 16px box, still on whole pixels.
    assert _ring()._circular_rect() == QRect(3, 3, 10, 10)


def test_full_size_centres_the_stroke_half_a_thickness_in(qapp: QApplication):
    assert _ring(full_size=True)._circular_rect() == QRectF(1.5, 1.5, 13, 13)


def test_full_size_follows_thickness_and_size(qapp: QApplication):
    assert _ring(size=20, thickness=2, full_size=True)._circular_rect() == QRectF(1, 1, 18, 18)


def test_full_size_ring_paints_edge_to_edge(qapp: QApplication):
    bar = _ring(full_size=True)
    bar.set_value(100)
    assert _painted_columns(bar) == (0, 16)


def test_default_ring_stays_13px_across(qapp: QApplication):
    bar = _ring()
    bar.set_value(100)
    left, right = _painted_columns(bar)
    assert right - left == 14  # 1.5 .. 14.5, antialiased into the half pixels
    assert left > 0


def test_default_gradient_keeps_its_centre(qapp: QApplication):
    # An unset ring paints exactly as before: the conical gradient still turns about QRect.center().
    bar = _ring(color=[RED, GREEN])
    brush = bar._create_circular_progress_brush(bar._circular_rect())
    assert isinstance(brush, QConicalGradient)
    assert brush.center() == QPointF(7, 7)


def test_full_size_gradient_turns_about_the_middle_of_the_box(qapp: QApplication):
    bar = _ring(color=[RED, GREEN], full_size=True)
    brush = bar._create_circular_progress_brush(bar._circular_rect())
    assert isinstance(brush, QConicalGradient)
    assert brush.center() == QPointF(8, 8)


def test_linear_bar_ignores_full_size(qapp: QApplication):
    bar = _ring(progress_type="linear_horizontal", full_size=True)
    assert (bar.width(), bar.height()) == (16, 3)


# --- config ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", MODELS)
def test_full_size_is_off_by_default(model: ProgressBarModel):
    assert model().full_size is False


@pytest.mark.parametrize("model", MODELS)
def test_full_size_is_accepted_on_every_hwmon_ring(model: ProgressBarModel):
    assert model.model_validate({"full_size": True}).full_size is True


@pytest.mark.parametrize("model", MODELS)
def test_full_size_reaches_the_progress_bar(qapp: QApplication, model: ProgressBarModel):
    options = model.model_validate({"enabled": True, "size": 16, "thickness": 3, "full_size": True}).model_dump()
    progress = build_progress_widget(QWidget(), options)
    assert progress is not None
    assert progress._progress_bar._full_size is True


def test_progress_bar_configs_without_the_key_still_build(qapp: QApplication):
    options = CpuProgressBarConfig(enabled=True).model_dump()
    del options["full_size"]
    progress = build_progress_widget(QWidget(), options)
    assert progress is not None
    assert progress._progress_bar._full_size is False

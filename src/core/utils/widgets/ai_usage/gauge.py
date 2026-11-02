"""The fill gauge behind each half of the AI pill: which window it shows, in which colour, how far.

Qt-free and shared by the Claude and Codex widgets; ``gauge_view.UsageGauge`` paints it. A widget
with two windows (Claude's 5-hour and 7-day) lets the short one drive the fill and the number,
with the long one as a thin line along the bottom, until the long one reaches crit_percent. From
then on the long window is what will actually lock you out, so it takes the fill and the number,
and the short one drops to the line.
"""

from dataclasses import dataclass
from typing import Literal

Step = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class GaugeWindow:
    name: str
    # Share of the window consumed; None while there is no reading.
    used: float | None


@dataclass(frozen=True)
class GaugeReading:
    fill: GaugeWindow | None
    line: GaugeWindow | None
    # The fill window's name when it is the long window, so "97%" never passes for the 5 hours.
    prefix: str


def step(used: float | None, warn: float, crit: float) -> Step | None:
    """Colour step for a share consumed: low below warn, medium from warn, high from crit."""
    if used is None:
        return None
    if used >= crit:
        return "high"
    if used >= warn:
        return "medium"
    return "low"


def pick(short: GaugeWindow | None, long: GaugeWindow | None, crit: float, swapped: bool = False) -> GaugeReading:
    """Which window takes the fill and which the line.

    ``swapped`` is the right-click label: it shows the window that is not driving. A lone window
    always drives, unprefixed, since there is nothing to tell it apart from.
    """
    if short is None or long is None:
        return GaugeReading(short or long, None, "")
    long_drives = long.used is not None and long.used >= crit
    if long_drives != swapped:
        return GaugeReading(long, short, long.name)
    return GaugeReading(short, long, "")


def share(used: float | None, mode: str) -> float | None:
    """How much of the half to fill: the share consumed, or what is left in "remaining" mode.

    ``mode`` is the widget's ``usage_mode`` ("used" or "remaining", validated by its config)."""
    if used is None:
        return None
    value = 100.0 - used if mode == "remaining" else float(used)
    return max(0.0, min(100.0, value))

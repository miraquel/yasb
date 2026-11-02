"""The rain rules shared by the pill and the card.

An hour is wet at the wet threshold (30%) or more, heavy at the heavy one (80%). Bar height is the
chance of rain, not how hard it rains. Heights round half up, as the approved mockups do.
"""

import math
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

from core.utils.widgets.local_weather.forecast import Day, Hour

Level = Literal["dry", "wet", "heavy", "none"]

# How far ahead a stop or "clears by" time is looked for, past the bars on show.
STOP_SEARCH_HOURS = 24
NO_FORECAST_LINE = "Can't reach WeatherAPI. Trying again every minute."


@dataclass(frozen=True)
class Thresholds:
    wet: int = 30
    heavy: int = 80


@dataclass(frozen=True)
class Bar:
    level: Level
    height: int
    label: str = ""


@dataclass(frozen=True)
class PillReading:
    state: Literal["rain-coming", "raining", "dry", "none"]
    bars: tuple[Bar, ...]
    time: str


@dataclass(frozen=True)
class Hero:
    state: Literal["coming", "coming-now", "raining", "raining-on", "dry", "none"]
    label: str
    figure: str
    line: str


def half_up(x: float) -> int:
    return math.floor(x + 0.5)


def level(chance: int, t: Thresholds) -> Level:
    if chance >= t.heavy:
        return "heavy"
    if chance >= t.wet:
        return "wet"
    return "dry"


def pill_bar(chance: int | None, t: Thresholds) -> Bar:
    """A wet hour is a bar 4-13px tall; a dry one is a 2px dot."""
    if chance is None:
        return Bar("none", 2)
    lv = level(chance, t)
    if lv == "dry":
        return Bar("dry", 2)
    return Bar(lv, half_up(chance * 13 / 100))


def card_bar(chance: int | None, t: Thresholds) -> Bar:
    """Every hour keeps its proportional height, so a rising chance shows before it turns wet."""
    if chance is None:
        return Bar("none", 3)
    lv = level(chance, t)
    return Bar(lv, max(3, half_up(chance * 58 / 100)), f"{chance}%" if lv != "dry" else "")


def mini_bar(chance: int | None, t: Thresholds) -> Bar:
    if chance is None:
        return Bar("none", 2)
    return Bar(level(chance, t), max(2, half_up(chance * 14 / 100)))


def _clock(start: int, now: datetime) -> str:
    return datetime.fromtimestamp(start, now.tzinfo).strftime("%H:%M")


def _first_wet(chances: list[int], t: Thresholds) -> int | None:
    return next((i for i, c in enumerate(chances) if c >= t.wet), None)


def _first_dry_after(chances: list[int], t: Thresholds, i: int) -> int | None:
    return next((j for j in range(i + 1, len(chances)) if chances[j] < t.wet), None)


def _peak(chances: list[int], lo: int, hi: int) -> int:
    """The index of the highest chance in [lo, hi); ties go to the earliest hour."""
    best = lo
    for i in range(lo, hi):
        if chances[i] > chances[best]:
            best = i
    return best


def pill_reading(hours: list[Hour] | None, raining: bool, now: datetime, t: Thresholds, count: int) -> PillReading:
    """The pill's bars and its one time. ``hours`` runs from the current hour, up to a day ahead."""
    if not hours:
        return PillReading("none", (pill_bar(None, t),) * count, "")
    chances = [h.chance for h in hours]
    bars = tuple(pill_bar(chances[i] if i < len(chances) else None, t) for i in range(count))
    if raining:
        stop = _first_dry_after(chances, t, 0)
        return PillReading("raining", bars, _clock(hours[stop].start, now) if stop is not None else "")
    first = _first_wet(chances[:count], t)
    if first is None:
        return PillReading("dry", bars, "")
    return PillReading("rain-coming", bars, "now" if first == 0 else _clock(hours[first].start, now))


def _raining_line(hours: list[Hour], chances: list[int], peak: int, end: int, now: datetime) -> str:
    """ "Heaviest ..., lighter after ...", with "lighter after" only before ``end`` (the stop)."""
    head = "Heaviest now" if peak == 0 else f"Heaviest around {_clock(hours[peak].start, now)}"
    lighter = next((j for j in range(peak + 1, end) if chances[j] < chances[peak]), None)
    return head + (f", lighter after {_clock(hours[lighter].start, now)}" if lighter is not None else "")


def hero_reading(hours: list[Hour] | None, raining: bool, now: datetime, t: Thresholds, count: int) -> Hero:
    """The card's answer: its label, Display figure and supporting line."""
    next_hours = f"Next {count} hours"
    if not hours:
        return Hero("none", next_hours, "No forecast", NO_FORECAST_LINE)
    chances = [h.chance for h in hours]
    window = min(count, len(chances))

    if raining:
        stop = _first_dry_after(chances, t, 0)
        if stop is not None and stop <= count - 1:
            line = _raining_line(hours, chances, _peak(chances, 0, stop), stop, now)
            return Hero("raining", "Rain stops around", _clock(hours[stop].start, now), line)
        line = _raining_line(hours, chances, _peak(chances, 0, window), window, now)
        return Hero("raining-on", "Rain continues past", _clock(hours[window - 1].start + 3600, now), line)

    first = _first_wet(chances[:window], t)
    if first is None:
        top = max(chances[:window])
        if top == 0:
            return Hero("dry", next_hours, "Dry", "No rain expected")
        at = _clock(hours[chances.index(top)].start, now)
        return Hero("dry", next_hours, "Dry", f"Highest chance is {top}%, at {at}")

    clear = _first_dry_after(chances, t, first)
    clears = f", clears by {_clock(hours[clear].start, now)}" if clear is not None else ""
    if first == 0:
        return Hero("coming-now", "Rain likely", "Now", f"{chances[0]}% chance this hour{clears}")
    # The heaviest hour of the spell that starts, so a later shower can't be named before it clears.
    peak = _peak(chances, first, clear if clear is not None else window)
    return Hero(
        "coming",
        "Rain starts",
        _clock(hours[first].start, now),
        f"Heaviest around {_clock(hours[peak].start, now)}{clears}",
    )


def day_blocks(day: Day, tz: tzinfo, t: Thresholds) -> tuple[Bar, ...]:
    """Eight 3-hour blocks (00-03 ... 21-24), each the highest chance in its hours."""
    blocks: list[int | None] = [None] * 8
    for h in day.hours:
        b = datetime.fromtimestamp(h.start, tz).hour // 3
        blocks[b] = h.chance if blocks[b] is None else max(blocks[b], h.chance)
    return tuple(mini_bar(c, t) for c in blocks)


def day_text(day: Day, tz: tzinfo, t: Thresholds) -> str:
    wet = [h for h in day.hours if h.chance >= t.wet]
    if not wet:
        return "Mostly dry"
    if len(wet) >= 12:
        return "Rain most of the day"
    return f"Rain from {datetime.fromtimestamp(wet[0].start, tz):%H}:00"

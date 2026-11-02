"""Tests for the rain rules: the 30/80 rule, bar heights, the pill's time, the card's hero, and
the day rows. Fixed Jakarta times, synthetic payloads, no clock."""

import unittest
from datetime import datetime
from typing import Any

from core.utils.widgets.local_weather.forecast import hours_from
from core.utils.widgets.local_weather.rain import (
    Bar,
    Thresholds,
    card_bar,
    day_blocks,
    day_text,
    hero_reading,
    level,
    mini_bar,
    pill_bar,
    pill_reading,
)
from tests.support.local_weather import JAKARTA, at, forecast, rain

T = Thresholds()
COMING = rain(13, [10, 25, 70, 95, 60, 35, 20, 15, 10, 10, 5, 5])
RAINING = rain(16, [95, 60, 35, 20, 15])
DRY = rain(13, [5, 10, 10, 15, 10, 5, 5, 5, 10, 10, 5, 5])


def hours(chances: dict[int, int], now: datetime, **kw: Any):
    return hours_from(forecast(chances, **kw), now, 24)


def pill(chances: dict[int, int], now: datetime | None = None, raining: bool = False, count: int = 6):
    now = now or at(13, 10)
    return pill_reading(hours(chances, now), raining, now, T, count)


def hero(chances: dict[int, int], now: datetime | None = None, raining: bool = False):
    now = now or at(13, 10)
    h = hero_reading(hours(chances, now), raining, now, T, 12)
    return (h.state, h.label, h.figure, h.line)


class BarTests(unittest.TestCase):
    def test_thirty_eighty_rule(self):
        self.assertEqual([level(c, T) for c in (29, 30, 79, 80)], ["dry", "wet", "wet", "heavy"])

    def test_heights_round_half_up(self):
        self.assertEqual(pill_bar(50, T).height, 7)
        self.assertEqual(card_bar(25, T).height, 15)
        self.assertEqual(card_bar(5, T), Bar("dry", 3))
        self.assertEqual(mini_bar(40, T).height, 6)
        self.assertEqual(mini_bar(0, T).height, 2)
        self.assertEqual(pill_bar(29, T), Bar("dry", 2))


class PillTests(unittest.TestCase):
    def test_pill_rain_coming(self):
        reading = pill(COMING)
        self.assertEqual((reading.state, reading.time), ("rain-coming", "15:00"))
        self.assertEqual(
            [(b.level, b.height) for b in reading.bars],
            [("dry", 2), ("dry", 2), ("wet", 9), ("heavy", 12), ("wet", 8), ("wet", 5)],
        )

    def test_pill_rain_this_hour_says_now(self):
        self.assertEqual(pill(rain(13, [70, 60, 20])).time, "now")

    def test_pill_raining_shows_the_stop(self):
        reading = pill(RAINING, at(16, 20), raining=True)
        self.assertEqual((reading.state, reading.time), ("raining", "19:00"))

    def test_pill_raining_without_a_dry_hour_shows_no_time(self):
        self.assertEqual(pill(rain(13, [80] * 30), raining=True).time, "")

    def test_pill_dry(self):
        reading = pill(DRY)
        self.assertEqual((reading.state, reading.time), ("dry", ""))

    def test_pill_none(self):
        reading = pill_reading(None, False, at(13, 10), T, 6)
        self.assertEqual((reading.state, reading.time), ("none", ""))
        self.assertEqual(reading.bars, (Bar("none", 2),) * 6)

    def test_pill_pads_missing_hours_as_absent(self):
        now = at(13, 10)
        reading = pill_reading(hours(COMING, now)[:3], False, now, T, 6)
        self.assertEqual(reading.bars[3:], (Bar("none", 2),) * 3)


class HeroTests(unittest.TestCase):
    def test_hero_coming(self):
        self.assertEqual(hero(COMING), ("coming", "Rain starts", "15:00", "Heaviest around 16:00, clears by 19:00"))

    def test_hero_coming_now(self):
        self.assertEqual(
            hero(rain(13, [70, 60, 20])),
            ("coming-now", "Rain likely", "Now", "70% chance this hour, clears by 15:00"),
        )

    def test_hero_raining(self):
        self.assertEqual(
            hero(RAINING, at(16, 20), raining=True),
            ("raining", "Rain stops around", "19:00", "Heaviest now, lighter after 17:00"),
        )

    def test_hero_raining_on(self):
        self.assertEqual(
            hero(rain(13, [80] * 30), raining=True),
            ("raining-on", "Rain continues past", "01:00", "Heaviest now"),
        )

    def test_hero_dry(self):
        self.assertEqual(hero(DRY), ("dry", "Next 12 hours", "Dry", "Highest chance is 15%, at 16:00"))

    def test_hero_dry_zero(self):
        self.assertEqual(hero({})[3], "No rain expected")

    def test_hero_none(self):
        h = hero_reading(None, False, at(13, 10), T, 12)
        self.assertEqual(
            (h.state, h.label, h.figure, h.line),
            ("none", "Next 12 hours", "No forecast", "Can't reach WeatherAPI. Trying again every minute."),
        )

    def test_coming_peak_is_in_the_first_spell(self):
        """Two showers: the line speaks of the one that starts, not "heaviest at 22, clears by 17"."""
        chances = rain(13, [10, 25, 70, 60, 10, 10, 10, 10, 10, 90, 90, 10])
        self.assertEqual(hero(chances)[3], "Heaviest around 15:00, clears by 17:00")

    def test_raining_lighter_after_stops_at_the_stop(self):
        """Lighter after the hour it stops says nothing; a line ends at the stop."""
        self.assertEqual(
            hero(rain(13, [40, 20, 10, 5]), raining=True),
            ("raining", "Rain stops around", "14:00", "Heaviest now"),
        )

    def test_wet_hour_beyond_the_window_is_dry(self):
        chances = rain(13 + 14, [90])
        self.assertEqual(hero(chances)[0], "dry")
        self.assertEqual(pill(chances).state, "dry")


class DayTests(unittest.TestCase):
    def test_day_blocks_take_the_highest_chance(self):
        day = forecast(rain(48 + 14, [40, 40, 40])).days[2]
        blocks = day_blocks(day, JAKARTA, T)
        self.assertEqual([b.level for b in blocks], ["dry"] * 4 + ["wet", "wet"] + ["dry"] * 2)
        self.assertEqual([b.height for b in blocks], [2, 2, 2, 2, 6, 6, 2, 2])

    def test_day_text(self):
        self.assertEqual(day_text(forecast().days[1], JAKARTA, T), "Mostly dry")
        self.assertEqual(day_text(forecast(rain(24 + 6, [50] * 12)).days[1], JAKARTA, T), "Rain most of the day")
        self.assertEqual(day_text(forecast(rain(48 + 14, [40, 40, 40])).days[2], JAKARTA, T), "Rain from 14:00")


if __name__ == "__main__":
    unittest.main()

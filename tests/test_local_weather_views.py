"""Tests for the pill's and card's view models: placeholders, the header line, freshness, the day
rows and the sky's input, all at fixed Jakarta times."""

import unittest

from local_weather_payloads import at, forecast, rain

from core.utils.widgets.local_weather.location import Place
from core.utils.widgets.local_weather.rain import Bar, Thresholds
from core.utils.widgets.local_weather.views import SkyInput, card_view, header_line, pill_view

T = Thresholds()
CONFIG = "Example Town"
PLACE = Place("-6.18,106.63", "windows", "")
COMING = rain(13, [10, 25, 70, 95])


def pill(f, now):
    return pill_view(f, CONFIG, now, T, 6)


def card(f, now, place=PLACE):
    return card_view(f, place, CONFIG, now, T, 12)


class PillViewTests(unittest.TestCase):
    def test_pill_view_coming(self):
        view = pill(forecast(COMING), at(13, 20))
        self.assertEqual(view.condition, "cloud")
        self.assertEqual(view.reading.time, "15:00")
        self.assertEqual(
            view.placeholders,
            {
                "{temp}": "32°",
                "{feels}": "38°",
                "{location}": "Rajeg",
                "{min_temp}": "24°",
                "{max_temp}": "32°",
                "{condition}": "Cloudy",
            },
        )

    def test_pill_view_without_forecast(self):
        view = pill(None, at(13, 10))
        self.assertEqual((view.condition, view.icon_key, view.reading.state), ("none", "default", "none"))
        self.assertEqual(view.placeholders["{temp}"], "—")
        self.assertEqual(view.placeholders["{location}"], CONFIG)

    def test_forecast_older_than_three_hours_reads_as_no_forecast(self):
        f = forecast(COMING)
        self.assertEqual(pill(f, at(16, 11)).reading.state, "none")
        old = card(f, at(16, 11))
        self.assertEqual(old.hero.state, "none")
        self.assertEqual((old.line, old.line_state), ("Last forecast 13:10", ""))
        self.assertEqual((old.title, old.temp), ("Rajeg", "—"))
        self.assertEqual(pill(f, at(16, 10)).reading.state, "rain-coming")

    def test_hour_rollover_moves_the_first_bar(self):
        f = forecast(rain(14, [70]))
        before = pill(f, at(13, 59)).reading
        self.assertEqual((before.bars[1].level, before.time), ("wet", "14:00"))
        after = pill(f, at(14, 0)).reading
        self.assertEqual((after.bars[0].level, after.time), ("wet", "now"))
        axis = card(f, at(14, 0)).axis
        self.assertEqual((axis[0], axis[2]), ("now", "16"))


class HeaderLineTests(unittest.TestCase):
    def test_header_lines(self):
        f = forecast(COMING)
        cases = [
            ("normal", f, PLACE, at(13, 20), ("Windows location, updated 13:10", "")),
            ("stale", f, PLACE, at(13, 41), ("Windows location, updated 13:10", "stale")),
            (
                "off",
                f,
                Place(CONFIG, "config", "off"),
                at(13, 20),
                ("From your config, Windows location is off", "warn"),
            ),
            ("no fix", f, Place(CONFIG, "config", "no_fix"), at(13, 20), ("From your config, no location fix", "warn")),
            ("expired", f, PLACE, at(16, 11), ("Last forecast 13:10", "")),
            ("never", None, None, at(13, 20), ("No forecast yet", "")),
        ]
        for name, fc, place, now, expected in cases:
            with self.subTest(name):
                self.assertEqual(header_line(fc, place, now), expected)


class CardViewTests(unittest.TestCase):
    def test_card_view_coming(self):
        view = card(forecast(COMING), at(13, 20))
        self.assertEqual((view.title, view.feels, view.hero.state), ("Rajeg", "feels 38°", "coming"))
        self.assertEqual(len(view.bars), 12)
        self.assertEqual(view.bars[2], Bar("wet", 41, "70%"))
        self.assertEqual(view.axis[:4], ("now", "", "15", ""))
        self.assertEqual([d.name for d in view.days], ["Tomorrow", "Wednesday"])
        self.assertEqual(view.days[0].range, "24–32°")
        self.assertEqual(view.sky, SkyInput(2, 9.0, 32.4, -6.18, 106.63, at(13, 10).timestamp()))

    def test_card_view_alert(self):
        view = card(forecast(COMING, alerts=("Flood warning for Tangerang",)), at(13, 20))
        self.assertEqual(view.alert, "Flood warning for Tangerang")

    def test_card_view_without_forecast(self):
        view = card_view(None, None, CONFIG, at(13, 10), T, 12)
        self.assertEqual(
            (view.title, view.line, view.temp, view.feels, view.hero.state),
            (CONFIG, "No forecast yet", "—", "", "none"),
        )
        self.assertEqual(view.bars, (Bar("none", 3),) * 12)
        self.assertEqual((view.days, view.sky, view.condition), ((), None, "none"))


if __name__ == "__main__":
    unittest.main()

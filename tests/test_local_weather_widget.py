"""Widget-level tests for the Local Weather pill: its options, its state classes, the strip and the
time, the alternate label, and the card it builds. No fetcher runs (no API key), so nothing here
looks the laptop up or calls WeatherAPI."""

import unittest

from local_weather_payloads import at, payload, rain
from pydantic import ValidationError
from PyQt6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from core.utils.widgets.local_weather.location import Place  # noqa: E402
from core.validation.widgets.yasb.local_weather import LocalWeatherConfig  # noqa: E402
from core.widgets.yasb.local_weather import LocalWeatherWidget  # noqa: E402

CONFIG = "Example Town"
PLACE = Place("-6.18,106.63", "windows", "")
COMING = rain(13, [10, 25, 70, 95, 60, 35])


def classes(widget) -> list[str]:
    return (widget.property("class") or "").split()


class OptionsTests(unittest.TestCase):
    def test_options_defaults_and_bounds(self):
        config = LocalWeatherConfig(location=CONFIG)
        rain_options = config.rain
        self.assertEqual(
            (
                rain_options.wet_threshold,
                rain_options.heavy_threshold,
                rain_options.pill_hours,
                rain_options.card_hours,
            ),
            (30, 80, 6, 12),
        )
        self.assertEqual((config.api_key, config.update_interval), ("env", 600))
        with self.assertRaises(ValidationError):
            LocalWeatherConfig(location=CONFIG, rain={"wet_threshold": 30, "heavy_threshold": 20})
        with self.assertRaises(ValidationError):
            LocalWeatherConfig()
        with self.assertRaises(ValidationError):
            LocalWeatherConfig(location=CONFIG, show_hourly_forecast=True)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        config = LocalWeatherConfig(
            api_key="", location=CONFIG, label="<span>{icon}</span> {temp}", label_alt="{location}"
        )
        self.widget = LocalWeatherWidget(config)
        self.widget._now = lambda: at(13, 10)

    def tearDown(self):
        self.widget._minute_timer.stop()
        self.widget.deleteLater()

    def container(self) -> list[str]:
        return classes(self.widget._widget_container)

    def test_starts_as_no_forecast(self):
        self.widget._render()
        self.assertIn("none", self.container())
        self.assertTrue(self.widget._time.isHidden())
        self.assertEqual({b.level for b in self.widget._strip.bars}, {"none"})
        self.assertEqual(self.widget._widgets[1].text(), "—")

    def test_rain_coming_pill(self):
        self.widget._on_forecast(payload(COMING), PLACE)
        self.assertTrue({"cloud", "rain-coming"} <= set(self.container()))
        self.assertEqual(self.widget._time.text(), "15:00")
        self.assertFalse(self.widget._time.isHidden())
        self.assertEqual(self.widget._widgets[0].text(), self.widget.config.icons.cloudyDay)
        self.assertEqual(self.widget._widgets[1].text(), "32°")

    def test_raining_pill(self):
        self.widget._on_forecast(payload(rain(13, [95, 60, 20]), code=1189, precip=1.2), PLACE)
        self.assertTrue({"rain", "raining"} <= set(self.container()))
        self.assertEqual(self.widget._time.text(), "15:00")

    def test_alt_label_keeps_strip_and_time(self):
        self.widget._on_forecast(payload(COMING), PLACE)
        self.widget._toggle_label()
        self.assertFalse(self.widget._widgets_alt[0].isHidden())
        self.assertEqual(self.widget._widgets_alt[0].text(), "Rajeg")
        self.assertTrue(all(w.isHidden() for w in self.widget._widgets))
        self.assertFalse(self.widget._strip.isHidden())
        self.assertFalse(self.widget._time.isHidden())

    def test_failed_fetch_keeps_the_last_forecast(self):
        self.widget._on_forecast(payload(COMING), PLACE)
        self.widget._now = lambda: at(13, 20)
        self.widget._on_failed(PLACE)
        self.assertIn("rain-coming", self.container())
        self.assertEqual(self.widget._time.text(), "15:00")

    def test_build_card_reflects_the_forecast(self):
        self.widget._on_forecast(payload(COMING), PLACE)
        card = self.widget._build_card()
        try:
            self.assertIn("coming", classes(card._hero))
        finally:
            card.deleteLater()


if __name__ == "__main__":
    unittest.main()

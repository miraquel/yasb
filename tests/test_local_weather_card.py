"""Widget-level tests for the weather card: its sections, the hero in each state, what hides with
no forecast, the header line's state and the axis. Filled offscreen; no popup is shown."""

import unittest

from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from tests.support.local_weather import at, first_ink, forecast, rain

APP = QApplication.instance() or QApplication([])

from core.utils.widgets.local_weather.bars import RainBars  # noqa: E402
from core.utils.widgets.local_weather.card import WeatherCard  # noqa: E402
from core.utils.widgets.local_weather.location import Place  # noqa: E402
from core.utils.widgets.local_weather.rain import Thresholds  # noqa: E402
from core.utils.widgets.local_weather.views import card_view  # noqa: E402
from core.validation.widgets.yasb.weather import WeatherIconsConfig  # noqa: E402

T = Thresholds()
CONFIG = "Example Town"
PLACE = Place("-6.18,106.63", "windows", "")
ICONS = WeatherIconsConfig().model_dump()

HEROES = {
    "coming": (rain(13, [10, 25, 70, 95, 60, 35, 20, 15, 10, 10, 5, 5]), at(13, 10), {}),
    "coming-now": (rain(13, [70, 60, 20]), at(13, 10), {}),
    "raining": (rain(16, [95, 60, 35, 20, 15]), at(16, 20), {"code": 1189, "precip": 1.2}),
    "raining-on": (rain(13, [80] * 30), at(13, 10), {"code": 1195, "precip": 2.0}),
    "dry": (rain(13, [5, 10, 10, 15, 10, 5, 5, 5, 10, 10, 5, 5]), at(13, 10), {}),
}


def view_for(state, place=PLACE, **extra):
    if state == "none":
        return card_view(None, None, CONFIG, at(13, 10), T, 12)
    chances, now, kw = HEROES[state]
    return card_view(forecast(chances, fetched=now, **kw, **extra), place, CONFIG, now, T, 12)


def classes(widget: QWidget) -> list[str]:
    return (widget.property("class") or "").split()


def by_class(root: QWidget, cls: str) -> QWidget:
    for child in root.findChildren(QWidget):
        if cls in classes(child):
            return child
    raise AssertionError(f"no descendant with class {cls!r}")


def all_by_class(root: QWidget, cls: str) -> list[QWidget]:
    return [child for child in root.findChildren(QWidget) if cls in classes(child)]


class CardTests(unittest.TestCase):
    def setUp(self):
        self.card = WeatherCard(ICONS, card_hours=12)

    def tearDown(self):
        self.card.deleteLater()

    def test_sections_are_frames(self):
        self.card.set_view(view_for("coming"))
        for cls in ("header", "hero", "days"):
            with self.subTest(section=cls):
                self.assertIsInstance(by_class(self.card, cls), QFrame)
        self.assertIsInstance(by_class(self.card, "hour-bars"), RainBars)

    def test_hero_states_set_class_and_text(self):
        for state in (*HEROES, "none"):
            with self.subTest(state=state):
                view = view_for(state)
                self.card.set_view(view)
                self.assertIn(state, classes(by_class(self.card, "hero")))
                texts = tuple(by_class(self.card, c).text() for c in ("hero-label", "hero-figure", "hero-line"))
                self.assertEqual(texts, (view.hero.label, view.hero.figure, view.hero.line))

    def test_no_forecast_hides_sky_and_days(self):
        self.card.set_view(view_for("none"))
        self.assertTrue(self.card.sky.isHidden())
        self.assertTrue(by_class(self.card, "days").isHidden())
        self.assertEqual({b.level for b in by_class(self.card, "hour-bars").bars}, {"none"})
        self.assertIn("none", classes(by_class(self.card, "temp")))

    def test_forecast_shows_sky_and_days(self):
        self.card.set_view(view_for("coming"))
        self.assertFalse(self.card.sky.isHidden())
        self.assertEqual(len(all_by_class(self.card, "day")), 2)
        self.assertEqual(self.card.sky.model.weather.code, 2)

    def test_alert_line_shows_only_with_an_alert(self):
        self.card.set_view(view_for("coming"))
        self.assertTrue(by_class(self.card, "hero-alert").isHidden())
        self.card.set_view(view_for("coming", alerts=("Flood warning for Tangerang",)))
        alert = by_class(self.card, "hero-alert")
        self.assertFalse(alert.isHidden())
        self.assertEqual(alert.text(), "Flood warning for Tangerang")

    def test_padded_labels_start_on_the_left_edge(self):
        """The alert and the header line have top padding, which made Qt indent them by ~3px."""
        self.card.set_view(view_for("coming", alerts=("Flood warning for Tangerang",)))
        for cls in ("hero-alert", "line"):
            with self.subTest(label=cls):
                label = by_class(self.card, cls)
                label.setStyleSheet("padding-top: 2px; color: #ffffff; background-color: #000000;")
                label.resize(300, 24)
                plain = QLabel(label.text())
                plain.setFont(label.font())
                plain.setIndent(0)
                plain.setStyleSheet("color: #ffffff; background-color: #000000;")
                plain.resize(300, 24)
                self.assertEqual(first_ink(label), first_ink(plain))

    def test_header_line_state_class(self):
        self.card.set_view(view_for("coming", place=Place(CONFIG, "config", "off")))
        line = by_class(self.card, "line")
        self.assertIn("warn", classes(line))
        self.assertEqual(line.text(), "From your config, Windows location is off")

    def test_axis_ticks(self):
        self.card.set_view(view_for("coming"))
        ticks = [w for w in all_by_class(self.card, "tick") if isinstance(w, QLabel)]
        self.assertEqual(len(ticks), 12)
        self.assertEqual([t.text() for t in ticks[:4]], ["now", "", "15", ""])
        self.assertIn("now", classes(ticks[0]))

    def test_set_view_keeps_the_same_sky(self):
        self.card.set_view(view_for("coming"))
        sky = self.card.sky
        self.card.set_view(view_for("dry"))
        self.assertIs(self.card.sky, sky)


if __name__ == "__main__":
    unittest.main()

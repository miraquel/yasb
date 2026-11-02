"""Tests for the painted rain bars and the sky's opt-in left and bottom fades, rendered offscreen
and read back pixel by pixel."""

import unittest

import local_weather_payloads  # noqa: F401  (puts src on sys.path)
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from core.utils.widgets.ai_usage.scene import SkyScene  # noqa: E402
from core.utils.widgets.local_weather.bars import RainBars  # noqa: E402
from core.utils.widgets.local_weather.rain import Bar  # noqa: E402

PILL = [Bar("wet", 13), Bar("dry", 2), Bar("heavy", 13), Bar("none", 2), Bar("wet", 4), Bar("dry", 2)]


def pixel(widget, x, y) -> str:
    return widget.grab().toImage().pixelColor(x, y).name()


class RainBarsTests(unittest.TestCase):
    def test_packed_size(self):
        bars = RainBars(6, 3, 2, 1, 13)
        self.assertEqual(bars.sizeHint(), QSize(28, 13))
        bars.setContentsMargins(8, 0, 0, 0)
        self.assertEqual(bars.sizeHint(), QSize(36, 13))

    def test_pill_bars_paint_their_levels(self):
        bars = RainBars(6, 3, 2, 1, 13)
        bars.set_bars(PILL)
        bars.resize(bars.sizeHint())
        self.assertEqual(bars.bars, tuple(PILL))
        self.assertEqual(pixel(bars, 1, 6), "#89dceb")
        self.assertEqual(pixel(bars, 6, 12), "#45475a")
        self.assertNotEqual(pixel(bars, 6, 5), "#45475a")
        self.assertEqual(pixel(bars, 11, 6), "#74c7ec")
        self.assertEqual(pixel(bars, 16, 12), "#6c7086")

    def test_colours_come_from_properties(self):
        bars = RainBars(6, 3, 2, 1, 13)
        bars.set_bars(PILL)
        bars.resize(bars.sizeHint())
        bars.setProperty("wetcolor", QColor("#ff0000"))
        self.assertEqual(pixel(bars, 1, 6), "#ff0000")


class SkyFadeTests(unittest.TestCase):
    def scene(self) -> SkyScene:
        sky = SkyScene()
        sky.resize(340, 150)
        sky.fxopacity = 0  # the gradient alone, so the fade is all that differs
        sky.edgefade = 0
        sky._tick()
        return sky

    def alpha(self, sky, x, y) -> int:
        return sky._image.pixelColor(x, y).alpha()

    def test_sky_left_fade(self):
        sky = self.scene()
        before, right = self.alpha(sky, 68, 10), self.alpha(sky, 306, 10)
        sky.leftfade = 75
        self.assertGreater(before, 0)
        self.assertTrue(0.25 < self.alpha(sky, 68, 10) / before < 0.34)
        self.assertEqual(self.alpha(sky, 306, 10), right)

    def test_sky_bottom_fade(self):
        sky = self.scene()
        low, high = self.alpha(sky, 170, 142), self.alpha(sky, 170, 30)
        sky.bottomfade = 40
        self.assertGreater(low, 0)
        self.assertLess(self.alpha(sky, 170, 142), 0.2 * low)
        self.assertEqual(self.alpha(sky, 170, 30), high)

    def test_sky_fades_default_off(self):
        sky = SkyScene()
        self.assertEqual((sky.leftfade, sky.bottomfade), (0, 0))


if __name__ == "__main__":
    unittest.main()

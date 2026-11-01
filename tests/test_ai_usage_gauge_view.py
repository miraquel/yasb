"""Tests for UsageGauge, the fill painted behind each half of the AI pill.

The gauge is rendered into a transparent image and sampled pixel by pixel, so what is checked is
what lands on screen: the fill's share and tint, its edge line, the bottom line and the clipped
corners. Nothing is ever shown.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QRegion  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.utils.widgets.ai_usage.gauge_view import UsageGauge  # noqa: E402

PEACH, YELLOW, RED, TEAL = (250, 179, 135), (249, 226, 175), (243, 139, 168), (148, 226, 213)

# Hosts and targets stay referenced here so Python never collects a gauge's parent mid-test.
_KEEP: dict[int, tuple[QFrame, QFrame]] = {}


def make(w: int = 100, h: int = 20, animate: bool = False) -> UsageGauge:
    host = QFrame()
    host.resize(w + 20, h + 10)
    target = QFrame(host)
    target.setGeometry(0, 0, w, h)
    gauge = UsageGauge(host, target, animate)
    _KEEP[id(gauge)] = (host, target)
    return gauge


def host_target(gauge: UsageGauge) -> QFrame:
    return _KEEP[id(gauge)][1]


def paint(gauge: UsageGauge) -> QImage:
    image = QImage(gauge.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    gauge.render(image, QPoint(), QRegion(), QWidget.RenderFlag(0))
    return image


def near(colour, rgb: tuple[int, int, int], alpha: int) -> bool:
    return (
        all(abs(a - b) <= 6 for a, b in zip((colour.red(), colour.green(), colour.blue()), rgb, strict=True))
        and abs(colour.alpha() - alpha) <= 3
    )


class FillTest(unittest.TestCase):
    def test_fill_covers_its_share(self):
        g = make()
        g.set_reading(40, "low", None, None)
        img = paint(g)
        self.assertTrue(near(img.pixelColor(20, 10), PEACH, 51), img.pixelColor(20, 10).getRgb())
        self.assertEqual(img.pixelColor(60, 10).alpha(), 0)

    def test_edge_marks_the_level_and_vanishes_when_full(self):
        g = make()
        g.set_reading(40, "low", None, None)
        img = paint(g)
        self.assertGreater(img.pixelColor(39, 10).alpha(), img.pixelColor(20, 10).alpha())
        g.set_reading(100, "low", None, None)
        img = paint(g)
        self.assertEqual(img.pixelColor(98, 10).alpha(), img.pixelColor(50, 10).alpha())

    def test_steps_use_their_hue_and_opacity(self):
        g = make()
        g.set_reading(70, "medium", None, None)
        self.assertTrue(near(paint(g).pixelColor(20, 10), YELLOW, 61))
        g.set_reading(90, "high", None, None)
        self.assertTrue(near(paint(g).pixelColor(20, 10), RED, 77))

    def test_line_runs_along_the_bottom(self):
        g = make()
        g.set_reading(15, "low", 97, "high")
        img = paint(g)
        self.assertTrue(near(img.pixelColor(50, 19), RED, 255))
        self.assertTrue(near(img.pixelColor(50, 18), RED, 255))
        self.assertEqual(img.pixelColor(50, 17).alpha(), 0)  # past the 15% fill, above the line
        self.assertEqual(img.pixelColor(98, 19).alpha(), 0)  # past 97%

    def test_no_reading_paints_nothing(self):
        g = make()
        g.set_reading(None, None, None, None)
        img = paint(g)
        self.assertTrue(all(img.pixelColor(x, y).alpha() == 0 for x in (0, 50, 99) for y in (0, 10, 19)))


class ShapeAndStyleTest(unittest.TestCase):
    def test_corners_are_clipped(self):
        g = make()
        g.setStyleSheet("qproperty-leftradius: 8; qproperty-rightradius: 0;")
        g.set_reading(100, "low", None, None)
        img = paint(g)
        self.assertEqual(img.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(img.pixelColor(0, 10).alpha(), 0)
        self.assertGreater(img.pixelColor(99, 0).alpha(), 0)

    def test_stylesheet_sets_the_look(self):
        g = make()
        g.parentWidget().setStyleSheet(".gauge { qproperty-lowcolor: #94e2d5; qproperty-lowalpha: 50; }")
        g.ensurePolished()
        g.set_reading(40, "low", None, None)
        self.assertTrue(near(paint(g).pixelColor(20, 10), TEAL, 128), paint(g).pixelColor(20, 10).getRgb())


class GeometryAndMotionTest(unittest.TestCase):
    def test_follows_the_target_and_sits_beneath_it(self):
        # A half widens when its sessions badge appears; the fill must follow at once.
        g = make()
        host, target = g.parentWidget(), host_target(g)
        # Qt holds back move/resize events for a widget never shown, as the bar's never are.
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        host.show()
        target.setGeometry(4, 0, 160, 20)
        QApplication.processEvents()
        self.assertEqual(g.geometry(), target.geometry())
        self.assertLess(host.children().index(g), host.children().index(target))
        self.assertTrue(g.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_animates_to_a_new_reading(self):
        g = make(animate=True)
        g.set_reading(80, "medium", None, None)
        self.assertLess(g.property("fillshare"), 80)
        QTest.qWait(500)
        self.assertEqual(g.property("fillshare"), 80)
        self.assertEqual(g.reading(), (80, "medium", None, None))


if __name__ == "__main__":
    unittest.main()

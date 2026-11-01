"""Tests for the AI pill's fill gauge model: which window drives the fill, its colour step and its share.

Qt-free, so it runs without a bar. The rule under test is the week takeover the owner picked: the
short window drives until the long one reaches crit_percent.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.widgets.ai_usage.gauge import GaugeReading, GaugeWindow, pick, share, step  # noqa: E402

H5, D7 = "5h", "7d"
w = GaugeWindow


class PickTest(unittest.TestCase):
    def test_short_drives_below_crit(self):
        r = pick(w(H5, 15), w(D7, 72), 85)
        self.assertEqual((r.fill.name, r.line.name, r.prefix), ("5h", "7d", ""))

    def test_long_takes_over_at_crit(self):
        self.assertEqual(pick(w(H5, 15), w(D7, 85), 85).fill.name, "7d")
        r = pick(w(H5, 15), w(D7, 97), 85)
        self.assertEqual((r.fill.used, r.line.used, r.prefix), (97, 15, "7d"))

    def test_both_hot_shows_the_week(self):
        self.assertEqual(pick(w(H5, 88), w(D7, 90), 85).fill.name, "7d")

    def test_swapped_shows_the_other_window(self):
        r = pick(w(H5, 23), w(D7, 41), 85, swapped=True)
        self.assertEqual((r.fill.name, r.line.name, r.prefix), ("7d", "5h", "7d"))
        r = pick(w(H5, 15), w(D7, 97), 85, swapped=True)
        self.assertEqual((r.fill.name, r.line.name, r.prefix), ("5h", "7d", ""))

    def test_long_without_reading_never_takes_over(self):
        r = pick(w(H5, 15), w(D7, None), 85)
        self.assertEqual((r.fill.name, r.line.used), ("5h", None))

    def test_lone_window_drives_and_ignores_swap(self):
        for swapped in (False, True):
            r = pick(w("1w", 47), None, 85, swapped=swapped)
            self.assertEqual((r.fill.name, r.line, r.prefix), ("1w", None, ""), swapped)

    def test_no_windows(self):
        self.assertEqual(pick(None, None, 85), GaugeReading(None, None, ""))


class StepAndShareTest(unittest.TestCase):
    def test_step(self):
        self.assertEqual(
            [step(u, 60, 85) for u in (0, 59, 60, 84, 85, 104, None)],
            ["low", "low", "medium", "medium", "high", "high", None],
        )

    def test_share(self):
        self.assertEqual((share(30, "used"), share(30, "remaining")), (30, 70))
        # The endpoint can report more than 100% used; the fill must stay inside its half.
        self.assertEqual((share(104, "used"), share(104, "remaining")), (100, 0))
        self.assertEqual((share(-3, "used"), share(None, "used"), share(None, "remaining")), (0, None, None))


if __name__ == "__main__":
    unittest.main()

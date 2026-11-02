"""Tests for where the forecast is for: a fresh Windows fix, the last one while under two hours old,
then the config address. Coordinates never reach a log record above DEBUG."""

import logging
import unittest

from core.utils.widgets.local_weather.location import Fix, LocationTracker, Place

CONFIG = "Example Town"
FIX = (-6.17834, 106.63191)
WINDOWS = Place("-6.18,106.63", "windows", "")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = LocationTracker(CONFIG)

    def test_fresh_fix_is_rounded_and_kept(self):
        self.assertEqual(self.tracker.resolve(FIX, 1000.0), WINDOWS)
        self.assertEqual(self.tracker.last, Fix(-6.18, 106.63, 1000.0))

    def test_failed_lookup_reuses_a_recent_fix(self):
        self.tracker.resolve(FIX, 0.0)
        self.assertEqual(self.tracker.resolve("no_fix", 3600.0), WINDOWS)

    def test_fix_older_than_two_hours_falls_back(self):
        self.tracker.resolve(FIX, 0.0)
        self.assertEqual(self.tracker.resolve("off", 7201.0), Place(CONFIG, "config", "off"))

    def test_no_fix_ever_falls_back_with_reason(self):
        self.assertEqual(self.tracker.resolve("no_fix", 0.0).reason, "no_fix")

    def test_location_turned_off_drops_the_last_fix(self):
        """Reuse covers a lookup that failed, not one the user switched off."""
        self.tracker.resolve(FIX, 0.0)
        self.assertEqual(self.tracker.resolve("off", 600.0), Place(CONFIG, "config", "off"))
        self.assertIsNone(self.tracker.last)

    def test_coordinates_never_logged(self):
        """Not even at DEBUG: with `debug: true` that record would land in yasb.log, on disk."""
        with self.assertLogs(level="DEBUG") as cm:
            self.tracker.resolve(FIX, 0.0)
            self.tracker.resolve("no_fix", 600.0)
            self.tracker.resolve("off", 3 * 3600.0)
        self.assertTrue(any(r.levelno > logging.DEBUG for r in cm.records), "the fallback should be logged")
        self.assertTrue(any(r.levelno == logging.DEBUG for r in cm.records))
        for record in cm.records:
            self.assertNotIn("-6.1", record.getMessage())
            self.assertNotIn("106.6", record.getMessage())


if __name__ == "__main__":
    unittest.main()

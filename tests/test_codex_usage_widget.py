"""Tests for the Codex usage widget's config defaults and its Qt-free helpers.

The widget itself needs a running bar, so only what can be checked without one is here: the
traffic-light level for a share used, and that every new option stays off by default so existing
configs render exactly as before.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.validation.widgets.yasb.codex_usage import CodexUsageConfig  # noqa: E402
from core.widgets.yasb.codex_usage import level_class  # noqa: E402


class LevelClassTest(unittest.TestCase):
    def test_defaults_keep_the_old_split(self):
        # The old rule, on the share remaining: 20 or less critical, 50 or less low.
        for used, expected in ((49, "good"), (50, "low"), (79, "low"), (80, "critical"), (None, "unknown")):
            self.assertEqual(level_class(used, 50, 80), expected, used)

    def test_owner_thresholds(self):
        self.assertEqual([level_class(u, 60, 85) for u in (59, 60, 84, 85)], ["good", "low", "low", "critical"])

    def test_new_options_default_off(self):
        config = CodexUsageConfig()
        self.assertFalse(config.hearts.enabled or config.footer.enabled)
        self.assertIsNone(config.progress_bar.level_colors)
        self.assertEqual((config.warn_percent, config.crit_percent), (50, 80))


if __name__ == "__main__":
    unittest.main()

"""Widget-level tests for the AI pill's fill gauge on the Claude and Codex usage widgets.

Each widget is built with its usage service swapped for a fake that hands over a fixed reading, so
no network, CLI or bar is involved. What is checked is what the pill shows: the number, its prefix,
its level class, and the reading handed to the gauge painter.
"""

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.validation.widgets.yasb.claude_usage import ClaudeUsageConfig  # noqa: E402
from core.validation.widgets.yasb.codex_usage import CodexUsageConfig  # noqa: E402
from core.widgets.yasb import claude_usage as claude_module  # noqa: E402
from core.widgets.yasb import codex_usage as codex_module  # noqa: E402

LABEL = "<span class='window'>{gauge_window}</span>{gauge_value}%"
LABEL_ALT = "<span class='window'>{gauge_window}</span>{gauge_value}% {mode}"


class FakeService(QObject):
    data_ready = pyqtSignal(dict)

    def __init__(self, data: dict[str, Any]):
        super().__init__()
        self._data = data

    def latest(self) -> dict[str, Any]:
        return dict(self._data)

    def release(self) -> None:
        pass

    def refresh_now(self) -> None:
        pass


def cls(label: QLabel) -> set[str]:
    return set((label.property("class") or "").split())


def claude(data: dict[str, Any], **opts):
    options: dict[str, Any] = {
        "show_account": False,
        "warn_percent": 60,
        "crit_percent": 85,
        "usage_mode": "used",
        "label": LABEL,
        "label_alt": LABEL_ALT,
        "gauge": {"enabled": True, "animation": False},
    }
    options.update(opts)
    with patch.object(claude_module.ClaudeUsageService, "get_instance", return_value=FakeService(data)):
        return claude_module.ClaudeUsageWidget(ClaudeUsageConfig(**options))


def codex(data: dict[str, Any], **opts):
    options: dict[str, Any] = {
        "show_account": False,
        "warn_percent": 60,
        "crit_percent": 85,
        "usage_mode": "used",
        "label": LABEL,
        "label_alt": LABEL_ALT,
        "gauge": {"enabled": True, "animation": False},
    }
    options.update(opts)
    with patch.object(codex_module.CodexUsageService, "get_instance", return_value=FakeService(data)):
        return codex_module.CodexUsageWidget(CodexUsageConfig(**options))


# The only window this plan's Codex account reports: weekly, no secondary.
WEEK = {"used": 47, "remaining": 53, "duration_mins": 10080, "resets_at": None}
# Reset times on either side of now, for readings that have and have not outlived their window.
PAST, FUTURE = "2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"


class ClaudeGaugeTest(unittest.TestCase):
    def test_gauge_off_by_default(self):
        self.assertFalse(ClaudeUsageConfig().gauge.enabled)
        self.assertIsNone(claude({"five": 23, "seven": 41}, gauge={"enabled": False})._gauge)

    def test_short_window_drives(self):
        w = claude({"five": 23, "seven": 41})
        win, num = w._widgets
        self.assertEqual((win.isHidden(), num.text()), (True, "23%"))
        self.assertTrue(cls(num) >= {"label", "low"}, cls(num))
        self.assertEqual(w._gauge.reading(), (23, "low", 41, "low"))

    def test_week_takes_over_with_prefix_and_red(self):
        w = claude({"five": 15, "seven": 97})
        win, num = w._widgets
        self.assertEqual((win.text(), num.text()), ("7d", "97%"))
        self.assertIn("high", cls(num))
        self.assertEqual(w._gauge.reading(), (97, "high", 15, "low"))

    def test_model_caps_never_take_over(self):
        w = claude({"five": 20, "seven": 40, "scoped": [{"name": "Fable", "value": 97}]})
        self.assertEqual(w._widgets[1].text(), "20%")
        self.assertEqual(w._gauge.reading()[0], 20)

    def test_right_click_shows_the_other_window(self):
        w = claude({"five": 23, "seven": 41})
        w._toggle_label()
        win, num = w._widgets_alt
        self.assertEqual((win.text(), num.text()), ("7d", "41% used"))
        self.assertEqual(w._gauge.reading(), (41, "low", 23, "low"))

    def test_left_mode_drains_but_keeps_consumption_colour(self):
        w = claude({"five": 15, "seven": 97})
        w._toggle_usage_mode()
        win, num = w._widgets
        self.assertEqual((win.text(), num.text()), ("7d", "3%"))
        self.assertIn("high", cls(num))
        self.assertEqual(w._gauge.reading(), (3, "high", 85, "low"))

    def test_no_reading_is_not_zero(self):
        w = claude({})
        num = w._widgets[1]
        self.assertEqual(num.text(), "--%")
        self.assertIn("unknown", cls(num))
        self.assertEqual(w._gauge.reading(), (None, None, None, None))

    def test_over_100_fills_but_keeps_the_number(self):
        w = claude({"five": 104, "seven": 50})
        self.assertEqual(w._widgets[1].text(), "104%")
        self.assertEqual(w._gauge.reading()[:2], (100, "high"))

    def test_window_past_its_reset_is_not_a_reading(self):
        # An expired token serves the cached record: its 5 hours reset long ago, its week has not.
        w = claude({"five": 90, "five_reset_iso": PAST, "seven": 40, "seven_reset_iso": FUTURE, "token_expired": True})
        num = w._widgets[1]
        self.assertEqual(num.text(), "--%")
        self.assertIn("unknown", cls(num))
        self.assertEqual(w._gauge.reading(), (None, None, 40, "low"))

    def test_new_data_updates_the_gauge(self):
        w = claude({"five": 23, "seven": 41})
        w._on_data({"five": 66, "seven": 52})
        self.assertEqual(w._gauge.reading(), (66, "medium", 52, "low"))


class CodexGaugeTest(unittest.TestCase):
    def test_codex_gauge_off_by_default(self):
        self.assertFalse(CodexUsageConfig().gauge.enabled)

    def test_codex_lone_window_drives_and_right_click_keeps_it(self):
        w = codex({"primary": WEEK, "secondary": None})
        win, num = w._widgets
        self.assertEqual((win.isHidden(), num.text()), (True, "47%"))
        self.assertIn("good", cls(num))
        self.assertEqual(w._gauge.reading(), (47, "low", None, None))
        w._toggle_label()
        win, num = w._widgets_alt
        self.assertEqual(num.text(), "47% used")
        self.assertEqual(w._gauge.reading(), (47, "low", None, None))

    def test_codex_pair_takes_over_by_duration(self):
        five = {"used": 20, "remaining": 80, "duration_mins": 300, "resets_at": None}
        week = {"used": 90, "remaining": 10, "duration_mins": 10080, "resets_at": None}
        w = codex({"primary": five, "secondary": week})
        win, num = w._widgets
        self.assertEqual((win.text(), num.text()), ("1w", "90%"))
        self.assertIn("critical", cls(num))
        self.assertEqual(w._gauge.reading(), (90, "high", 20, "low"))

    def test_codex_window_past_its_reset_is_not_a_reading(self):
        # A failed refresh serves the cached reading; once its window has reset it says nothing.
        w = codex(
            {"primary": dict(WEEK, used=95, remaining=5, resets_at=1_000_000.0), "secondary": None, "stale": True}
        )
        num = w._widgets[1]
        self.assertEqual(num.text(), "--%")
        self.assertIn("unknown", cls(num))
        self.assertEqual(w._gauge.reading(), (None, None, None, None))

    def test_codex_number_uses_its_own_level_names(self):
        w = codex({"primary": dict(WEEK, used=70, remaining=30), "secondary": None})
        self.assertIn("low", cls(w._widgets[1]))
        self.assertEqual(w._gauge.reading()[1], "medium")


if __name__ == "__main__":
    unittest.main()

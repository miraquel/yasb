# pyright: reportPrivateUsage=false

"""The Codex popup's pager, built for real and fed data the way the service does.

Nothing else opens this popup in tests, which is how an upstream type guard naming the old
previous/next buttons (gone since the tab strip replaced them) crashed every refresh unnoticed.
"""

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from core.validation.widgets.yasb.codex_usage import CodexUsageConfig  # noqa: E402
from core.widgets.services.codex_usage.codex_api import EMPTY_RECORD  # noqa: E402
from core.widgets.yasb import codex_usage  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


class FakeService(QObject):
    data_ready = pyqtSignal(dict)

    def __init__(self, data: dict[str, Any]):
        super().__init__()
        self.data = data

    def latest(self) -> dict[str, Any]:
        return self.data

    def refresh_now(self) -> None:
        pass

    def release(self) -> None:
        pass


def record(**changes: Any) -> dict[str, Any]:
    data = dict(EMPTY_RECORD)
    data.update(changes)
    return data


class PagerTests(unittest.TestCase):
    def build(self, data: dict[str, Any]) -> codex_usage.CodexUsageWidget:
        self.service = FakeService(data)
        with mock.patch.object(codex_usage.CodexUsageService, "get_instance", return_value=self.service):
            widget = codex_usage.CodexUsageWidget(CodexUsageConfig())
        self.addCleanup(widget.deleteLater)
        widget._menu = widget._build_menu()
        self.addCleanup(widget._menu.deleteLater)
        return widget

    def test_a_refresh_with_the_popup_built_keeps_the_tab_strip(self):
        widget = self.build(record())
        # Called directly, not emitted: an exception in a slot aborts the whole test process.
        widget._on_data(record(reset_credits={"available_count": 1, "credits": []}))

        self.assertEqual(widget._visible_pages, ["overview", "resets"])
        self.assertEqual(list(widget._page_tabs), ["overview", "resets"])
        assert widget._page_navigation is not None
        self.assertFalse(widget._page_navigation.isHidden())
        self.assertEqual(widget._page_tabs["overview"].property("class"), "page-tab active")

    def test_choosing_a_tab_moves_the_active_mark(self):
        widget = self.build(record(reset_credits={"available_count": 0, "credits": []}))
        widget._sync_menu()

        widget._select_page("resets")

        self.assertEqual(widget._current_page, "resets")
        self.assertEqual(widget._page_tabs["resets"].property("class"), "page-tab active")
        self.assertEqual(widget._page_tabs["overview"].property("class"), "page-tab")

    def test_a_single_page_hides_the_tab_strip(self):
        widget = self.build(record())
        widget._on_data(record())

        self.assertEqual(widget._visible_pages, ["overview"])
        assert widget._page_navigation is not None
        self.assertTrue(widget._page_navigation.isHidden())

    def test_every_popup_label_sits_on_its_box_edge(self):
        widget = self.build(record())

        assert widget._menu is not None
        labels = widget._menu.findChildren(QLabel)
        self.assertTrue(labels)
        self.assertEqual([label for label in labels if label.indent() != 0], [])


if __name__ == "__main__":
    unittest.main()

"""Widget and service tests for anime airing: bar label states, the popup, and reminder toasts.

No network is touched: the widget gets a stub service, and the real service is built with
its fetch disabled and fed the schedule fixture directly. The popup body is filled into a
plain host frame, so no popup window is ever shown.
"""

import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

for root in (SRC_ROOT, PROJECT_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.validation.widgets.yasb.anime_airing import AnimeAiringConfig  # noqa: E402
from core.widgets.services.anime_airing import service as service_module  # noqa: E402
from core.widgets.services.anime_airing.service import AnimeAiringService, ReminderSettings  # noqa: E402
from core.widgets.yasb import anime_airing as widget_module  # noqa: E402
from core.widgets.yasb.anime_airing import AnimeAiringWidget  # noqa: E402
from tests.test_anime_airing_schedule import NOW, SNAPSHOT, at  # noqa: E402


class StubService(QObject):
    updated = pyqtSignal()

    def __init__(self, snapshot=None, loading=False, error_kind="", error_text=""):
        super().__init__()
        self.snapshot = snapshot
        self.loading = loading
        self.error_kind = error_kind
        self.error_text = error_text
        self.username = "miraquel"

    def refresh_now(self):
        pass

    def release(self):
        pass

    def test_reminder(self):
        pass


def by_class(root: QWidget, cls: str) -> list[QWidget]:
    return [child for child in root.findChildren(QWidget) if cls in (child.property("class") or "").split()]


class WidgetTestCase(unittest.TestCase):
    def make(self, stub: StubService, now=NOW, **options) -> AnimeAiringWidget:
        config = AnimeAiringConfig(username="miraquel", **options)
        with mock.patch.object(widget_module.AnimeAiringService, "get_instance", return_value=stub):
            widget = AnimeAiringWidget(config)
        widget._now = lambda: now
        widget._update_label()
        self.addCleanup(widget.deleteLater)
        return widget

    @staticmethod
    def texts(widget: AnimeAiringWidget, alt=False) -> list[str]:
        return [label.text() for label in (widget._widgets_alt if alt else widget._widgets)]


class LabelTests(WidgetTestCase):
    def test_counts_down_to_the_soonest_episode(self):
        widget = self.make(StubService(SNAPSHOT))
        self.assertEqual(self.texts(widget), ["", "Mushoku Tensei III… 1d 6h"])
        self.assertIn("unwatched", widget._widgets[1].property("class").split())

    def test_alt_label(self):
        widget = self.make(StubService(SNAPSHOT))
        widget._toggle_label()
        self.assertEqual(self.texts(widget, alt=True), ["", "Ep 14 · Tomorrow 18:00"])
        self.assertFalse(widget._widgets[1].isVisibleTo(widget))

    def test_soon(self):
        widget = self.make(StubService(SNAPSHOT), now=at(9, 27, 17, 30))
        self.assertEqual(self.texts(widget)[1], "Mushoku Tensei III… 30m")
        self.assertIn("soon", widget._widgets[1].property("class").split())

    def test_states_replace_the_template(self):
        cases = [
            (StubService(loading=True), "Loading...", "loading"),
            (StubService(error_kind="user", error_text="MyAnimeList user not found"), "User not found", "error"),
            (StubService(error_kind="network"), "Offline", "error"),
        ]
        for stub, text, state in cases:
            widget = self.make(stub)
            widget._toggle_label()
            self.assertEqual(self.texts(widget, alt=True), ["", text])
            self.assertIn(state, widget._widgets_alt[1].property("class").split())

    def test_nothing_airing(self):
        widget = self.make(StubService(SNAPSHOT), now=at(10, 20, 0))
        self.assertEqual(self.texts(widget), ["", "Nothing airing"])

    def test_title_limit_and_language(self):
        widget = self.make(StubService(SNAPSHOT), max_title_length=0, title_language="english")
        self.assertEqual(self.texts(widget)[1], "Mushoku Tensei: Jobless Reincarnation Season 3 1d 6h")


class PopupTests(WidgetTestCase):
    def fill(self, widget: AnimeAiringWidget) -> QFrame:
        host = QFrame()
        self.addCleanup(host.deleteLater)
        widget._fill_popup(QVBoxLayout(host))
        return host

    def test_hero_and_rows(self):
        widget = self.make(StubService(SNAPSHOT), menu={"show_covers": False})
        host = self.fill(widget)
        self.assertEqual(by_class(host, "hero-countdown")[0].text(), "1d 6h")
        self.assertEqual(by_class(host, "hero-meta")[0].text(), "Episode 14 · Tomorrow 18:00")
        self.assertEqual(by_class(host, "hero-unwatched")[0].text(), "1 episode to catch up on")
        rows = by_class(host, "show-row")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].property("class"), "show-row active unwatched")
        self.assertEqual(rows[0].url, "https://myanimelist.net/anime/59193")
        titles = [row.findChild(QLabel).text() for row in rows]
        self.assertEqual(titles[2], "JoJo SBR - 2nd & 3rd STAGE")
        badges = by_class(host, "show-unwatched")
        self.assertEqual([b.text() for b in badges], ["1 new", "", ""])

    def test_footer_says_how_fresh(self):
        widget = self.make(StubService(SNAPSHOT), now=NOW + timedelta(minutes=5))
        host = self.fill(widget)
        self.assertEqual(by_class(host, "status")[0].text(), "Updated 5m ago")

    def test_stale_footer(self):
        stub = StubService(SNAPSHOT, error_kind="network", error_text="AniList unreachable")
        host = self.fill(self.make(stub, now=NOW + timedelta(hours=2)))
        status = by_class(host, "status")[0]
        self.assertEqual(status.text(), "Offline · updated 2h ago")
        self.assertIn("stale", status.property("class").split())

    def test_error_placeholder(self):
        stub = StubService(error_kind="user", error_text="MyAnimeList user not found, or the list is private")
        host = self.fill(self.make(stub))
        self.assertEqual(by_class(host, "placeholder")[0].text(), "MyAnimeList user not found, or the list is private")
        self.assertEqual(by_class(host, "show-row"), [])

    def test_rows_update_in_place_then_rebuild_when_the_order_changes(self):
        widget = self.make(StubService(SNAPSHOT))
        host = self.fill(widget)
        first = by_class(host, "show-row")[0]
        widget._now = lambda: NOW + timedelta(minutes=1)
        widget._refresh_popup()
        self.assertIs(by_class(host, "show-row")[0], first)
        self.assertEqual(by_class(host, "hero-countdown")[0].text(), "1d 5h")
        widget._now = lambda: at(9, 27, 18, 1)
        widget._refresh_popup()
        APP.processEvents()
        rows = by_class(host, "show-row")
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_class(host, "hero-meta")[0].text(), "Episode 19 · Wed 20:00")


class CoverTests(unittest.TestCase):
    def test_cover_is_drawn_at_screen_density_with_rounded_corners(self):
        from PyQt6.QtGui import QColor, QPixmap

        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "cover.png")
            source = QPixmap(100, 142)
            source.fill(QColor("#c03030"))
            source.save(path)
            label = widget_module._CoverLabel(path, (30, 43, 3))
            pixmap = label.pixmap()
            dpr = label.devicePixelRatioF()
            self.assertEqual((pixmap.width(), pixmap.height()), (round(30 * dpr), round(43 * dpr)))
            self.assertEqual(pixmap.devicePixelRatio(), dpr)
            image = pixmap.toImage()
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(image.pixelColor(pixmap.width() // 2, pixmap.height() // 2).name(), "#c03030")
            label.deleteLater()

    def test_missing_cover_leaves_an_empty_slot(self):
        label = widget_module._CoverLabel(None, (30, 43, 3))
        self.assertTrue(label.pixmap().isNull())
        self.assertEqual((label.width(), label.height()), (30, 43))
        label.deleteLater()


class ServiceReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cache = Path(self.tmp.name) / "cache.json"
        self.toasts = []
        toaster = mock.Mock()
        toaster.return_value.show.side_effect = lambda icon, title, message, **kw: self.toasts.append(
            (title, message, kw["launch_url"])
        )
        for target, value in (
            ("cache_path", lambda username: cache),
            ("cover_path", lambda anilist_id, url: Path(self.tmp.name) / f"{anilist_id}.jpg"),
            ("ToastNotifier", toaster),
        ):
            patcher = mock.patch.object(service_module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        AnimeAiringService._instances.clear()

    def make(self, now, **reminders) -> AnimeAiringService:
        settings = ReminderSettings(**reminders)
        with mock.patch.object(AnimeAiringService, "refresh_now"):
            service = AnimeAiringService.get_instance("miraquel", ("watching",), 1800, settings)
        service._now = lambda: now
        self.addCleanup(service.release)
        return service

    def test_first_snapshot_replays_nothing(self):
        service = self.make(NOW, catch_up_hours=72)
        service._on_done(SNAPSHOT, "")
        self.assertEqual(self.toasts, [])

    def test_fires_once_at_broadcast_and_survives_a_restart(self):
        service = self.make(NOW)
        service._on_done(SNAPSHOT, "")
        service._now = lambda: at(9, 27, 18, 0)
        service._check_reminders()
        service._check_reminders()
        # '&' in a title would otherwise break the toast's XML.
        self.assertEqual(
            self.toasts,
            [
                (
                    "Mushoku Tensei III: Isekai Ittara Honki Dasu",
                    "Episode 14 is out now · 2 to catch up on",
                    "https://myanimelist.net/anime/59193",
                )
            ],
        )

        # A new process starts with no live services, only the cache file on disk.
        AnimeAiringService._instances.clear()
        restarted = self.make(at(9, 27, 18, 3))
        self.assertIsNot(restarted, service)
        self.assertIsNotNone(restarted.snapshot)
        restarted._check_reminders()
        self.assertEqual(len(self.toasts), 1)

    def test_titles_are_xml_escaped(self):
        service = self.make(NOW)
        service._on_done(SNAPSHOT, "")
        service._now = lambda: at(10, 2, 15, 0)
        service._check_reminders()
        self.assertIn("JoJo SBR - 2nd &amp; 3rd STAGE", [title for title, _, _ in self.toasts])

    def test_disabled(self):
        service = self.make(NOW, enabled=False)
        service._on_done(SNAPSHOT, "")
        service._now = lambda: at(9, 27, 18, 0)
        service._check_reminders()
        self.assertEqual(self.toasts, [])

    def test_retry_only_for_errors_that_can_clear(self):
        service = self.make(NOW)
        service._on_done(None, "user:MyAnimeList user not found")
        self.assertFalse(service._retry.isActive())
        self.assertEqual(service.error_kind, "user")
        service._on_done(None, "network:AniList unreachable")
        self.assertTrue(service._retry.isActive())

    def test_one_service_per_configuration(self):
        first = self.make(NOW)
        second = self.make(NOW)
        self.assertIs(first, second)
        self.assertEqual(first._refcount, 2)


if __name__ == "__main__":
    unittest.main()

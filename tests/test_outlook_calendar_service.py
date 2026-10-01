"""Tests for the shared Outlook calendar service: the cache, the snapshot states, and one
service shared by every bar. Polling is switched off and results are fed in directly."""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.widgets.services.outlook_calendar import service as service_module  # noqa: E402
from core.widgets.services.outlook_calendar.agenda import CalEvent, Snapshot  # noqa: E402
from core.widgets.services.outlook_calendar.outlook import OutlookNotRunning  # noqa: E402
from core.widgets.services.outlook_calendar.service import (  # noqa: E402
    OutlookCalendarService,
    load_cache,
    write_cache,
)

NOW = datetime(2026, 10, 1, 9, 0)
FETCHED = datetime(2026, 10, 1, 8, 12)
EVENT = CalEvent(start=datetime(2026, 10, 1, 14), end=datetime(2026, 10, 1, 15), subject="Weekly sync")


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name) / "outlook_calendar.json"
        patcher = mock.patch.object(OutlookCalendarService, "refresh_now")
        self.refresh = patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, cache_file: Path | None = None) -> OutlookCalendarService:
        service = OutlookCalendarService(7, 300, True, cache_file=cache_file or self.cache)
        service._now = lambda: NOW
        self.addCleanup(self.stop, service)
        return service

    @staticmethod
    def stop(service: OutlookCalendarService) -> None:
        service._timer.stop()
        service._tick.stop()
        service.deleteLater()


class SnapshotStateTests(ServiceTestCase):
    def test_starts_closed_without_a_cache(self):
        service = self.make()
        self.assertEqual(service.snapshot, Snapshot())
        self.refresh.assert_called_once_with()

    def test_starts_from_the_cache_marked_stale(self):
        write_cache(self.cache, Snapshot((EVENT,), FETCHED, "live"))
        self.assertEqual(self.make().snapshot, Snapshot((EVENT,), FETCHED, "stale"))

    def test_corrupt_cache_is_ignored(self):
        self.cache.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.make().snapshot, Snapshot())

    def test_success_goes_live_and_is_cached(self):
        service = self.make()
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "live"))
        self.assertEqual(load_cache(self.cache), Snapshot((EVENT,), NOW, "stale"))

    def test_outlook_closing_keeps_the_events(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "closed")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "stale"))

    def test_closed_with_nothing_cached(self):
        service = self.make()
        service._on_done(None, "closed")
        self.assertEqual(service.snapshot, Snapshot())

    def test_three_failures_in_a_row_mark_an_error(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "error")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot.status, "live")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "error"))
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot.status, "live")

    def test_closed_resets_the_failure_count(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._on_done(None, "error")
        service._on_done(None, "error")
        service._on_done(None, "closed")
        service._on_done(None, "error")
        self.assertEqual(service.snapshot.status, "stale")

    def test_every_result_emits_updated(self):
        service = self.make()
        seen = []
        service.updated.connect(lambda: seen.append(service.snapshot.status))
        service._on_done(None, "closed")
        service._on_done([EVENT], "")
        self.assertEqual(seen, ["closed", "live"])

    def test_tick_retries_while_outlook_is_closed(self):
        service = self.make()
        self.refresh.reset_mock()
        service._on_done(None, "closed")
        service._on_tick()
        self.refresh.assert_called_once_with()

    def test_tick_does_not_poll_while_outlook_is_live(self):
        service = self.make()
        self.refresh.reset_mock()
        service._on_done([EVENT], "")
        service._on_tick()
        self.refresh.assert_not_called()

    def test_an_error_keeps_the_closed_flag(self):
        service = self.make()
        service._on_done(None, "closed")
        service._on_done(None, "error")
        self.refresh.reset_mock()
        service._on_tick()
        self.refresh.assert_called_once_with()

    def test_every_tick_emits_updated(self):
        service = self.make()
        seen = []
        service.updated.connect(lambda: seen.append(1))
        service._on_tick()
        service._on_done(None, "closed")
        seen.clear()
        service._on_tick()
        self.assertEqual(seen, [1])

    def test_a_hung_fetch_marks_the_reading_as_error(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._worker = mock.Mock()
        service._fetch_started = 0.0
        service._clock = lambda: 61.0
        service._on_tick()
        self.assertEqual(service.snapshot, Snapshot((EVENT,), NOW, "error"))
        service._worker = None

    def test_a_fetch_within_the_timeout_changes_nothing(self):
        service = self.make()
        service._on_done([EVENT], "")
        service._worker = mock.Mock()
        service._fetch_started = 0.0
        service._clock = lambda: 59.0
        service._on_tick()
        self.assertEqual(service.snapshot.status, "live")
        service._worker = None

    def test_unwritable_cache_is_not_fatal(self):
        service = self.make(cache_file=self.cache.parent / "missing" / "outlook_calendar.json")
        service._on_done([EVENT], "")
        self.assertEqual(service.snapshot.status, "live")


class SharedInstanceTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(service_module, "cache_path", return_value=self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, OutlookCalendarService, "_instance", None)

    def get(self, *args) -> OutlookCalendarService:
        service = OutlookCalendarService.get_instance(*args)
        self.addCleanup(self.stop, service)
        return service

    def test_bars_share_one_service_that_widens(self):
        first = self.get(7, 300, False)
        self.refresh.reset_mock()
        second = self.get(14, 120, True)
        self.assertIs(first, second)
        self.assertEqual((first._days, first._scan_body, first._timer.interval()), (14, True, 120_000))
        self.refresh.assert_called_once_with()

    def test_a_narrower_bar_changes_nothing(self):
        first = self.get(14, 120, True)
        self.refresh.reset_mock()
        self.get(7, 300, False)
        self.assertEqual((first._days, first._scan_body, first._timer.interval()), (14, True, 120_000))
        self.refresh.assert_not_called()

    def test_widening_during_a_fetch_reruns_it_afterwards(self):
        first = self.get(7, 300, False)
        self.refresh.reset_mock()
        first._worker = mock.Mock()
        self.get(14, 300, True)
        self.refresh.assert_not_called()
        first._on_worker_finished()
        self.refresh.assert_called_once_with()
        first._on_worker_finished()
        self.refresh.assert_called_once_with()

    def test_widening_with_no_fetch_does_not_rerun_later(self):
        first = self.get(7, 300, False)
        self.refresh.reset_mock()
        self.get(14, 300, True)
        self.refresh.assert_called_once_with()
        first._worker = mock.Mock()
        first._on_worker_finished()
        self.refresh.assert_called_once_with()

    def test_no_rerun_after_the_service_is_released(self):
        first = self.get(7, 300, False)
        worker = mock.Mock()
        worker.isRunning.return_value = True
        first._worker = worker
        self.get(14, 300, True)
        self.refresh.reset_mock()
        first.release()
        first.release()
        first._on_worker_finished()
        self.refresh.assert_not_called()
        worker.finished.connect.assert_called_once_with(first.deleteLater)

    def test_released_by_the_last_bar(self):
        first = self.get(7, 300, True)
        self.get(7, 300, True)
        first.release()
        self.assertIs(OutlookCalendarService._instance, first)
        first.release()
        self.assertIsNone(OutlookCalendarService._instance)


class WorkerTests(unittest.TestCase):
    def run_worker(self, **fetch_patch) -> list[tuple]:
        worker = service_module._FetchWorker(7, True)
        results = []
        worker.done.connect(lambda events, failure: results.append((events, failure)))
        with mock.patch.object(service_module, "fetch", **fetch_patch):
            worker.run()
        return results

    def test_success(self):
        self.assertEqual(self.run_worker(return_value=[EVENT]), [([EVENT], "")])

    def test_not_running(self):
        self.assertEqual(self.run_worker(side_effect=OutlookNotRunning()), [(None, "closed")])

    def test_other_failure(self):
        with self.assertLogs("outlook_calendar", "WARNING"):
            results = self.run_worker(side_effect=RuntimeError("boom"))
        self.assertEqual(results, [(None, "error")])


if __name__ == "__main__":
    unittest.main()

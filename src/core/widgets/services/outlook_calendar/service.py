"""Shared poller for the Outlook calendar widget.

One service runs per process, however many bars show the widget, so a bar on every monitor
still means one COM poll. Instances are reference-counted and released when the last widget
goes away (mirrors ``AnimeAiringService``). A widget asking for a longer window, a shorter
interval or body scanning widens the one service rather than starting another.

The last successful read is cached in the YASB data folder. At login the bar counts down
from it before Outlook is running, and while Outlook is closed it keeps counting down from
it, marked stale.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pythoncom
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.utils.system import app_data_path
from core.widgets.services.outlook_calendar.agenda import Snapshot, snapshot_from_cache, snapshot_to_cache
from core.widgets.services.outlook_calendar.outlook import OutlookNotRunning, fetch

logger = logging.getLogger("outlook_calendar")

CACHE_FILE = "outlook_calendar.json"
FAILURES_BEFORE_ERROR = 3
TICK_MS = 30_000
FETCH_TIMEOUT_S = 60


def cache_path() -> Path:
    return app_data_path(CACHE_FILE)


def load_cache(path: Path) -> Snapshot | None:
    try:
        with open(path, encoding="utf-8") as cache_file:
            data = json.load(cache_file)
    except (OSError, ValueError) as error:
        logger.debug("outlook calendar: no usable cache: %s", error)
        return None
    snapshot = snapshot_from_cache(data)
    if snapshot is None:
        logger.debug("outlook calendar: ignored a cache this version did not write")
    return snapshot


def write_cache(path: Path, snapshot: Snapshot) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as cache_file:
            json.dump(snapshot_to_cache(snapshot), cache_file)
        os.replace(temporary, path)
    except OSError as error:
        logger.debug("outlook calendar: failed to write the cache: %s", error)


class _FetchWorker(QThread):
    """Reads Outlook off the UI thread. ``done`` carries (events or None, failure kind)."""

    done = pyqtSignal(object, str)

    def __init__(self, days: int, scan_body: bool, parent: QObject | None = None):
        super().__init__(parent)
        self._days = days
        self._scan_body = scan_body

    def run(self) -> None:
        pythoncom.CoInitialize()
        try:
            events = fetch(datetime.now(), self._days, self._scan_body)
        except OutlookNotRunning:
            self.done.emit(None, "closed")
        except Exception as error:  # a widget must never take the bar down
            logger.warning("outlook calendar: reading Outlook failed: %s", error)
            self.done.emit(None, "error")
        else:
            self.done.emit(events, "")
        finally:
            pythoncom.CoUninitialize()


class OutlookCalendarService(QObject):
    """Polls Outlook and holds the latest ``Snapshot``."""

    # Emitted after every poll result and every 30 seconds, so widgets re-derive countdowns.
    updated = pyqtSignal()

    _instance: ClassVar[OutlookCalendarService | None] = None

    @classmethod
    def get_instance(cls, days: int, update_interval_s: int, scan_body: bool) -> OutlookCalendarService:
        instance = cls._instance
        if instance is None:
            instance = cls(days, update_interval_s, scan_body)
            cls._instance = instance
        else:
            instance._widen(days, update_interval_s, scan_body)
        instance._refcount += 1
        return instance

    def __init__(self, days: int, update_interval_s: int, scan_body: bool, cache_file: Path | None = None):
        super().__init__()
        self._refcount = 0
        self._days = int(days)
        self._scan_body = bool(scan_body)
        self._failures = 0
        self._refresh_after_fetch = False
        self._outlook_closed = False
        self._fetch_started = 0.0
        self._worker: _FetchWorker | None = None
        self._cache_path = cache_file if cache_file is not None else cache_path()
        self.snapshot: Snapshot = load_cache(self._cache_path) or Snapshot()

        self._timer = QTimer(self)
        self._timer.setInterval(max(int(update_interval_s), 60) * 1000)
        self._timer.timeout.connect(self.refresh_now)
        self._timer.start()
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self.refresh_now()

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    @staticmethod
    def _clock() -> float:
        return time.monotonic()

    def _on_tick(self) -> None:
        if self._outlook_closed:
            # Attaching takes about 11 ms and never starts Outlook, so look again at every tick
            # rather than waiting out the update interval. A no-op while a fetch runs.
            self.refresh_now()
        if (
            self._worker is not None
            and self._clock() - self._fetch_started > FETCH_TIMEOUT_S
            and self.snapshot.status != "error"
        ):
            # A hung Outlook blocks the worker for good; don't keep calling the reading live.
            self.snapshot = replace(self.snapshot, status="error")
        self.updated.emit()

    def _widen(self, days: int, update_interval_s: int, scan_body: bool) -> None:
        changed = False
        if days > self._days:
            self._days = int(days)
            changed = True
        if scan_body and not self._scan_body:
            self._scan_body = True
            changed = True
        interval_ms = max(int(update_interval_s), 60) * 1000
        if interval_ms < self._timer.interval():
            self._timer.setInterval(interval_ms)
        if changed:
            if self._worker is not None:
                # The running fetch was built with the old window; rerun once it ends.
                self._refresh_after_fetch = True
            else:
                self.refresh_now()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        self._refresh_after_fetch = False
        self._timer.stop()
        self._tick.stop()
        if OutlookCalendarService._instance is self:
            OutlookCalendarService._instance = None
        if self._worker is not None and self._worker.isRunning():
            # Never block the UI thread on Outlook during a config reload.
            self._worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def refresh_now(self) -> None:
        if self._worker is not None:
            return
        worker = _FetchWorker(self._days, self._scan_body, self)
        worker.done.connect(self._on_done)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._fetch_started = self._clock()
        worker.start()

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._refresh_after_fetch:
            self._refresh_after_fetch = False
            self.refresh_now()

    def _on_done(self, events, failure: str) -> None:
        if events is not None:
            self._failures = 0
            self._outlook_closed = False
            self.snapshot = Snapshot(tuple(events), self._now(), "live")
            write_cache(self._cache_path, self.snapshot)
        elif failure == "closed":
            self._failures = 0
            self._outlook_closed = True
            self.snapshot = replace(self.snapshot, status="stale" if self.snapshot.fetched_at else "closed")
        else:
            self._failures += 1
            if self._failures >= FAILURES_BEFORE_ERROR:
                self.snapshot = replace(self.snapshot, status="error")
        self.updated.emit()

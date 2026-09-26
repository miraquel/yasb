"""Shared poller and reminder clock for the anime airing widget.

One service runs per configuration, however many bars show the widget. That matters for
more than the network: the reminder toasts are fired here, so a bar on every monitor still
announces each episode once. Instances are reference-counted and released when the last
widget goes away (mirrors ``DeepSeekUsageService``).

The last snapshot and the set of announced episodes are kept in one JSON file per user in
the YASB data folder. The snapshot lets the bar show a countdown the moment it starts,
before - or without - the network; the announced set is what stops a restart from
replaying a reminder.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
import xml.sax.saxutils
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.utils.system import app_data_path
from core.utils.utilities import ToastNotifier
from core.widgets.services.anime_airing.schedule import (
    already_due,
    build_episodes,
    build_shows,
    due_episodes,
    prune_notified,
    reminder_text,
    upcoming_shows,
)
from core.widgets.services.anime_airing.sources import USER_AGENT, Snapshot, SourceError, fetch_snapshot
from settings import SCRIPT_PATH

logger = logging.getLogger("anime_airing")

_CACHE_VERSION = 1
_RETRY_MS = 60_000
_COVER_DIR = "anime_airing_covers"
_COVER_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ReminderSettings:
    enabled: bool = True
    offset_minutes: int = 0
    catch_up_hours: int = 12
    title_language: str = "romaji"


def _slug(username: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", username.strip().lower()) or "_"


def cache_path(username: str) -> Path:
    return app_data_path(f"anime_airing_{_slug(username)}.json")


def cover_path(anilist_id: int, url: str) -> Path:
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    return app_data_path(_COVER_DIR) / f"{anilist_id}{suffix}"


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as cache_file:
            data = json.load(cache_file)
    except OSError, ValueError:
        return {}
    if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION:
        return {}
    return data


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as cache_file:
            json.dump(data, cache_file)
        os.replace(temporary, path)
    except OSError as error:
        logger.debug("failed to write anime airing cache: %s", error)


def _download_covers(snapshot: Snapshot) -> None:
    """Keep a local copy of each airing show's cover: Windows toasts from a desktop app
    only load images from disk, and the popup reads the same files."""
    for media in snapshot.media:
        if not media.cover_url or (media.next_episode is None and media.status != "RELEASING"):
            continue
        target = cover_path(media.anilist_id, media.cover_url)
        if target.exists():
            continue
        try:
            request = urllib.request.Request(media.cover_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read(_COVER_MAX_BYTES + 1)
            if len(data) > _COVER_MAX_BYTES:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".part")
            temporary.write_bytes(data)
            os.replace(temporary, target)
        except (OSError, ValueError) as error:
            logger.debug("cover download failed for %s: %s", media.anilist_id, error)


class _FetchWorker(QThread):
    """Runs the blocking MAL and AniList requests off the UI thread."""

    done = pyqtSignal(object, str)

    def __init__(self, username: str, statuses: tuple[str, ...], parent: QObject | None = None):
        super().__init__(parent)
        self._username = username
        self._statuses = statuses

    def run(self) -> None:
        try:
            snapshot = fetch_snapshot(self._username, self._statuses)
        except SourceError as error:
            logger.warning("anime airing: %s", error)
            self.done.emit(None, error.kind + ":" + str(error))
            return
        except Exception as error:  # a widget must never take the bar down
            logger.exception("anime airing: unexpected fetch failure")
            self.done.emit(None, f"response:{error}")
            return
        _download_covers(snapshot)
        self.done.emit(snapshot, "")


class AnimeAiringService(QObject):
    """Polls one user's list and schedule, and fires that user's episode reminders."""

    # Emitted after new data and on every minute tick, so widgets re-derive countdowns.
    updated = pyqtSignal()

    _instances: ClassVar[dict[tuple, AnimeAiringService]] = {}

    @classmethod
    def get_instance(
        cls,
        username: str,
        statuses: tuple[str, ...],
        update_interval_s: int,
        reminders: ReminderSettings,
    ) -> AnimeAiringService:
        key = (username.strip().lower(), tuple(statuses), int(update_interval_s), reminders)
        instance = cls._instances.get(key)
        if instance is None:
            instance = cls(username.strip(), tuple(statuses), int(update_interval_s), reminders, key)
            cls._instances[key] = instance
        instance._refcount += 1
        return instance

    def __init__(
        self,
        username: str,
        statuses: tuple[str, ...],
        update_interval_s: int,
        reminders: ReminderSettings,
        key: tuple,
    ):
        super().__init__()
        self._key = key
        self._refcount = 0
        self.username = username
        self._statuses = statuses
        self._reminders = reminders
        self._worker: _FetchWorker | None = None
        self._cache_path = cache_path(username) if username else None

        cached = _read_cache(self._cache_path) if self._cache_path else {}
        self.snapshot: Snapshot | None = Snapshot.from_dict(cached.get("snapshot"))
        # None until the first snapshot has been seen: that first look marks everything
        # already past as announced, so installing the widget does not replay the week.
        notified = cached.get("notified")
        self._notified: dict[str, int] | None = (
            {str(k): int(v) for k, v in notified.items()} if isinstance(notified, dict) else None
        )
        self.error_kind = ""
        self.error_text = ""
        self.loading = self.snapshot is None and bool(username)

        self._timer = QTimer(self)
        self._timer.setInterval(max(update_interval_s, 60) * 1000)
        self._timer.timeout.connect(self.refresh_now)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.refresh_now)

        # Aligned to the wall clock so a countdown turns over on the minute, like the clock.
        # The aligning shot is a timer of our own rather than QTimer.singleShot, so that
        # release() can stop it before it fires into a deleted service.
        self._minute = QTimer(self)
        self._minute.setInterval(60_000)
        self._minute.timeout.connect(self._on_minute)
        self._align = QTimer(self)
        self._align.setSingleShot(True)
        self._align.timeout.connect(self._start_minute)
        now = datetime.now()
        self._align.start(max((60 - now.second) * 1000 - now.microsecond // 1000, 0))

        if not username:
            self.error_kind = "config"
            self.error_text = "Set a MyAnimeList username"
            return
        self._timer.start()
        self.refresh_now()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        for timer in (self._timer, self._retry, self._align, self._minute):
            timer.stop()
        AnimeAiringService._instances.pop(self._key, None)
        if self._worker is not None and self._worker.isRunning():
            # Never block the GUI thread on a request during a config reload.
            self._worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def refresh_now(self) -> None:
        if self._worker is not None or not self.username:
            return
        worker = _FetchWorker(self.username, self._statuses, self)
        worker.done.connect(self._on_done)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _on_done(self, snapshot: Snapshot | None, error: str) -> None:
        self.loading = False
        if snapshot is None:
            kind, _, text = error.partition(":")
            self.error_kind, self.error_text = kind, text
            # A wrong username will not fix itself in a minute; anything else might.
            if kind != "user":
                self._retry.start(_RETRY_MS)
            self.updated.emit()
            return
        self._retry.stop()
        self.error_kind = self.error_text = ""
        self.snapshot = snapshot
        if self._notified is None:
            episodes = build_episodes(snapshot, self._reminders.title_language)
            self._notified = already_due(episodes, self._now(), self._offset)
        self._save()
        self._check_reminders()
        self.updated.emit()

    # ------------------------------------------------------------------
    # Clock and reminders
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()

    @property
    def _offset(self) -> timedelta:
        return timedelta(minutes=self._reminders.offset_minutes)

    def _start_minute(self) -> None:
        self._minute.start()
        self._on_minute()

    def _on_minute(self) -> None:
        self._check_reminders()
        self.updated.emit()

    def _check_reminders(self) -> None:
        if not self._reminders.enabled or self.snapshot is None or self._notified is None:
            return
        now = self._now()
        language = self._reminders.title_language
        due = due_episodes(
            build_episodes(self.snapshot, language),
            now,
            self._offset,
            timedelta(hours=self._reminders.catch_up_hours),
            self._notified,
        )
        if not due:
            return
        unwatched = {show.anilist_id: show.unwatched for show in build_shows(self.snapshot, now, language)}
        for episode in due:
            self._notified[episode.key] = int(episode.at.timestamp())
            title, message = reminder_text(episode, now, unwatched.get(episode.anilist_id))
            self._toast(episode.anilist_id, title, message, episode.url)
        self._notified = prune_notified(self._notified, now)
        self._save()

    def _toast(self, anilist_id: int, title: str, message: str, url: str) -> None:
        icon = ""
        media = next((m for m in self.snapshot.media if m.anilist_id == anilist_id), None) if self.snapshot else None
        if media is not None and media.cover_url:
            path = cover_path(anilist_id, media.cover_url)
            if path.exists():
                icon = str(path)
        if not icon:
            icon = os.path.join(SCRIPT_PATH, "assets", "images", "app_transparent.png")
        try:
            # ToastNotifier drops these straight into its XML template, and titles carry
            # '&' often enough ("2nd & 3rd STAGE") to break the whole toast.
            escape = xml.sax.saxutils.escape
            ToastNotifier().show(
                escape(icon, {'"': "&quot;"}),
                escape(title),
                escape(message),
                launch_url=escape(url, {'"': "&quot;"}),
                launch_label="Open on MyAnimeList",
            )
        except Exception as error:
            logger.warning("anime airing: could not show a reminder: %s", error)

    def _save(self) -> None:
        if self._cache_path is None:
            return
        _write_cache(
            self._cache_path,
            {
                "version": _CACHE_VERSION,
                "snapshot": self.snapshot.to_dict() if self.snapshot else None,
                "notified": self._notified,
            },
        )

    # ------------------------------------------------------------------
    # Debugging aid
    # ------------------------------------------------------------------

    def test_reminder(self) -> None:
        """Fire a reminder for the soonest episode right now, whatever its time."""
        now = self._now()
        language = self._reminders.title_language
        shows = upcoming_shows(build_shows(self.snapshot, now, language))
        if not shows:
            self._toast(0, "Anime airing", "Nothing on your list is airing", "https://myanimelist.net/")
            return
        show = shows[0]
        message = f"Episode {show.next_episode} is next"
        self._toast(show.anilist_id, show.title, message, show.url)

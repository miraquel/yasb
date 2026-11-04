"""
TaskbarNotificationMonitor
--------------------------
Polls the Windows Notification Center via WinRT UserNotificationListener and
emits a per-app unread count dictionary every time the counts change.

This is used by TaskbarWidget to drive the per-button notification badge when
`badge.enabled = true` in config.yaml.

Why WinRT instead of ITaskbarList3?
  ITaskbarList3::SetOverlayIcon is write-only — no public Windows API lets a
  third-party process read back another app's overlay icon or badge count.
  The Windows Notification Center (Action Center) DOES expose per-app counts
  via UserNotificationListener and is the practical source of truth for
  unread notifications (used by WhatsApp, Discord, Slack, Outlook, Teams, …).

Access requirement:
  Windows → Settings → System → Notifications
  → "Allow apps to access notifications" must be ON.
  On first run the user may be prompted to grant access.
"""

import asyncio
import logging
from collections.abc import Iterable, Mapping

import winrt.windows.ui.notifications.management as management
from PyQt6.QtCore import QThread, pyqtSignal
from winrt.windows.ui.notifications import NotificationKinds, UserNotification


def count_by_app(names: Iterable[str]) -> dict[str, int]:
    """Count notifications per app, keyed by the display name stripped and lowercased.

    Blank names are skipped.
    """
    counts: dict[str, int] = {}
    for raw in names:
        name = raw.strip().lower()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def match_notification_count(process_name: str | None, counts: Mapping[str, int]) -> int:
    """Return the notification count for the app running as *process_name*, or 0.

    The process name without ``.exe`` (``WhatsApp.exe`` → ``whatsapp``) is looked up first.
    Failing that, the first app name that contains the key, or is contained in it, wins.
    """
    if not process_name or not counts:
        return 0
    key = process_name.lower().replace(".exe", "").strip()
    count = counts.get(key, 0)
    if count > 0:
        return count
    for app_name, c in counts.items():
        if app_name and (app_name in key or key in app_name):
            return c
    return 0


def _display_name(notification: UserNotification) -> str:
    """The notification's app display name, or "" when Windows cannot resolve it."""
    try:
        return notification.app_info.display_info.display_name
    except Exception:
        return ""


class TaskbarNotificationMonitor(QThread):
    """Background thread that polls Windows notification counts per app.

    Emits `counts_updated` with a ``dict[str, int]`` of
    ``{app_display_name_lower: unread_count}`` whenever the snapshot changes.
    """

    counts_updated = pyqtSignal(dict)

    def __init__(self, poll_interval: float = 2.0):
        super().__init__()
        self._running = True
        self._poll_interval = poll_interval
        self._loop = asyncio.new_event_loop()

    # ------------------------------------------------------------------
    # Private async helpers
    # ------------------------------------------------------------------

    async def _poll(self) -> None:
        try:
            listener = management.UserNotificationListener.current
            access_result = await listener.request_access_async()

            if access_result != management.UserNotificationListenerAccessStatus.ALLOWED:
                logging.warning(
                    "TaskbarNotificationMonitor: Windows notification access denied. "
                    "Enable 'Allow apps to access notifications' in Windows Settings → System → Notifications."
                )
                return

            last_counts: dict[str, int] = {}

            while self._running:
                try:
                    counts = await self._snapshot(listener)
                    if counts != last_counts:
                        last_counts = counts
                        self.counts_updated.emit(dict(counts))
                except Exception as exc:
                    logging.debug("TaskbarNotificationMonitor poll error: %s", exc)

                await asyncio.sleep(self._poll_interval)

        except Exception as exc:
            logging.warning("TaskbarNotificationMonitor stopped: %s", exc)

    async def _snapshot(self, listener: management.UserNotificationListener) -> dict[str, int]:
        """Return ``{app_name_lower: count}`` for all current notifications."""
        try:
            notifications = await listener.get_notifications_async(NotificationKinds.TOAST)
            return count_by_app(_display_name(n) for n in notifications)
        except Exception as exc:
            logging.debug("TaskbarNotificationMonitor snapshot error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # QThread interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._poll())
        except Exception as exc:
            logging.error("TaskbarNotificationMonitor thread error: %s", exc)
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    def stop(self) -> None:
        self._running = False
        try:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception as exc:
            logging.debug("TaskbarNotificationMonitor stop error: %s", exc)

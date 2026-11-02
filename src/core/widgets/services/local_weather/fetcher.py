"""Fetches the forecast for wherever the laptop is: each refresh asks Windows location first (off
the GUI thread), picks the place, then calls WeatherAPI. A failure retries every minute.

The request URL carries the API key, so it is never logged.
"""

import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from core.utils.widgets.local_weather.forecast import parse_forecast
from core.utils.widgets.local_weather.location import LocateResult, LocationTracker, Place
from core.widgets.services.weather.api import CACHE_CONTROL, HEADER

API_URL = "https://api.weatherapi.com/v1/forecast.json"
RETRY_MS = 60_000  # the card's copy promises "Trying again every minute"
# A lookup the watchdog cut off (15 s) plus a request at its transfer timeout (20 s) still ends
# before the next refresh may start, so an older reply can never land after a newer one.
LOCATE_TIMEOUT_MS = 15_000
TRANSFER_TIMEOUT_MS = 20_000
BUSY_TIMEOUT_S = 40  # a lookup or request older than this no longer blocks the next refresh


def build_url(api_key: str, query: str) -> str:
    params = {"key": api_key, "q": query, "days": 3, "aqi": "no", "alerts": "yes"}
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


class LocalWeatherFetcher(QObject):
    finished = pyqtSignal(dict, object)  # the payload, and the Place it is for
    failed = pyqtSignal(object)  # the Place that was tried
    _located = pyqtSignal(int, object)  # (lookup token, LocateResult) from the lookup thread

    def __init__(
        self,
        parent: QObject | None,
        api_key: str,
        tracker: LocationTracker,
        locate: Callable[[], LocateResult],
        interval_ms: int,
    ):
        super().__init__(parent)
        self._api_key = api_key
        self._tracker = tracker
        self._locate = locate
        self._busy_since: float | None = None
        self._token = 0  # the current lookup; a late answer from an older one is dropped
        self._requests: dict[QNetworkReply, Place] = {}

        self._manager = QNetworkAccessManager(self)
        self._manager.finished.connect(self._on_reply)
        self._located.connect(self._on_located)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(RETRY_MS)
        self._retry_timer.timeout.connect(self.refresh)
        # WinRT's own timeout only covers its async wait; a call that blocks outright never
        # answers, so the GUI side gives up on it and falls back as "no fix".
        self._locate_watchdog = QTimer(self)
        self._locate_watchdog.setSingleShot(True)
        self._locate_watchdog.setInterval(LOCATE_TIMEOUT_MS)
        self._locate_watchdog.timeout.connect(self._on_locate_timeout)

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def refresh(self) -> None:
        now = time.monotonic()
        if self._busy_since is not None and now - self._busy_since < BUSY_TIMEOUT_S:
            return
        self._busy_since = now
        self._token += 1
        self._locate_watchdog.start()
        self._start_locate(self._token)

    def _start_locate(self, token: int) -> None:
        def run() -> None:
            try:
                result = self._locate()
            except Exception as e:
                logging.warning("Local weather: location lookup raised %s", type(e).__name__)
                result = "no_fix"
            try:
                self._located.emit(token, result)
            except RuntimeError:
                pass  # the widget went away while Windows was answering

        threading.Thread(target=run, name="LocalWeatherLocate", daemon=True).start()

    def _on_locate_timeout(self) -> None:
        logging.warning("Local weather: Windows location did not answer in time")
        self._on_located(self._token, "no_fix")

    def _on_located(self, token: int, result: LocateResult) -> None:
        if token != self._token:
            return  # an older lookup, already given up on
        self._token += 1  # this lookup is answered; anything later from it is dropped
        self._locate_watchdog.stop()
        self._request(self._tracker.resolve(result, time.time()))

    def _request(self, place: Place) -> None:
        request = QNetworkRequest(QUrl(build_url(self._api_key, place.query)))
        request.setRawHeader(*HEADER)
        request.setRawHeader(*CACHE_CONTROL)
        request.setTransferTimeout(TRANSFER_TIMEOUT_MS)
        self._requests[self._manager.get(request)] = place

    def _on_reply(self, reply: QNetworkReply) -> None:
        place = self._requests.pop(reply, None)
        try:
            raw = reply.readAll().data()
            try:
                data = json.loads(raw.decode("utf-8", errors="replace")) if raw else None
            except ValueError:
                data = None
            if reply.error() != QNetworkReply.NetworkError.NoError and not (isinstance(data, dict) and "error" in data):
                logging.warning("Local weather: WeatherAPI request failed (%s)", reply.error().name)
        finally:
            reply.deleteLater()
        if place is not None:
            self._on_payload(data if isinstance(data, dict) else None, place)

    def _on_payload(self, data: dict | None, place: Place) -> None:
        self._busy_since = None
        if data is not None and parse_forecast(data, 0.0) is not None:
            self._retry_timer.stop()
            self.finished.emit(data, place)
            return
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            error = data["error"]
            logging.warning("Local weather: WeatherAPI error %s: %s", error.get("code"), error.get("message"))
        self._retry_timer.start()
        self.failed.emit(place)

"""Weather for the AI usage popups' sky.

Asks Open-Meteo (https://open-meteo.com) for the current WMO weather code, temperature and
wind, and switches to met.no (https://api.met.no) for good once Open-Meteo stops answering, as
it is blocked in some places. Neither needs a key. The coordinates come from the config only:
there is no lookup by IP, so the only thing sent is the location you configured.
"""

import json
import logging
import re
import ssl
import time
import urllib.request
from typing import Any, ClassVar

import certifi
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

logger = logging.getLogger("claude_usage")

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&current=weather_code,temperature_2m,wind_speed_10m&forecast_days=1"
)
# met.no asks for at most four decimals, and for a User-Agent that names the application.
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}"
USER_AGENT = "yasb-claude-usage-widget (+https://github.com/amnweb/yasb)"


def _get_json(url: str) -> Any:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # certifi's bundle, as the updater uses: Windows' store only holds the roots it has
        # needed so far, and Python cannot fetch a missing one the way Windows itself does,
        # which is exactly how api.met.no fails on a machine that has never visited it.
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.debug("weather fetch failed (%s): %s", url.split("?")[0], e)
        return None


def parse_open_meteo(payload: Any) -> dict[str, float] | None:
    try:
        current = payload["current"]
        return {
            "code": int(current["weather_code"]),
            "temp": float(current["temperature_2m"]),
            "wind": float(current["wind_speed_10m"]),
        }
    except Exception:
        return None


def met_no_code(symbol: str) -> int:
    """met.no names the weather ("lightrainshowers_day"); turn that into a WMO code."""
    sym = re.sub(r"_(day|night|polartwilight)$", "", symbol or "")
    level = 0 if sym.startswith("light") else 2 if sym.startswith("heavy") else 1
    showers = "showers" in sym
    if "thunder" in sym:
        return 95
    if "snow" in sym:
        return (85, 85, 86)[level] if showers else (71, 73, 75)[level]
    if "sleet" in sym:
        return 67 if level == 2 else 66
    if "rain" in sym:
        return (80, 81, 82)[level] if showers else (61, 63, 65)[level]
    for prefix, code in (("fog", 45), ("cloudy", 3), ("partlycloudy", 2), ("fair", 1), ("clearsky", 0)):
        if sym.startswith(prefix):
            return code
    return 3


def parse_met_no(payload: Any) -> dict[str, float] | None:
    try:
        data = payload["properties"]["timeseries"][0]["data"]
        details = data["instant"]["details"]
        return {
            "code": met_no_code(data["next_1_hours"]["summary"]["symbol_code"]),
            "temp": float(details["air_temperature"]),
            "wind": 3.6 * float(details["wind_speed"]),  # m/s -> km/h, as Open-Meteo reports it
        }
    except Exception:
        return None


def fetch_weather(lat: float, lon: float, use_met_no: bool = False) -> dict[str, Any]:
    """The current weather, or an empty dict when neither source answers."""
    if not use_met_no:
        weather = parse_open_meteo(_get_json(OPEN_METEO_URL.format(lat=lat, lon=lon)))
        if weather is not None:
            return dict(weather, source="open-meteo", fetched_at=time.time())
    weather = parse_met_no(_get_json(MET_NO_URL.format(lat=lat, lon=lon)))
    if weather is not None:
        return dict(weather, source="met.no", fetched_at=time.time())
    return {}


class _WeatherWorker(QThread):
    """Runs the (blocking) weather request off the UI thread."""

    data_ready = pyqtSignal(dict)

    def __init__(self, lat: float, lon: float, use_met_no: bool, parent: QObject | None = None):
        super().__init__(parent)
        self._args = (lat, lon, use_met_no)

    def run(self) -> None:
        self.data_ready.emit(fetch_weather(*self._args))


class SkyWeatherService(QObject):
    """Shared weather poller, one per location and interval (mirrors ``ClaudeStatusService``).

    The last reading is kept when a fetch fails; the sky itself decides when it is too old to
    draw.
    """

    data_ready = pyqtSignal(dict)

    _instances: ClassVar[dict[tuple[float, float, int], SkyWeatherService]] = {}

    @classmethod
    def get_instance(cls, lat: float, lon: float, interval_s: int) -> SkyWeatherService:
        key = (round(lat, 4), round(lon, 4), int(interval_s))
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(lat, lon, int(interval_s), _key=key)
            cls._instances[key] = inst
        inst._refcount += 1
        return inst

    def __init__(self, lat: float, lon: float, interval_s: int, _key: tuple[float, float, int]):
        super().__init__()
        self._key = _key
        self._lat = lat
        self._lon = lon
        self._refcount = 0
        self._use_met_no = False
        self._worker: _WeatherWorker | None = None
        self._data: dict[str, Any] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(max(interval_s, 60) * 1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def latest(self) -> dict[str, Any]:
        return self._data

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        self._timer.stop()
        SkyWeatherService._instances.pop(self._key, None)
        if self._worker is not None and self._worker.isRunning():
            self._worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    def _tick(self) -> None:
        if self._worker is not None:
            return  # a fetch is already in flight
        worker = _WeatherWorker(self._lat, self._lon, self._use_met_no, self)
        worker.data_ready.connect(self._on_data)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def _on_data(self, data: dict[str, Any]) -> None:
        if not data:
            return
        # Open-Meteo failed and met.no answered: stay with met.no rather than wait out
        # Open-Meteo's timeout on every fetch.
        if data.get("source") == "met.no":
            self._use_met_no = True
        self._data = data
        self.data_ready.emit(data)

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

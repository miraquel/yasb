"""Where the forecast is for: the laptop's position from Windows location, or the config address.

Coordinates stay in memory, rounded to two decimals (about 1 km), and are never logged, not even
at DEBUG.
"""

import logging
from dataclasses import dataclass
from typing import Literal

# What a Windows location lookup hands back: a position, or why there is none ("off" when
# location is disabled or denied, "no_fix" when it is allowed but nothing came back in time).
LocateResult = tuple[float, float] | Literal["off", "no_fix"]
Reason = Literal["", "off", "no_fix"]

# A failed lookup (say a Wi-Fi scan timing out) keeps the last fix this long, so one miss
# doesn't send the forecast back to the config address.
REUSE_S = 2 * 3600


@dataclass(frozen=True)
class Fix:
    lat: float
    lon: float
    at: float  # epoch seconds it was taken


@dataclass(frozen=True)
class Place:
    query: str  # what WeatherAPI is asked for: "lat,lon" or the config address
    source: Literal["windows", "config"]
    reason: Reason  # why the config address is used ("" when it isn't)


def round_fix(lat: float, lon: float, at: float) -> Fix:
    return Fix(round(lat, 2), round(lon, 2), at)


class LocationTracker:
    """Picks the place for each refresh: a fresh fix, else a recent one, else the config address."""

    def __init__(self, config_location: str):
        self._config_location = config_location
        self.last: Fix | None = None

    def resolve(self, result: LocateResult, now: float) -> Place:
        # The position itself is never logged, not even at DEBUG: with `debug: true` it would
        # land in yasb.log, on disk.
        if isinstance(result, tuple):
            self.last = round_fix(*result, now)
            logging.debug("Local weather: using a fresh Windows location fix")
            return self._windows(self.last)
        if result == "off":
            # Switched off or denied: stop using the old position too, not just new ones.
            self.last = None
        elif self.last is not None and now - self.last.at < REUSE_S:
            logging.debug("Local weather: no fresh fix (%s), reusing the last one", result)
            return self._windows(self.last)
        logging.warning("Local weather: no Windows location (%s), using the config address", result)
        return Place(self._config_location, "config", result)

    @staticmethod
    def _windows(fix: Fix) -> Place:
        return Place(f"{fix.lat:.2f},{fix.lon:.2f}", "windows", "")

"""The laptop's position from Windows location (WinRT ``Geolocator``), the source Maps uses.

``windows_fix`` blocks for up to its timeout, so it is only ever called off the GUI thread. The
position is returned, never logged: only the accuracy reaches the log, at DEBUG.
"""

import asyncio
import logging
from datetime import timedelta
from types import ModuleType

from core.utils.widgets.local_weather.location import LocateResult

_missing_logged = False


def windows_fix(
    accuracy_m: int = 500,
    max_age_s: int = 600,
    timeout_s: float = 10.0,
    api: ModuleType | None = None,
) -> LocateResult:
    """Ask Windows where the laptop is: ``(lat, lon)``, ``"off"`` or ``"no_fix"``."""
    global _missing_logged
    if api is None:
        try:
            import winrt.windows.devices.geolocation as api
        except ImportError:
            if not _missing_logged:
                _missing_logged = True
                logging.warning("Local weather: this build has no Windows location API")
            return "no_fix"
    try:
        # A little past the lookup's own timeout, in case WinRT never answers at all.
        return asyncio.run(asyncio.wait_for(_locate(api, accuracy_m, max_age_s, timeout_s), timeout_s + 2))
    except Exception as e:
        logging.warning("Local weather: Windows location lookup failed (%s)", type(e).__name__)
        return "no_fix"


async def _locate(api: ModuleType, accuracy_m: int, max_age_s: int, timeout_s: float) -> LocateResult:
    access = await api.Geolocator.request_access_async()
    if access != api.GeolocationAccessStatus.ALLOWED:
        return "off"
    locator = api.Geolocator()
    locator.desired_accuracy_in_meters = accuracy_m
    if locator.location_status in (api.PositionStatus.DISABLED, api.PositionStatus.NOT_AVAILABLE):
        return "off"
    # pywinrt names the (maximumAge, timeout) overload of GetGeopositionAsync on its own.
    position = await locator.get_geoposition_async_with_age_and_timeout(
        timedelta(seconds=max_age_s), timedelta(seconds=timeout_s)
    )
    coordinate = position.coordinate
    logging.debug("Local weather: Windows location fix, accurate to %.0f m", coordinate.accuracy)
    point = coordinate.point.position
    return point.latitude, point.longitude

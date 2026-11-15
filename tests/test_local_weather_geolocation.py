"""Tests for reading the laptop's position from Windows location, against a fake WinRT module so
nothing here asks Windows where the machine is."""

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.local_weather.geolocation import windows_fix  # noqa: E402


def fake_api(
    access: str = "ALLOWED",
    status: str = "READY",
    position: tuple[float, float] = (-6.17834, 106.63191),
    error: Exception | None = None,
    seen: dict[str, Any] | None = None,
) -> ModuleType:
    """A stand-in for ``winrt.windows.devices.geolocation`` with just what ``windows_fix`` uses."""

    async def _access() -> str:
        return access

    async def _position(max_age: timedelta, timeout: timedelta) -> SimpleNamespace:
        if seen is not None:
            seen.update(max_age=max_age, timeout=timeout)
        if error:
            raise error
        point = SimpleNamespace(position=SimpleNamespace(latitude=position[0], longitude=position[1]))
        return SimpleNamespace(coordinate=SimpleNamespace(accuracy=381.0, point=point))

    class Geolocator:
        request_access_async = staticmethod(_access)

        def __init__(self) -> None:
            self.desired_accuracy_in_meters: int | None = None
            self.location_status = status
            if seen is not None:
                seen["locator"] = self

        def get_geoposition_async_with_age_and_timeout(self, max_age: timedelta, timeout: timedelta, /):
            return _position(max_age, timeout)

    fake = SimpleNamespace(
        Geolocator=Geolocator,
        GeolocationAccessStatus=SimpleNamespace(ALLOWED="ALLOWED"),
        PositionStatus=SimpleNamespace(DISABLED="DISABLED", NOT_AVAILABLE="NOT_AVAILABLE"),
    )
    return cast(ModuleType, fake)


class WindowsFixTests(unittest.TestCase):
    def test_fix_returns_the_position(self):
        self.assertEqual(windows_fix(api=fake_api()), (-6.17834, 106.63191))

    def test_denied_access_is_off(self):
        self.assertEqual(windows_fix(api=fake_api(access="DENIED")), "off")

    def test_disabled_location_is_off(self):
        for status in ("DISABLED", "NOT_AVAILABLE"):
            with self.subTest(status=status):
                self.assertEqual(windows_fix(api=fake_api(status=status)), "off")

    def test_timeout_is_no_fix(self):
        self.assertEqual(windows_fix(api=fake_api(error=OSError(-2147023436, "timeout"))), "no_fix")

    def test_missing_module_is_no_fix(self):
        with mock.patch.dict(sys.modules, {"winrt.windows.devices.geolocation": None}):
            self.assertEqual(windows_fix(), "no_fix")

    def test_requests_accuracy_and_age(self):
        seen: dict[str, Any] = {}
        windows_fix(api=fake_api(seen=seen))
        self.assertEqual(seen["max_age"], timedelta(seconds=600))
        self.assertEqual(seen["timeout"], timedelta(seconds=10))
        self.assertEqual(seen["locator"].desired_accuracy_in_meters, 500)


if __name__ == "__main__":
    unittest.main()

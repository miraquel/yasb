"""WeatherAPI-shaped payloads for the local weather tests: three Jakarta days from Monday 2026-11-02."""

import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtWidgets import QWidget  # noqa: E402

from core.utils.widgets.local_weather.forecast import Forecast, parse_forecast  # noqa: E402

JAKARTA = timezone(timedelta(hours=7))
DAY0 = datetime(2026, 11, 2, tzinfo=JAKARTA)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "local_weather" / "forecast_rajeg.json"


def at(hour: int, minute: int = 0, day: int = 0) -> datetime:
    return DAY0 + timedelta(days=day, hours=hour, minutes=minute)


def rain(start: int, values: list[int]) -> dict[int, int]:
    """Chances keyed by hours after DAY0's midnight, from ``start`` on."""
    return {start + i: v for i, v in enumerate(values)}


def payload(
    chances: dict[int, int] | None = None,
    *,
    code: int = 1003,
    precip: float = 0.0,
    is_day: int = 1,
    alerts: Sequence[str] = (),
) -> dict[str, Any]:
    chances = chances or {}
    days: list[dict[str, Any]] = []
    for d in range(3):
        midnight = DAY0 + timedelta(days=d)
        hours = [
            {
                "time_epoch": int((midnight + timedelta(hours=h)).timestamp()),
                "chance_of_rain": chances.get(24 * d + h, 0),
                "condition": {"code": 1003},
            }
            for h in range(24)
        ]
        days.append({"date": midnight.date().isoformat(), "day": {"mintemp_c": 24.2, "maxtemp_c": 32.4}, "hour": hours})
    return {
        "location": {"name": "Rajeg", "lat": -6.18, "lon": 106.63},
        "current": {
            "temp_c": 32.4,
            "feelslike_c": 38.1,
            "condition": {"code": code},
            "is_day": is_day,
            "wind_kph": 9.0,
            "precip_mm": precip,
        },
        "forecast": {"forecastday": days},
        "alerts": {"alert": [{"headline": h} for h in alerts]},
    }


def forecast(chances: dict[int, int] | None = None, *, fetched: datetime | None = None, **kw: Any) -> Forecast:
    parsed = parse_forecast(payload(chances, **kw), (fetched or at(13, 10)).timestamp())
    assert parsed is not None
    return parsed


def first_ink(label: QWidget) -> int:
    """The first column of ``label``'s own render that differs from its top-left pixel."""
    image = label.grab().toImage()
    ground = image.pixelColor(0, 0)
    for x in range(image.width()):
        if any(image.pixelColor(x, y) != ground for y in range(image.height())):
            return x
    return -1

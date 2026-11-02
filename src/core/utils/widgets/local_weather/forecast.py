"""WeatherAPI ``forecast.json`` read into plain values: the place, the weather now, and each
day's hours. Only the fields the widget uses are kept."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast


@dataclass(frozen=True)
class Hour:
    start: int  # epoch seconds the hour begins (time_epoch)
    chance: int  # chance of rain, 0-100
    code: int  # WeatherAPI condition code


@dataclass(frozen=True)
class Day:
    date: date
    min_temp: float
    max_temp: float
    hours: tuple[Hour, ...]


@dataclass(frozen=True)
class Current:
    temp: float
    feels: float
    code: int
    is_day: bool
    wind_kph: float
    precip_mm: float


@dataclass(frozen=True)
class Forecast:
    place: str
    lat: float
    lon: float
    current: Current
    days: tuple[Day, ...]
    alerts: tuple[str, ...]
    fetched_at: float  # epoch seconds the response arrived


def parse_forecast(payload: dict[str, Any], fetched_at: float) -> Forecast | None:
    """The forecast in ``payload``, or None when it is an error body or is missing a part."""
    try:
        location = payload["location"]
        cur = payload["current"]
        days = payload["forecast"]["forecastday"]
        if not location or not cur or not days:
            return None
        current = Current(
            float(cur["temp_c"]),
            float(cur["feelslike_c"]),
            int(cur["condition"]["code"]),
            bool(cur["is_day"]),
            float(cur["wind_kph"]),
            float(cur["precip_mm"]),
        )
        parsed_days = tuple(
            Day(
                date.fromisoformat(day["date"]),
                float(day["day"]["mintemp_c"]),
                float(day["day"]["maxtemp_c"]),
                tuple(
                    Hour(int(h["time_epoch"]), int(h["chance_of_rain"]), int(h["condition"]["code"]))
                    for h in day.get("hour") or ()
                ),
            )
            for day in days
        )
        return Forecast(
            str(location["name"]),
            float(location["lat"]),
            float(location["lon"]),
            current,
            parsed_days,
            _alerts(payload.get("alerts")),
            fetched_at,
        )
    except KeyError, TypeError, ValueError, AttributeError:
        # An exception escaping here would reach a Qt slot, and YASB's excepthook exits the bar.
        return None


def _alerts(block: object) -> tuple[str, ...]:
    """Alert headlines. Alerts are optional, so a block of an unexpected shape is just none."""
    items = cast(dict[str, object], block).get("alert") if isinstance(block, dict) else None
    if not isinstance(items, list):
        return ()
    headlines: list[str] = []
    for item in cast(list[object], items):
        headline = cast(dict[str, object], item).get("headline") if isinstance(item, dict) else None
        if isinstance(headline, str) and headline:
            headlines.append(headline)
    return tuple(headlines)


def hours_from(forecast: Forecast, now: datetime, count: int) -> list[Hour]:
    """Up to ``count`` hours starting with the one ``now`` falls in, across days."""
    hours = [h for day in forecast.days for h in day.hours]
    ts = now.timestamp()
    for i, hour in enumerate(hours):
        if hour.start <= ts < hour.start + 3600:
            return hours[i : i + count]
    return []

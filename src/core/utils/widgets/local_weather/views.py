"""What the pill and the card show, worked out from the last forecast, where it came from and the
time now. A forecast over three hours old counts as none, so a laptop waking from a long sleep
never shows yesterday's "rain at 15:00"."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.utils.widgets.local_weather.conditions import condition, condition_class, is_raining_now, wmo_code
from core.utils.widgets.local_weather.forecast import Day, Forecast, hours_from
from core.utils.widgets.local_weather.location import Place
from core.utils.widgets.local_weather.rain import (
    STOP_SEARCH_HOURS,
    Bar,
    Hero,
    PillReading,
    Thresholds,
    card_bar,
    day_blocks,
    day_text,
    half_up,
    hero_reading,
    pill_reading,
)

STALE_S = 30 * 60  # the header line turns yellow: refreshes are failing
EXPIRED_S = 3 * 3600  # past this the forecast is not shown at all

NO_DATA = "—"
NO_DATA_ICON = "default"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class PillView:
    condition: str  # state class: sun, night, cloud, rain, storm, none
    icon_key: str  # key into the widget's icons
    reading: PillReading
    placeholders: dict[str, str]


@dataclass(frozen=True)
class DayRow:
    name: str
    bars: tuple[Bar, ...]
    text: str
    range: str


@dataclass(frozen=True)
class SkyInput:
    wmo: int
    wind_kph: float
    temp: float
    lat: float
    lon: float
    fetched_at: float


@dataclass(frozen=True)
class CardView:
    condition: str
    icon_key: str
    title: str
    line: str
    line_state: str  # "", "warn" or "stale"
    temp: str
    feels: str
    hero: Hero
    bars: tuple[Bar, ...]
    axis: tuple[str, ...]
    alert: str
    days: tuple[DayRow, ...]
    sky: SkyInput | None


def usable(forecast: Forecast | None, now: datetime) -> Forecast | None:
    if forecast is None or now.timestamp() - forecast.fetched_at > EXPIRED_S:
        return None
    return forecast


def _deg(value: float) -> str:
    return f"{half_up(value)}°"


def _clock(ts: float, now: datetime) -> str:
    return datetime.fromtimestamp(ts, now.tzinfo).strftime("%H:%M")


def _today(forecast: Forecast, now: datetime) -> Day:
    return next((d for d in forecast.days if d.date == now.date()), forecast.days[0])


def _day_name(day: date, now: datetime) -> str:
    return "Tomorrow" if day == now.date() + timedelta(days=1) else _WEEKDAYS[day.weekday()]


def pill_view(
    forecast: Forecast | None, config_location: str, now: datetime, t: Thresholds, pill_hours: int
) -> PillView:
    f = usable(forecast, now)
    if f is None:
        place = forecast.place if forecast is not None else config_location
        placeholders = {
            "{temp}": NO_DATA,
            "{feels}": NO_DATA,
            "{location}": place,
            "{min_temp}": NO_DATA,
            "{max_temp}": NO_DATA,
            "{condition}": "No forecast",
        }
        return PillView("none", NO_DATA_ICON, pill_reading(None, False, now, t, pill_hours), placeholders)
    icon_key, text = condition(f.current.code, f.current.is_day)
    hours = hours_from(f, now, STOP_SEARCH_HOURS)
    today = _today(f, now)
    placeholders = {
        "{temp}": _deg(f.current.temp),
        "{feels}": _deg(f.current.feels),
        "{location}": f.place,
        "{min_temp}": _deg(today.min_temp),
        "{max_temp}": _deg(today.max_temp),
        "{condition}": text,
    }
    reading = pill_reading(hours, is_raining_now(f.current), now, t, pill_hours)
    return PillView(condition_class(icon_key), icon_key, reading, placeholders)


def header_line(forecast: Forecast | None, place: Place | None, now: datetime) -> tuple[str, str]:
    """The card header's second line, and its state: "" (overlay1), "warn" or "stale" (yellow)."""
    f = usable(forecast, now)
    if f is None:
        if forecast is not None:
            return f"Last forecast {_clock(forecast.fetched_at, now)}", ""
        return "No forecast yet", ""
    if place is not None and place.source == "config":
        if place.reason == "off":
            return "From your config, Windows location is off", "warn"
        return "From your config, no location fix", "warn"
    stale = now.timestamp() - f.fetched_at > STALE_S
    return f"Windows location, updated {_clock(f.fetched_at, now)}", "stale" if stale else ""


def card_view(
    forecast: Forecast | None,
    place: Place | None,
    config_location: str,
    now: datetime,
    t: Thresholds,
    card_hours: int,
) -> CardView:
    """``place`` is where the shown forecast came from, not where the latest attempt went."""
    line, line_state = header_line(forecast, place, now)
    axis = tuple("now" if i == 0 else f"{(now.hour + i) % 24:02d}" if i % 2 == 0 else "" for i in range(card_hours))
    title = forecast.place if forecast is not None else config_location
    f = usable(forecast, now)
    if f is None:
        return CardView(
            "none",
            NO_DATA_ICON,
            title,
            line,
            line_state,
            NO_DATA,
            "",
            hero_reading(None, False, now, t, card_hours),
            (card_bar(None, t),) * card_hours,
            axis,
            "",
            (),
            None,
        )
    icon_key, _ = condition(f.current.code, f.current.is_day)
    hours = hours_from(f, now, STOP_SEARCH_HOURS)
    bars = tuple(card_bar(hours[i].chance if i < len(hours) else None, t) for i in range(card_hours))
    days = tuple(
        DayRow(
            _day_name(d.date, now),
            day_blocks(d, now.tzinfo, t),
            day_text(d, now.tzinfo, t),
            f"{half_up(d.min_temp)}–{half_up(d.max_temp)}°",
        )
        for d in f.days
        if d.date > now.date()
    )[:2]
    return CardView(
        condition_class(icon_key),
        icon_key,
        title,
        line,
        line_state,
        _deg(f.current.temp),
        f"feels {_deg(f.current.feels)}",
        hero_reading(hours, is_raining_now(f.current), now, t, card_hours),
        bars,
        axis,
        f.alerts[0] if f.alerts else "",
        days,
        SkyInput(wmo_code(f.current.code), f.current.wind_kph, f.current.temp, f.lat, f.lon, f.fetched_at),
    )

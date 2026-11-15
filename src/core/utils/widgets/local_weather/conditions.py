"""What a WeatherAPI condition code means here: whether it is raining now, which icon and colour
the pill shows, and which weather the sky draws."""

from core.utils.widgets.local_weather.forecast import Current
from core.widgets.yasb.weather import get_weather

# Rain, drizzle, showers and thunder with rain. The "possible" codes (1063 patchy rain
# possible, 1087 thundery outbreaks possible) are a forecast, not rain falling now.
RAINING_CODES = frozenset(
    {1150, 1153, 1168, 1171, 1180, 1183, 1186, 1189, 1192, 1195, 1198, 1201, 1240, 1243, 1246, 1273, 1276}
)

_CLASS = {
    "sunnyDay": "sun",
    "clearNight": "night",
    "rainyDay": "rain",
    "rainyNight": "rain",
    "thunderstormDay": "storm",
    "thunderstormNight": "storm",
}

# WeatherAPI condition code -> the WMO code the AI cards' sky draws (sky.py).
_WMO = {
    **dict.fromkeys((1000,), 0),
    **dict.fromkeys((1003,), 2),
    **dict.fromkeys((1006, 1009), 3),
    **dict.fromkeys((1030, 1135, 1147), 45),
    1150: 51,
    1153: 53,
    **dict.fromkeys((1072, 1168), 56),
    1171: 57,
    **dict.fromkeys((1063, 1180, 1183), 61),
    **dict.fromkeys((1186, 1189), 63),
    **dict.fromkeys((1192, 1195), 65),
    **dict.fromkeys((1069, 1198, 1204, 1249), 66),
    **dict.fromkeys((1201, 1207, 1252), 67),
    **dict.fromkeys((1066, 1210, 1213), 71),
    **dict.fromkeys((1216, 1219), 73),
    **dict.fromkeys((1114, 1117, 1222, 1225), 75),
    **dict.fromkeys((1237, 1261, 1264), 77),
    1240: 80,
    1243: 81,
    1246: 82,
    1255: 85,
    1258: 86,
    **dict.fromkeys((1087, 1273, 1276, 1279, 1282), 95),
}


def is_raining_now(current: Current) -> bool:
    return current.precip_mm > 0 or current.code in RAINING_CODES


# Rain or thunder "possible" nearby: a forecast, not weather falling here. Shown as a cloud, so
# the pill never pairs a rain icon with a dry strip.
POSSIBLE_CODES = {1063: "Rain possible", 1087: "Thunder possible"}
_CLOUDY = 1003


def condition(code: int, is_day: bool) -> tuple[str, str]:
    """The icon key (the same names as the weather widget's ``icons``) and a short description."""
    if code in POSSIBLE_CODES:
        return get_weather(_CLOUDY, is_day)[0], POSSIBLE_CODES[code]
    return get_weather(code, is_day)


def condition_class(icon_key: str) -> str:
    """The state class that colours the icon: sun, night, rain, storm, or cloud for the rest."""
    return _CLASS.get(icon_key, "cloud")


def wmo_code(code: int) -> int:
    return _WMO.get(code, 3)

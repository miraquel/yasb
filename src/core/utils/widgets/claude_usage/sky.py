"""Clawd's sky: a Qt-free port of clawd-usage-winwidget's backdrop (``lib/sky.ps1``).

A faint sky behind the 5-hour reading that follows the real sunrise and sunset. Its colour
moves through night, dawn, day and dusk, the sun travels an arc by day, and at night the moon
shows its actual phase among twinkling stars. Weather adds clouds drifting with the wind, rain
slanting with it, swaying snow that settles underfoot, fog bands and the odd lightning flash.

Everything is in Clawd's logical units. ``Sky.step`` advances one animation frame and returns a
``SkyFrame`` of rectangles and colours; ``SkyScene`` only scales and paints it.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

Colour = tuple[int, int, int, int]  # (alpha, red, green, blue)
Rect = tuple[float, float, float, float]


def argb(hex_colour: str) -> Colour:
    """``#AARRGGBB`` (or ``#RRGGBB``, opaque) as an (a, r, g, b) tuple."""
    h = hex_colour.lstrip("#")
    if len(h) == 6:
        h = "FF" + h
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))


def mix(a: Colour, b: Colour, k: float) -> Colour:
    """Blend ``a`` toward ``b`` by ``k`` (clamped to 0..1), alpha included."""
    k = min(1.0, max(0.0, k))
    return tuple(round(x + (y - x) * k) for x, y in zip(a, b))


def dim(c: Colour, g: float) -> Colour:
    """Cloud cover ``g``: fade the colour toward its own grey and darken it; alpha is kept."""
    lum = 0.3 * c[1] + 0.59 * c[2] + 0.11 * c[3]
    f = 1 - 0.3 * g
    return (c[0], *(min(255, max(0, round((v + (lum - v) * g) * f))) for v in c[1:]))


# ----- palette -----

# Per phase: the gradient's top and bottom, and how much daylight it stands for.
PALETTE = {
    "night": (argb("#00304A8C"), argb("#1A304A8C"), 0.0),
    "dawn": (argb("#00404E8A"), argb("#33E08A66"), 0.5),
    "day": (argb("#004A8CCB"), argb("#2E6FA8D8"), 1.0),
    "dusk": (argb("#00383070"), argb("#33D86A50"), 0.5),
}
PHASES = ("dawn", "day", "dusk", "night")

SUN_HIGH = argb("#FFFDE68A")
SUN_LOW = argb("#FFFB923C")
SUN_GLOW = argb("#40FDE68A")
MOON_LIT = argb("#FFF1F5F9")
MOON_DARK = argb("#2EE5E7EB")
STAR = argb("#FFF8FAFC")
SNOW_DAY = argb("#80DDE4EC")
SNOW_NIGHT = argb("#50A1A8B5")
CLOUD_DAY = argb("#FFB4B4BC")
CLOUD_NIGHT = argb("#FF5E5E68")
CLOUD_RAIN = argb("#FF52525B")
FOG = argb("#FFE5E7EB")
DROP = argb("#8093C5FD")
FLAKE = argb("#C0E4E4E7")
FLASH = argb("#FFF8FAFC")

# ----- weather -----


@dataclass(frozen=True)
class WeatherKind:
    id: str
    name: str
    cover: float
    fog: bool = False
    storm: bool = False
    rain: int = 0  # drops at this intensity, before scaling to the sky's width
    snow: int = 0


# WMO weather codes, as Open-Meteo reports them. Three codes in a group are light, moderate
# and heavy, and scale the drops or flakes by 0.6 / 1 / 1.35.
_KINDS = (
    ((0,), "clear", "clear", 0.0, {}),
    ((1,), "mostly_clear", "mostly clear", 0.2, {}),
    ((2,), "partly", "partly cloudy", 0.5, {}),
    ((3,), "overcast", "overcast", 0.85, {}),
    ((45, 48), "fog", "fog", 0.7, {"fog": True}),
    ((51, 53, 55), "drizzle", "drizzle", 0.8, {"rain": 6}),
    ((56, 57), "ice_drizzle", "freezing drizzle", 0.8, {"rain": 6}),
    ((61, 63, 65), "rain", "rain", 0.9, {"rain": 12}),
    ((66, 67), "ice_rain", "freezing rain", 0.9, {"rain": 12}),
    ((71, 73, 75), "snow", "snow", 0.85, {"snow": 10}),
    ((77,), "grains", "snow grains", 0.85, {"snow": 8}),
    ((80, 81, 82), "showers", "rain showers", 0.85, {"rain": 16}),
    ((85, 86), "snow_showers", "snow showers", 0.9, {"snow": 14}),
    ((95, 96, 99), "storm", "thunderstorm", 1.0, {"rain": 16, "storm": True}),
)
_INTENSITY = (0.6, 1.0, 1.35)

# One representative code per kind, for previewing a weather that is not happening.
PREVIEW_CODES = {
    "clear": 0,
    "mostly_clear": 1,
    "partly": 2,
    "overcast": 3,
    "fog": 45,
    "drizzle": 53,
    "rain": 63,
    "showers": 81,
    "snow": 73,
    "snow_showers": 85,
    "storm": 95,
}


def weather_kind(code: int) -> WeatherKind:
    for codes, kind_id, name, cover, extra in _KINDS:
        if code not in codes:
            continue
        mul = _INTENSITY[codes.index(code)] if len(codes) == 3 else 1.0
        return WeatherKind(
            kind_id,
            name,
            cover,
            fog=extra.get("fog", False),
            storm=extra.get("storm", False),
            rain=round(extra.get("rain", 0) * mul),
            snow=round(extra.get("snow", 0) * mul),
        )
    return WeatherKind("unknown", f"code {code}", 0.5)


@dataclass
class Weather:
    code: int
    wind: float  # km/h, as Open-Meteo reports it
    temp: float | None = None  # °C
    at: float = 0.0  # epoch seconds it was fetched


WEATHER_FRESH_S = 3 * 3600
FORCED_WIND = 12.0
CALM_WIND = 8.0

# ----- sun and moon -----

DEFAULT_SUN = (420.0, 1140.0)  # 07:00 and 19:00, for a sky that has no location


def sun_times(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Sunrise and sunset for ``when``'s date, in minutes after local midnight (NOAA formulas).

    ``when`` must be timezone-aware; its UTC offset is what "local" means.
    """
    gm = 2 * math.pi / 365 * (when.timetuple().tm_yday - 0.5)
    eq = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gm)
        - 0.032077 * math.sin(gm)
        - 0.014615 * math.cos(2 * gm)
        - 0.040849 * math.sin(2 * gm)
    )
    dec = (
        0.006918
        - 0.399912 * math.cos(gm)
        + 0.070257 * math.sin(gm)
        - 0.006758 * math.cos(2 * gm)
        + 0.000907 * math.sin(2 * gm)
        - 0.002697 * math.cos(3 * gm)
        + 0.00148 * math.sin(3 * gm)
    )
    la = math.radians(lat)
    c = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(dec)) - math.tan(la) * math.tan(dec)
    # Polar day or night: the sun never sets or never rises. Clamp to a sliver of either.
    c = max(-0.999, min(0.999, c))
    ha = math.degrees(math.acos(c))
    offset = when.utcoffset()
    tz = offset.total_seconds() / 60 if offset is not None else 0.0
    sunrise = (720 - 4 * (lon + ha) - eq + tz) % 1440
    sunset = (720 - 4 * (lon - ha) - eq + tz) % 1440
    return sunrise, sunset


SYNODIC_MONTH = 29.530588853
_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)


def moon_age(when: datetime) -> float:
    """Days since the last new moon, from the mean synodic month."""
    days = (when.astimezone(UTC) - _NEW_MOON).total_seconds() / 86400
    return days % SYNODIC_MONTH


def moon_rows(age: float, southern: bool = False, n: int = 7) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The moon as a pixel disc: (lit rows, dark rows), ``#`` for a set pixel.

    A pixel is lit on the bright side of the terminator ``u = cos(θ)·√(1-v²)``. South of the
    equator the picture is mirrored, so a waxing moon is lit on the left.
    """
    th = 2 * math.pi * age / SYNODIC_MONTH
    k = math.cos(th)
    r = n / 2
    lit, dark = [], []
    for y in range(n):
        a, b = [], []
        for x in range(n):
            u = (x + 0.5 - r) / r
            v = (y + 0.5 - r) / r
            if southern:
                u = -u
            inside = u * u + v * v <= 1.05
            t = k * math.sqrt(max(0.0, 1 - v * v))
            on = inside and (u > t if th < math.pi else u < -t)
            a.append("#" if on else ".")
            b.append("#" if inside and not on else ".")
        lit.append("".join(a))
        dark.append("".join(b))
    return tuple(lit), tuple(dark)


# ----- sprites -----

SUN_ROWS = ("..###..", ".#####.", "#######", "#######", "#######", ".#####.", "..###..")
SUN_PX = 1.4
SUN_HALF = len(SUN_ROWS) * SUN_PX / 2
GLOW_RADIUS = 10.0
MOON_PX = 1.3
MOON_HALF = 7 * MOON_PX / 2
CLOUD_SHAPES = (
    ("....###.....", "..#######...", ".##########.", "############"),
    ("..###...", ".######.", "########"),
    ("...##.##..", ".########.", "##########"),
)
CLOUD_PX = 2.0
STAR_SIZE = 1.2
DROP_W, DROP_H = 1.0, 3.5
FLAKE_SIZE = 1.6
GROUND_H = 1.5
FOG_H = 3.0

STARS = 20
CLOUDS = 9
FOG_BANDS = 3
DROPS = 40
FLAKES = 34

# Weather counts are tuned for a sky about this wide; a wider one gets proportionally more.
BASE_WIDTH = 140.0
# The lightning flash, frame by frame (played from the end): sometimes it strikes twice.
FLASH_STEPS = (0.0, 0.18, 0.05, 0.0, 0.25, 0.1, 0.04)
FLASH_CHANCE = 140  # one frame in this many, during a storm


def pixel_rects(rows, px: float, dx: float = 0.0, dy: float = 0.0) -> tuple[Rect, ...]:
    """Rows of ``#`` / ``.`` as rectangles, one per horizontal run."""
    rects = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x] != "#":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == "#":
                x += 1
            rects.append((dx + start * px, dy + y * px, (x - start) * px, px))
    return tuple(rects)


def arc_point(p: float, w: float, h: float) -> tuple[float, float] | None:
    """Centre of a sun or moon ``p`` of the way across its arc, or None once it has set."""
    if p < -0.06 or p > 1.06:
        return None
    alt = math.sin(math.pi * p)
    return 7 + p * (w - 14), h + 3 - alt * (h - 12)


@dataclass
class Sprite:
    """One thing to paint. ``kind`` is ``rects``, ``glow`` (a soft disc in ``rects[0]``) or
    ``fog`` (a band that fades out at both ends)."""

    kind: str
    rects: tuple[Rect, ...]
    colour: Colour
    opacity: float = 1.0


@dataclass
class SkyFrame:
    top: Colour
    bottom: Colour
    sprites: list[Sprite] = field(default_factory=list)


@dataclass
class _Cloud:
    rows: tuple[str, ...]
    width: float
    x: float
    fy: float
    speed: float
    fade: float = 0.0


@dataclass
class _Drop:
    x: float = 0.0
    y: float = -99.0
    v: float = 0.0
    phase: float = 0.0


class Sky:
    """The sky's state between frames: where the clouds, drops and flakes are, and the colours
    worked out for the current minute and weather."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        rnd = self._rng.random
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.weather_enabled = True
        self.weather: Weather | None = None
        self.force_phase: str | None = None
        self.force_weather: int | None = None

        self.tick = 0
        self.kind = weather_kind(0)
        self.light = 0.0
        self._w = 0.0
        self._h = 0.0
        self._key: tuple | None = None
        self._moon_key: tuple | None = None
        self._moon = ((), ())
        self._top = PALETTE["night"][0]
        self._bottom = PALETTE["night"][1]
        self._fixed: list[Sprite] = []  # sun and moon: placed once a minute, not every frame
        self._cloud_colour = CLOUD_DAY
        self._ground: Sprite | None = None
        self._star_opacity = 0.0
        self._counts = (0, 0, 0)  # clouds, drops, flakes
        self._flash = 0

        self._stars = [(rnd(), rnd() * 0.6) for _ in range(STARS)]
        self._clouds = []
        for i in range(CLOUDS):
            rows = CLOUD_SHAPES[i % len(CLOUD_SHAPES)]
            self._clouds.append(_Cloud(rows, len(rows[0]) * CLOUD_PX, -1.0, 0.05 + 0.3 * rnd(), 0.7 + 0.6 * rnd()))
        self._fog = [[rnd(), 0.42 + 0.2 * i] for i in range(FOG_BANDS)]
        self._drops = [_Drop() for _ in range(DROPS)]
        self._flakes = [_Drop() for _ in range(FLAKES)]

    # ------------------------------------------------------------------ inputs ----
    def sun_times(self, now: datetime) -> tuple[float, float]:
        if self.latitude is None or self.longitude is None:
            return DEFAULT_SUN
        return sun_times(self.latitude, self.longitude, now)

    def live_weather(self, now: datetime) -> Weather | None:
        """The weather to draw: a preview if one is forced, else the last reading while fresh."""
        if self.force_weather is not None:
            return Weather(self.force_weather, FORCED_WIND)
        wx = self.weather
        if wx is not None and now.timestamp() - wx.at < WEATHER_FRESH_S:
            return wx
        return None

    def describe(self, now: datetime, clock) -> list[str]:
        """Tooltip lines: the weather, then sunrise and sunset. ``clock`` formats minutes."""
        lines = []
        if self.force_phase or self.force_weather is not None:
            what = [self.force_phase] if self.force_phase else []
            if self.force_weather is not None:
                what.append(weather_kind(self.force_weather).name)
            lines.append("preview · " + ", ".join(what))
        else:
            wx = self.live_weather(now)
            if wx is not None:
                name = weather_kind(wx.code).name
                if wx.temp is not None:
                    temp = round(wx.temp)
                    name = f"{'+' if temp > 0 else ''}{temp}°, {name}"
                lines.append(name)
                lines.append(f"wind {round(wx.wind / 3.6)} m/s")
            elif self.weather_enabled and self.latitude is not None and self.longitude is not None:
                lines.append("weather: no data")
        sunrise, sunset = self.sun_times(now)
        line = f"sunrise {clock(sunrise)} · sunset {clock(sunset)}"
        if self.latitude is None or self.longitude is None:
            line += " (no location set)"
        lines.append(line)
        return lines

    # ---------------------------------------------------------------- stepping ----
    def step(self, w: float, h: float, now: datetime | None = None) -> SkyFrame:
        now = now or datetime.now().astimezone()
        self.tick += 1
        if w <= 0 or h <= 0:
            return SkyFrame(self._top, self._bottom)
        if (w, h) != (self._w, self._h):
            self._w, self._h = w, h
            self._key = None
            for c in self._clouds:
                if c.x < 0:
                    c.x = self._rng.random() * w

        sunrise, sunset = self.sun_times(now)
        if sunset <= sunrise:
            sunset += 1440
        t = now.hour * 60 + now.minute + now.second / 60
        t = {
            "dawn": sunrise - 10,
            "day": (sunrise + sunset) / 2,
            "dusk": sunset + 10,
            "night": 0.0,
        }.get(self.force_phase or "", t)
        wx = self.live_weather(now)
        code = wx.code if wx is not None else 0
        wind = wx.wind if wx is not None else CALM_WIND

        # Colours, sun and moon change slowly: work them out once a minute or on new weather.
        key = (int(t), code, w, h)
        if key != self._key:
            self._key = key
            self._recompute(t, sunrise, sunset, weather_kind(code), now)

        frame = SkyFrame(self._top, self._bottom)
        self._step_stars(frame)
        frame.sprites.extend(self._fixed)
        self._step_clouds(frame, wind)
        self._step_fog(frame)
        slant = min(1.2, wind / 25.0)
        self._step_rain(frame, slant)
        self._step_snow(frame, slant)
        if self._ground is not None:
            frame.sprites.append(self._ground)
        self._step_flash(frame)
        return frame

    def _recompute(self, t: float, sunrise: float, sunset: float, kind: WeatherKind, now: datetime) -> None:
        w, h = self._w, self._h
        self.kind = kind
        stops = (
            (sunrise - 80, "night"),
            (sunrise - 10, "dawn"),
            (sunrise + 70, "day"),
            (sunset - 70, "day"),
            (sunset + 10, "dusk"),
            (sunset + 80, "night"),
        )
        a = b = PALETTE["night"]
        k = 0.0
        for (t0, p0), (t1, p1) in zip(stops, stops[1:]):
            if t0 <= t < t1:
                a, b = PALETTE[p0], PALETTE[p1]
                k = (t - t0) / (t1 - t0)
                break
        self.light = a[2] + (b[2] - a[2]) * k
        grey = kind.cover * 0.9
        self._top = dim(mix(a[0], b[0], k), grey)
        self._bottom = dim(mix(a[1], b[1], k), grey)

        # Snow has settled: a thin strip underfoot.
        self._ground = None
        if kind.snow > 0:
            colour = mix(SNOW_NIGHT, SNOW_DAY, self.light)
            self._ground = Sprite("rects", ((0.0, h - GROUND_H, w, GROUND_H),), colour)
        cloud = mix(CLOUD_NIGHT, CLOUD_DAY, self.light)
        if kind.rain or kind.storm:
            cloud = mix(cloud, CLOUD_RAIN, 0.55)
        self._cloud_colour = cloud

        self._fixed = []
        visible = max(0.0, 1 - kind.cover * 1.15)
        # The moon goes first so the sun's glow lies over it at the moments both are up.
        night_len = sunrise + 1440 - sunset
        q = ((t - sunset + 1440) % 1440) / night_len
        moon = arc_point(q, w, h)
        if moon is not None and visible > 0:
            lit, dark = self._moon_rows(now)
            ox, oy = moon[0] - MOON_HALF, moon[1] - MOON_HALF
            self._fixed.append(Sprite("rects", pixel_rects(dark, MOON_PX, ox, oy), MOON_DARK, visible))
            self._fixed.append(Sprite("rects", pixel_rects(lit, MOON_PX, ox, oy), MOON_LIT, visible))
        # The sun by day, along the arc from sunrise to sunset, orange near the horizon.
        p = (t - sunrise) / (sunset - sunrise)
        sun = arc_point(p, w, h)
        if sun is not None and visible > 0:
            cx, cy = sun
            glow = ((cx - GLOW_RADIUS, cy - GLOW_RADIUS, 2 * GLOW_RADIUS, 2 * GLOW_RADIUS),)
            self._fixed.append(Sprite("glow", glow, SUN_GLOW, visible))
            colour = mix(SUN_LOW, SUN_HIGH, math.sin(math.pi * p) * 1.6)
            self._fixed.append(
                Sprite("rects", pixel_rects(SUN_ROWS, SUN_PX, cx - SUN_HALF, cy - SUN_HALF), colour, visible)
            )

        self._star_opacity = (1 - self.light * 2) * max(0.0, 1 - kind.cover * 1.4)
        density = max(1.0, w / BASE_WIDTH)
        self._counts = (
            min(CLOUDS, round(kind.cover * 5 * density)),
            min(DROPS, round(kind.rain * density)),
            min(FLAKES, round(kind.snow * density)),
        )

    def _moon_rows(self, now: datetime):
        age = moon_age(now)
        southern = self.latitude is not None and self.latitude < 0
        key = (round(age * 2), southern)
        if key != self._moon_key:
            self._moon_key = key
            self._moon = moon_rows(age, southern)
        return self._moon

    def _step_stars(self, frame: SkyFrame) -> None:
        if self._star_opacity <= 0:
            return
        w, h = self._w, self._h
        for i, (fx, fy) in enumerate(self._stars):
            twinkle = 0.55 + 0.45 * math.sin(self.tick / 7.0 + i * 1.7)
            rect = (float(round(fx * (w - 2))), float(round(2 + fy * h)), STAR_SIZE, STAR_SIZE)
            frame.sprites.append(Sprite("rects", (rect,), STAR, self._star_opacity * twinkle))

    def _step_clouds(self, frame: SkyFrame, wind: float) -> None:
        """Clouds drift with the wind; ones no longer wanted fade out, newly wanted ones fade in."""
        w, h = self._w, self._h
        drift = 0.04 + wind / 350.0
        for i, c in enumerate(self._clouds):
            want = 1.0 if i < self._counts[0] else 0.0
            c.fade += max(-0.03, min(0.03, want - c.fade))
            if c.fade <= 0:
                continue
            c.x += drift * c.speed
            if c.x > w:
                c.x = -c.width
                c.fy = 0.05 + 0.3 * self._rng.random()
            rects = pixel_rects(c.rows, CLOUD_PX, round(c.x), round(c.fy * h))
            frame.sprites.append(Sprite("rects", rects, self._cloud_colour, 0.65 * c.fade))

    def _step_fog(self, frame: SkyFrame) -> None:
        """Fog: translucent bands crawling slowly across."""
        if not self.kind.fog:
            return
        w, h = self._w, self._h
        for band in self._fog:
            band[0] = (band[0] + 0.0015) % 1.6
            opacity = 0.14 + 0.05 * math.sin(self.tick / 20.0 + band[1] * 10)
            rect = ((band[0] - 0.6) * w, band[1] * h, w * 0.6, FOG_H)
            frame.sprites.append(Sprite("fog", (rect,), FOG, opacity))

    def _step_rain(self, frame: SkyFrame, slant: float) -> None:
        """Rain falls fast and slants with the wind."""
        w, h = self._w, self._h
        rnd = self._rng.random
        rects = []
        for i, d in enumerate(self._drops):
            if i >= self._counts[1]:
                d.y = -99.0
                continue
            if d.y < -50 or d.y > h:
                d.x = rnd() * (w + 10) - 10
                d.y = rnd() * h if d.y < -50 else -4.0
                d.v = 3.5 + 1.5 * rnd()
            d.y += d.v
            d.x += slant
            rects.append((d.x, d.y, DROP_W, DROP_H))
        if rects:
            frame.sprites.append(Sprite("rects", tuple(rects), DROP))

    def _step_snow(self, frame: SkyFrame, slant: float) -> None:
        """Snow falls slowly and sways."""
        w, h = self._w, self._h
        rnd = self._rng.random
        rects = []
        for i, f in enumerate(self._flakes):
            if i >= self._counts[2]:
                f.y = -99.0
                continue
            if f.y < -50 or f.y > h:
                f.x = rnd() * w
                f.y = rnd() * h if f.y < -50 else -2.0
                f.v = 0.3 + 0.35 * rnd()
                f.phase = rnd() * 6.28
            f.y += f.v
            x = f.x + 1.5 * math.sin(self.tick / 9.0 + f.phase) + slant * f.y / 4
            rects.append((x, f.y, FLAKE_SIZE, FLAKE_SIZE))
        if rects:
            frame.sprites.append(Sprite("rects", tuple(rects), FLAKE))

    def _step_flash(self, frame: SkyFrame) -> None:
        """A thunderstorm now and then lights the whole sky, sometimes twice in a row."""
        if self.kind.storm and self._flash <= 0 and self._rng.randrange(FLASH_CHANCE) == 0:
            self._flash = len(FLASH_STEPS)
        if self._flash > 0:
            opacity = FLASH_STEPS[self._flash - 1]
            self._flash -= 1
            if opacity > 0:
                frame.sprites.append(Sprite("rects", ((0.0, 0.0, self._w, self._h),), FLASH, opacity))

"""Tests for the Claude popup's sky: sun and moon maths, weather kinds, the weather parsers and
the Qt-free ``Sky`` model, driven with a seeded RNG and fixed times so nothing depends on the
real clock, the real weather or the network.
"""

import random
import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.widgets.claude_usage import sky  # noqa: E402
from core.utils.widgets.claude_usage.sky import (  # noqa: E402
    MOON_LIT,
    STAR,
    Sky,
    Weather,
    arc_point,
    moon_age,
    moon_rows,
    pixel_rects,
    sun_times,
    weather_kind,
)
from core.widgets.services.claude_usage.weather import met_no_code, parse_met_no, parse_open_meteo  # noqa: E402

JAKARTA = timezone(timedelta(hours=7))
RAJEG = (-6.1783, 106.6319)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 17, hour, minute, tzinfo=JAKARTA)


def make_sky(code: int | None = None, when: datetime | None = None, seed: int = 1) -> Sky:
    s = Sky(random.Random(seed))
    s.latitude, s.longitude = RAJEG
    if code is not None:
        s.weather = Weather(code, 15.0, 29.0, (when or at(12)).timestamp())
    return s


def run(s: Sky, when: datetime, frames: int = 120, w: float = 220, h: float = 50):
    frame = None
    for _ in range(frames):
        frame = s.step(w, h, when)
    return frame


def colours(frame) -> set:
    return {sprite.colour for sprite in frame.sprites}


class SunMoonTests(unittest.TestCase):
    def test_sunrise_and_sunset_match_the_almanac(self):
        # Jakarta area, 17 Oct: sunrise about 05:31, sunset about 17:45.
        sunrise, sunset = sun_times(*RAJEG, at(12))
        self.assertAlmostEqual(sunrise, 5 * 60 + 31, delta=4)
        self.assertAlmostEqual(sunset, 17 * 60 + 45, delta=4)

    def test_polar_night_still_gives_a_sliver_of_day(self):
        sunrise, sunset = sun_times(78.2, 15.6, datetime(2026, 12, 21, 12, tzinfo=timezone(timedelta(hours=1))))
        self.assertLess(0, (sunset - sunrise) % 1440)

    def test_moon_age_follows_the_synodic_month(self):
        self.assertAlmostEqual(moon_age(datetime(2000, 1, 6, 18, 14, tzinfo=UTC)), 0, places=3)
        # Full moon of 26 Oct 2026; the mean month is within a day of the real one.
        self.assertAlmostEqual(moon_age(datetime(2026, 10, 26, 4, 12, tzinfo=UTC)), 14.77, delta=1.0)

    def test_new_and_full_moon(self):
        lit, dark = moon_rows(0.0)
        self.assertNotIn("#", "".join(lit))
        lit, dark = moon_rows(sky.SYNODIC_MONTH / 2 - 0.01)
        self.assertNotIn("#", "".join(dark))

    def test_waxing_moon_is_lit_on_the_right_in_the_north_and_left_in_the_south(self):
        def lit_side(rows):
            right = sum(row[4:].count("#") for row in rows)
            left = sum(row[:3].count("#") for row in rows)
            return "right" if right > left else "left"

        self.assertEqual(lit_side(moon_rows(5.0)[0]), "right")
        self.assertEqual(lit_side(moon_rows(5.0, southern=True)[0]), "left")

    def test_arc_rises_peaks_and_sets(self):
        self.assertIsNone(arc_point(-0.1, 200, 50))
        self.assertIsNone(arc_point(1.1, 200, 50))
        rise, noon = arc_point(0.0, 200, 50), arc_point(0.5, 200, 50)
        self.assertLess(noon[1], rise[1])  # higher on screen means a smaller y
        self.assertAlmostEqual(noon[0], 100)

    def test_pixel_rows_become_one_rect_per_run(self):
        self.assertEqual(pixel_rects(("##.#",), 2.0), ((0.0, 0.0, 4.0, 2.0), (6.0, 0.0, 2.0, 2.0)))


class WeatherKindTests(unittest.TestCase):
    def test_intensity_scales_light_moderate_heavy(self):
        self.assertEqual([weather_kind(c).rain for c in (61, 63, 65)], [7, 12, 16])
        self.assertEqual(weather_kind(75).snow, 14)

    def test_flags_and_unknown_codes(self):
        self.assertTrue(weather_kind(45).fog)
        self.assertTrue(weather_kind(99).storm)
        self.assertEqual(weather_kind(0).cover, 0.0)
        self.assertEqual(weather_kind(42).name, "code 42")

    def test_met_no_symbols_map_to_wmo_codes(self):
        self.assertEqual(met_no_code("lightrainshowers_day"), 80)
        self.assertEqual(met_no_code("heavysnow"), 75)
        self.assertEqual(met_no_code("rainandthunder"), 95)
        self.assertEqual(met_no_code("partlycloudy_night"), 2)
        self.assertEqual(met_no_code("clearsky_polartwilight"), 0)
        self.assertEqual(met_no_code("something_new"), 3)

    def test_parsers_read_the_current_conditions(self):
        self.assertEqual(
            parse_open_meteo({"current": {"weather_code": 3, "temperature_2m": 30.5, "wind_speed_10m": 12}}),
            {"code": 3, "temp": 30.5, "wind": 12.0},
        )
        met = {
            "properties": {
                "timeseries": [
                    {
                        "data": {
                            "instant": {"details": {"air_temperature": 28.0, "wind_speed": 5.0}},
                            "next_1_hours": {"summary": {"symbol_code": "rain"}},
                        }
                    }
                ]
            }
        }
        self.assertEqual(parse_met_no(met), {"code": 63, "temp": 28.0, "wind": 18.0})

    def test_parsers_reject_anything_else(self):
        for payload in (None, {}, {"current": {}}, {"properties": {"timeseries": []}}):
            self.assertIsNone(parse_open_meteo(payload))
            self.assertIsNone(parse_met_no(payload))


class SkyTests(unittest.TestCase):
    def test_clear_noon_has_the_sun_and_no_stars(self):
        frame = run(make_sky(0), at(12))
        self.assertEqual(make_sky(0).sun_times(at(12)), sun_times(*RAJEG, at(12)))
        kinds = [s.kind for s in frame.sprites]
        self.assertIn("glow", kinds)
        self.assertNotIn(STAR, colours(frame))

    def test_clear_night_has_the_moon_and_stars(self):
        frame = run(make_sky(0, at(23)), at(23))
        self.assertIn(STAR, colours(frame))
        self.assertIn(MOON_LIT, colours(frame))

    def test_gradient_brightens_from_night_to_day(self):
        night, day = make_sky(0, at(23)), make_sky(0)
        run(night, at(23), 2)
        run(day, at(12), 2)
        self.assertEqual(night.light, 0.0)
        self.assertEqual(day.light, 1.0)

    def test_cloud_cover_dims_the_sun_and_hides_the_stars(self):
        # Overcast leaves only a smudge of sun, as in the original; rain hides it outright.
        glow = [s for s in run(make_sky(3), at(12)).sprites if s.kind == "glow"]
        self.assertLess(glow[0].opacity, 0.05)
        self.assertNotIn("glow", [s.kind for s in run(make_sky(63), at(12)).sprites])
        self.assertNotIn(STAR, colours(run(make_sky(3, at(23)), at(23))))

    def test_rain_falls_and_snow_settles(self):
        rain = run(make_sky(63), at(12))
        self.assertIn(sky.DROP, colours(rain))
        snow = run(make_sky(73), at(12))
        self.assertIn(sky.FLAKE, colours(snow))
        ground = [s for s in snow.sprites if s.rects[0][1] == 50 - sky.GROUND_H and s.rects[0][2] == 220]
        self.assertTrue(ground)

    def test_fog_draws_bands(self):
        frame = run(make_sky(45), at(12))
        self.assertEqual(sum(s.kind == "fog" for s in frame.sprites), sky.FOG_BANDS)

    def test_a_storm_flashes_now_and_then(self):
        s = make_sky(95)
        flashes = 0
        for _ in range(3000):
            frame = s.step(220, 50, at(12))
            flashes += any(sp.colour == sky.FLASH and sp.rects[0][2] == 220 for sp in frame.sprites)
        self.assertGreater(flashes, 0)

    def test_stale_weather_is_dropped(self):
        s = make_sky(63, at(8))
        self.assertIsNone(s.live_weather(at(12)))
        self.assertIsNotNone(s.live_weather(at(10)))

    def test_preview_overrides_clock_and_weather(self):
        s = make_sky(0)
        s.force_phase, s.force_weather = "night", sky.PREVIEW_CODES["snow"]
        frame = run(s, at(12))
        self.assertEqual(s.light, 0.0)
        self.assertIn(sky.FLAKE, colours(frame))
        self.assertEqual(s.describe(at(12), str)[0], "preview · night, snow")

    def test_wider_skies_get_more_weather(self):
        narrow, wide = make_sky(63), make_sky(63)
        run(narrow, at(12), 2, w=140)
        run(wide, at(12), 2, w=280)
        self.assertGreater(wide._counts[1], narrow._counts[1])

    def test_tooltip_lines(self):
        def clock(m):
            return f"{int(m) // 60:02d}:{int(m) % 60:02d}"

        s = make_sky(0)
        self.assertEqual(s.describe(at(12), clock)[:2], ["+29°, clear", "wind 4 m/s"])
        s.weather = None
        self.assertEqual(s.describe(at(12), clock)[0], "weather: no data")
        s.latitude = s.longitude = None
        self.assertEqual(s.describe(at(12), clock), ["sunrise 07:00 · sunset 19:00 (no location set)"])


if __name__ == "__main__":
    unittest.main()

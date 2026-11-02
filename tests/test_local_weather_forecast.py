"""Tests for reading WeatherAPI forecasts: parsing, the hours from now on, and what a condition
code means (raining now, the pill's colour, the sky's weather)."""

import json
import unittest
from datetime import date

from local_weather_payloads import FIXTURE, at, forecast, payload, rain

from core.utils.widgets.local_weather.conditions import condition, condition_class, is_raining_now, wmo_code
from core.utils.widgets.local_weather.forecast import Current, hours_from, parse_forecast


class ParseTests(unittest.TestCase):
    def test_recorded_payload_parses(self):
        f = parse_forecast(json.loads(FIXTURE.read_text("utf-8")), 0.0)
        self.assertEqual(len(f.days), 3)
        self.assertTrue(all(len(d.hours) == 24 for d in f.days))
        starts = [h.start for d in f.days for h in d.hours]
        self.assertEqual(starts, list(range(starts[0], starts[0] + 72 * 3600, 3600)))
        self.assertTrue(f.place)

    def test_synthetic_payload_fields(self):
        f = parse_forecast(payload(rain(13, [70]), alerts=("Flood warning",)), 123.0)
        self.assertEqual((f.place, f.lat, f.lon), ("Rajeg", -6.18, 106.63))
        self.assertEqual(f.current, Current(32.4, 38.1, 1003, True, 9.0, 0.0))
        self.assertEqual(f.days[0].date, date(2026, 11, 2))
        self.assertEqual((f.days[0].min_temp, f.days[0].max_temp), (24.2, 32.4))
        self.assertEqual(f.days[0].hours[13].chance, 70)
        self.assertEqual(f.alerts, ("Flood warning",))
        self.assertEqual(f.fetched_at, 123.0)

    def test_payload_missing_forecast_is_rejected(self):
        broken = [
            {},
            {"error": {"code": 1006, "message": "No matching location found."}},
            {**payload(), "forecast": {}},
            {**payload(), "current": {}},
        ]
        for data in broken:
            with self.subTest(data=list(data)):
                self.assertIsNone(parse_forecast(data, 0.0))

    def test_malformed_alerts_are_ignored(self):
        """An escaped exception here would reach a Qt slot, and YASB's excepthook exits the bar."""
        for alerts in (["oops"], {"alert": ["oops"]}, {"alert": "oops"}, "oops"):
            with self.subTest(alerts=alerts):
                data = payload(rain(13, [70]))
                data["alerts"] = alerts
                f = parse_forecast(data, 0.0)
                self.assertIsNotNone(f)
                self.assertEqual(f.alerts, ())

    def test_day_with_no_hours_parses_empty(self):
        data = payload()
        data["forecast"]["forecastday"][2]["hour"] = []
        self.assertEqual(parse_forecast(data, 0.0).days[2].hours, ())


class HoursTests(unittest.TestCase):
    def test_hours_start_at_the_current_hour(self):
        hours = hours_from(forecast(), at(13, 10), 12)
        self.assertEqual(len(hours), 12)
        self.assertEqual(hours[0].start, at(13).timestamp())

    def test_hours_cross_midnight(self):
        self.assertEqual(hours_from(forecast(), at(20), 12)[-1].start, at(7, day=1).timestamp())

    def test_hours_stop_where_the_data_ends(self):
        self.assertEqual(len(hours_from(forecast(), at(20, day=2), 12)), 4)

    def test_no_current_hour_gives_nothing(self):
        self.assertEqual(hours_from(forecast(), at(0, day=3), 6), [])


def current(precip: float, code: int) -> Current:
    return Current(30.0, 33.0, code, True, 5.0, precip)


class ConditionTests(unittest.TestCase):
    def test_raining_now(self):
        for precip, code in ((0.1, 1003), (0, 1189), (0, 1201), (0, 1276)):
            with self.subTest(precip=precip, code=code):
                self.assertTrue(is_raining_now(current(precip, code)))
        for precip, code in ((0, 1063), (0, 1087), (0, 1003)):
            with self.subTest(precip=precip, code=code):
                self.assertFalse(is_raining_now(current(precip, code)))

    def test_condition_class(self):
        expected = {
            (1000, True): "sun",
            (1000, False): "night",
            (1003, True): "cloud",
            (1135, True): "cloud",
            (1213, True): "cloud",
            (9999, True): "cloud",
            (1183, False): "rain",
            (1276, True): "storm",
        }
        for (code, day), cls in expected.items():
            with self.subTest(code=code, day=day):
                self.assertEqual(condition_class(condition(code, day)[0]), cls)

    def test_possible_rain_shows_a_cloud(self):
        """'Patchy rain possible' isn't rain falling; a rain icon over a dry strip needs decoding."""
        for code in (1063, 1087):
            with self.subTest(code=code):
                self.assertEqual(condition(code, True)[0], "cloudyDay")
                self.assertEqual(condition(code, False)[0], "cloudyNight")
                self.assertEqual(condition_class(condition(code, True)[0]), "cloud")

    def test_wmo_mapping(self):
        table = {
            (1000,): 0,
            (1003,): 2,
            (1006, 1009): 3,
            (1030, 1135, 1147): 45,
            (1150,): 51,
            (1153,): 53,
            (1072, 1168): 56,
            (1171,): 57,
            (1063, 1180, 1183): 61,
            (1186, 1189): 63,
            (1192, 1195): 65,
            (1069, 1198, 1204, 1249): 66,
            (1201, 1207, 1252): 67,
            (1066, 1210, 1213): 71,
            (1216, 1219): 73,
            (1114, 1117, 1222, 1225): 75,
            (1237, 1261, 1264): 77,
            (1240,): 80,
            (1243,): 81,
            (1246,): 82,
            (1255,): 85,
            (1258,): 86,
            (1087, 1273, 1276, 1279, 1282): 95,
        }
        for codes, wmo in table.items():
            for code in codes:
                with self.subTest(code=code):
                    self.assertEqual(wmo_code(code), wmo)
        self.assertEqual(wmo_code(9999), 3)


if __name__ == "__main__":
    unittest.main()

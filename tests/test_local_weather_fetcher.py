"""Tests for the fetcher's decisions: the request URL, what counts as a forecast, the one-minute
retry, and not stacking lookups. Nothing here touches the network or Windows location."""

import unittest

from local_weather_payloads import payload
from PyQt6.QtWidgets import QApplication

from core.utils.widgets.local_weather.location import LocationTracker, Place
from core.widgets.services.local_weather.fetcher import BUSY_TIMEOUT_S, LocalWeatherFetcher, build_url

APP = QApplication.instance() or QApplication([])
PLACE = Place("-6.18,106.63", "windows", "")


def no_locate():
    raise AssertionError("the tests never look the laptop up")


class FetcherTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = LocalWeatherFetcher(None, "KEY", LocationTracker("Example Town"), no_locate, 600_000)
        self.finished, self.failed = [], []
        self.fetcher.finished.connect(lambda data, place: self.finished.append(place))
        self.fetcher.failed.connect(self.failed.append)

    def tearDown(self):
        self.fetcher.deleteLater()

    def test_build_url(self):
        self.assertEqual(
            build_url("KEY", "-6.18,106.63"),
            "https://api.weatherapi.com/v1/forecast.json?key=KEY&q=-6.18%2C106.63&days=3&aqi=no&alerts=yes",
        )

    def test_good_payload_finishes(self):
        self.fetcher._busy_since = 1.0
        self.fetcher._on_payload(payload(), PLACE)
        self.assertEqual((self.finished, self.failed), ([PLACE], []))
        self.assertFalse(self.fetcher._retry_timer.isActive())
        self.assertIsNone(self.fetcher._busy_since)

    def test_error_payload_fails_and_retries_in_a_minute(self):
        for data in ({"error": {"code": 2006, "message": "API key is invalid."}}, None):
            with self.subTest(data=data):
                self.fetcher._busy_since = 1.0
                self.fetcher._on_payload(data, PLACE)
                self.assertEqual(self.failed[-1], PLACE)
                self.assertTrue(self.fetcher._retry_timer.isActive())
                self.assertEqual(self.fetcher._retry_timer.interval(), 60_000)
                self.assertIsNone(self.fetcher._busy_since)
        self.assertEqual(self.finished, [])

    def test_refresh_skips_while_busy_but_not_forever(self):
        calls = []
        self.fetcher._start_locate = lambda token: calls.append(token)
        self.fetcher.refresh()
        self.fetcher.refresh()
        self.assertEqual(len(calls), 1)
        self.fetcher._busy_since -= BUSY_TIMEOUT_S + 1
        self.fetcher.refresh()
        self.assertEqual(len(calls), 2)

    def test_busy_guard_outlasts_a_slow_lookup_and_request(self):
        """A lookup cut off by the watchdog plus a request at its transfer timeout must not overlap
        the next refresh, or an older reply could land last and overwrite a newer forecast."""
        self.assertGreater(BUSY_TIMEOUT_S * 1000, 15_000 + 20_000)

    def test_lookup_that_never_answers_falls_back(self):
        """A WinRT call that blocks outright never reaches its own timeout; the watchdog stands in."""
        requests = []
        self.fetcher._start_locate = lambda token: None  # Windows never answers
        self.fetcher._request = requests.append
        self.fetcher.refresh()
        self.assertTrue(self.fetcher._locate_watchdog.isActive())
        stale_token = self.fetcher._token
        self.fetcher._on_locate_timeout()
        self.assertEqual(requests, [Place("Example Town", "config", "no_fix")])
        self.fetcher._located.emit(stale_token, (-6.17834, 106.63191))  # the lookup answers at last
        self.assertEqual(len(requests), 1)

    def test_located_result_cancels_the_watchdog(self):
        requests = []
        self.fetcher._start_locate = lambda token: None
        self.fetcher._request = requests.append
        self.fetcher.refresh()
        self.fetcher._located.emit(self.fetcher._token, (-6.17834, 106.63191))
        self.assertFalse(self.fetcher._locate_watchdog.isActive())
        self.assertEqual(requests, [Place("-6.18,106.63", "windows", "")])


if __name__ == "__main__":
    unittest.main()

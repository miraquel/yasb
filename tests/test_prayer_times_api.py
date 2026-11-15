# pyright: reportPrivateUsage=false

"""Tests for the prayer times fetcher's response handling.

Replies are fakes handed straight to the handler, and the request itself is stubbed, so no
test reaches the Aladhan API.
"""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtNetwork import QNetworkReply  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from core.utils.widgets.prayer_times.api import PrayerTimesDataFetcher  # noqa: E402


class _Bytes:
    def __init__(self, raw: bytes):
        self._raw = raw

    def data(self) -> bytes:
        return self._raw


class FakeReply:
    """Just the parts of QNetworkReply the handler reads."""

    def __init__(self, body: bytes = b"", error: QNetworkReply.NetworkError = QNetworkReply.NetworkError.NoError):
        self._body = body
        self._error = error
        self.deleted = False

    def error(self) -> QNetworkReply.NetworkError:
        return self._error

    def attribute(self, _attribute: object) -> int:
        return 200 if self._error == QNetworkReply.NetworkError.NoError else 0

    def readAll(self) -> _Bytes:  # noqa: N802 - Qt naming
        return _Bytes(self._body)

    def deleteLater(self) -> None:  # noqa: N802 - Qt naming
        self.deleted = True


class FetcherResponseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = QObject()
        self.fetcher = PrayerTimesDataFetcher(
            self.parent, url_factory=lambda: "https://example.invalid/", timeout_ms=60_000
        )
        self.received: list[dict[str, Any]] = []
        self.fetcher.finished.connect(self.received.append)

    def tearDown(self) -> None:
        self.fetcher._retry_timer.stop()
        self.parent.deleteLater()

    def handle(self, reply: FakeReply) -> None:
        self.fetcher._handle_response(cast(QNetworkReply, reply))

    def test_a_200_response_is_emitted_as_is(self) -> None:
        body = {"code": 200, "data": {"timings": {"Fajr": "04:44"}}}
        reply = FakeReply(json.dumps(body).encode())

        self.handle(reply)

        self.assertEqual(self.received, [body])
        self.assertFalse(self.fetcher._retry_timer.isActive())
        self.assertTrue(reply.deleted)

    def test_an_api_error_code_emits_empty_and_retries(self) -> None:
        self.handle(FakeReply(json.dumps({"code": 400, "status": "Bad Request"}).encode()))

        self.assertEqual(self.received, [{}])
        self.assertTrue(self.fetcher._retry_timer.isActive())

    def test_invalid_json_emits_empty_and_retries(self) -> None:
        self.handle(FakeReply(b"<html>not json</html>"))

        self.assertEqual(self.received, [{}])
        self.assertTrue(self.fetcher._retry_timer.isActive())

    def test_no_connection_emits_empty_and_retries(self) -> None:
        reply = FakeReply(error=QNetworkReply.NetworkError.HostNotFoundError)

        self.handle(reply)

        self.assertEqual(self.received, [{}])
        self.assertTrue(self.fetcher._retry_timer.isActive())
        self.assertTrue(reply.deleted)

    def test_start_requests_once_and_arms_the_refresh_timer(self) -> None:
        with patch.object(PrayerTimesDataFetcher, "make_request", autospec=True) as make_request:
            self.fetcher.start()
        self.fetcher._timer.stop()

        make_request.assert_called_once_with(self.fetcher)
        self.assertTrue(self.fetcher.started)


if __name__ == "__main__":
    unittest.main()

"""Tests for reading the MAL list and the AniList schedule, with the network faked out."""

import io
import json
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.anime_airing.sources import (  # noqa: E402
    MAL_PAGE_SIZE,
    Snapshot,
    SourceError,
    fetch_list,
    fetch_snapshot,
    parse_list_page,
)


def mal_item(mal_id, title="Title", watched=0, total=12, airing_status=1, english=""):
    return {
        "anime_id": mal_id,
        "anime_title": title,
        "anime_title_eng": english,
        "num_watched_episodes": watched,
        "anime_num_episodes": total,
        "anime_airing_status": airing_status,
    }


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, io.BytesIO(b""))


class FakeNetwork:
    """Answers MAL and AniList requests from canned data and records what was asked."""

    def __init__(self, mal_pages=None, media=None, airings=None, error=None):
        self.mal_pages = mal_pages or {}
        self.media = media or []
        self.airings = airings or []
        self.error = error
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request):
        if self.error is not None:
            raise self.error
        url = request.full_url
        if "myanimelist.net" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            key = (int(query["status"][0]), int(query["offset"][0]))
            self.requests.append(("mal", {"status": key[0], "offset": key[1]}))
            return json.dumps(self.mal_pages.get(key, [])).encode()
        body = json.loads(request.data)
        variables = body["variables"]
        if "airingSchedules" in body["query"]:
            self.requests.append(("schedule", variables))
            rows = [row for row in self.airings if row["mediaId"] in variables["ids"]]
            return json.dumps(
                {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "airingSchedules": rows}}}
            ).encode()
        self.requests.append(("media", variables))
        rows = [row for row in self.media if row["idMal"] in variables["ids"]]
        return json.dumps({"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": rows}}}).encode()


class ParseListTests(unittest.TestCase):
    def test_numeric_title_and_unknown_length(self):
        (item,) = parse_list_page([mal_item(1, title=86, total=0)], "watching")
        self.assertEqual(item.title, "86")
        self.assertIsNone(item.total)
        self.assertEqual(item.url, "https://myanimelist.net/anime/1")

    def test_finished_flag(self):
        entries = parse_list_page([mal_item(1, airing_status=2), mal_item(2, airing_status=3)], "watching")
        self.assertEqual([e.airing_finished for e in entries], [True, False])

    def test_malformed_rows_are_skipped(self):
        self.assertEqual(len(parse_list_page([None, {"anime_id": "x"}, mal_item(3)], "watching")), 1)

    def test_not_a_list(self):
        with self.assertRaises(SourceError) as caught:
            parse_list_page({"errors": []}, "watching")
        self.assertEqual(caught.exception.kind, "response")


class FetchListTests(unittest.TestCase):
    def test_pages_until_a_short_page(self):
        full = [mal_item(i) for i in range(1, MAL_PAGE_SIZE + 1)]
        network = FakeNetwork(mal_pages={(1, 0): full, (1, MAL_PAGE_SIZE): [mal_item(9999)]})
        entries = fetch_list("someone", ["watching"], network)
        self.assertEqual(len(entries), MAL_PAGE_SIZE + 1)
        self.assertEqual([r[1]["offset"] for r in network.requests], [0, MAL_PAGE_SIZE])

    def test_statuses_merge_without_duplicates(self):
        network = FakeNetwork(mal_pages={(1, 0): [mal_item(1), mal_item(2)], (6, 0): [mal_item(2), mal_item(3)]})
        entries = fetch_list("someone", ["watching", "plan_to_watch"], network)
        self.assertEqual(
            [(e.mal_id, e.list_status) for e in entries], [(1, "watching"), (2, "watching"), (3, "plan_to_watch")]
        )

    def test_unknown_user(self):
        with self.assertRaises(SourceError) as caught:
            fetch_list("nobody", ["watching"], FakeNetwork(error=http_error(400)))
        self.assertEqual(caught.exception.kind, "user")

    def test_rate_limit_and_network(self):
        with self.assertRaises(SourceError) as caught:
            fetch_list("u", ["watching"], FakeNetwork(error=http_error(429)))
        self.assertEqual(caught.exception.kind, "rate_limited")
        with self.assertRaises(SourceError) as caught:
            fetch_list("u", ["watching"], FakeNetwork(error=urllib.error.URLError("down")))
        self.assertEqual(caught.exception.kind, "network")

    def test_username_is_quoted(self):
        seen = []

        def fetch(request):
            seen.append(request.full_url)
            return b"[]"

        fetch_list("a b/c", ["watching"], fetch)
        self.assertIn("/animelist/a%20b%2Fc/load.json", seen[0])


class FetchSnapshotTests(unittest.TestCase):
    def network(self):
        return FakeNetwork(
            mal_pages={(1, 0): [mal_item(10, watched=3), mal_item(20, airing_status=2)]},
            media=[
                {
                    "id": 100,
                    "idMal": 10,
                    "status": "RELEASING",
                    "episodes": 12,
                    "siteUrl": "https://anilist.co/anime/100",
                    "title": {"romaji": "Ten", "english": None},
                    "coverImage": {"medium": "https://img/100.jpg"},
                    "nextAiringEpisode": {"episode": 5, "airingAt": 2_000_000},
                }
            ],
            airings=[
                {"mediaId": 100, "episode": 4, "airingAt": 1_400_000},
                {"mediaId": 100, "episode": 5, "airingAt": 2_000_000},
            ],
        )

    def test_only_shows_still_airing_reach_anilist(self):
        network = self.network()
        snapshot = fetch_snapshot("u", ["watching"], network, now=1_500_000)
        media_request = next(v for kind, v in network.requests if kind == "media")
        self.assertEqual(media_request["ids"], [10])
        schedule_request = next(v for kind, v in network.requests if kind == "schedule")
        self.assertEqual(schedule_request["ids"], [100])
        self.assertLess(schedule_request["from"], 1_500_000)
        self.assertGreater(schedule_request["to"], 1_500_000)
        self.assertEqual(len(snapshot.entries), 2)
        self.assertEqual([m.anilist_id for m in snapshot.media], [100])
        self.assertEqual(snapshot.media[0].title_english, "")
        self.assertEqual([a.episode for a in snapshot.airings], [4, 5])

    def test_nothing_airing_skips_anilist(self):
        network = FakeNetwork(mal_pages={(1, 0): [mal_item(20, airing_status=2)]})
        fetch_snapshot("u", ["watching"], network, now=1)
        self.assertEqual([kind for kind, _ in network.requests], ["mal"])

    def test_graphql_error_is_named(self):
        def fetch(request):
            if "myanimelist" in request.full_url:
                return json.dumps([mal_item(1)]).encode()
            return json.dumps({"errors": [{"message": "Too Many Requests."}], "data": None}).encode()

        with self.assertRaises(SourceError) as caught:
            fetch_snapshot("u", ["watching"], fetch, now=1)
        self.assertIn("Too Many Requests", str(caught.exception))

    def test_snapshot_round_trips_through_json(self):
        snapshot = fetch_snapshot("u", ["watching"], self.network(), now=1_500_000)
        restored = Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
        self.assertEqual(restored, snapshot)
        self.assertIsNone(Snapshot.from_dict({"username": "u"}))
        self.assertIsNone(Snapshot.from_dict(None))


if __name__ == "__main__":
    unittest.main()

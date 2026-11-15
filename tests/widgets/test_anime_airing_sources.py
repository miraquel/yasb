"""Tests for reading the MAL list and the AniList schedule, with the network faked out."""

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from typing import Any

import pytest

from core.widgets.services.anime_airing.sources import (
    MAL_PAGE_SIZE,
    Snapshot,
    SourceError,
    fetch_list,
    fetch_snapshot,
    parse_list_page,
)


def mal_item(
    mal_id: int,
    title: str | int = "Title",
    watched: int = 0,
    total: int = 12,
    airing_status: int = 1,
    english: str = "",
) -> dict[str, Any]:
    return {
        "anime_id": mal_id,
        "anime_title": title,
        "anime_title_eng": english,
        "num_watched_episodes": watched,
        "anime_num_episodes": total,
        "anime_airing_status": airing_status,
    }


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.invalid", code, "error", Message(), io.BytesIO(b""))


def _body(request: urllib.request.Request) -> dict[str, Any]:
    data = request.data
    assert isinstance(data, bytes)
    return json.loads(data)


class FakeNetwork:
    """Answers MAL and AniList requests from canned data and records what was asked."""

    def __init__(
        self,
        mal_pages: dict[tuple[int, int], list[dict[str, Any]]] | None = None,
        media: list[dict[str, Any]] | None = None,
        airings: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.mal_pages = mal_pages or {}
        self.media = media or []
        self.airings = airings or []
        self.error = error
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: urllib.request.Request) -> bytes:
        if self.error is not None:
            raise self.error
        url = request.full_url
        if "myanimelist.net" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            key = (int(query["status"][0]), int(query["offset"][0]))
            self.requests.append(("mal", {"status": key[0], "offset": key[1]}))
            return json.dumps(self.mal_pages.get(key, [])).encode()
        body = _body(request)
        variables: dict[str, Any] = body["variables"]
        if "airingSchedules" in body["query"]:
            self.requests.append(("schedule", variables))
            rows = [row for row in self.airings if row["mediaId"] in variables["ids"]]
            return json.dumps(
                {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "airingSchedules": rows}}}
            ).encode()
        self.requests.append(("media", variables))
        rows = [row for row in self.media if row["idMal"] in variables["ids"]]
        return json.dumps({"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": rows}}}).encode()

    def first(self, kind: str) -> dict[str, Any]:
        return next(variables for seen, variables in self.requests if seen == kind)


# ----------------------------------------------------------------------
# parse_list_page
# ----------------------------------------------------------------------


def test_numeric_title_and_unknown_length() -> None:
    (item,) = parse_list_page([mal_item(1, title=86, total=0)], "watching")
    assert item.title == "86"
    assert item.total is None
    assert item.url == "https://myanimelist.net/anime/1"


def test_finished_flag() -> None:
    entries = parse_list_page([mal_item(1, airing_status=2), mal_item(2, airing_status=3)], "watching")
    assert [e.airing_finished for e in entries] == [True, False]


def test_malformed_rows_are_skipped() -> None:
    assert len(parse_list_page([None, {"anime_id": "x"}, mal_item(3)], "watching")) == 1


def test_not_a_list() -> None:
    with pytest.raises(SourceError) as caught:
        parse_list_page({"errors": []}, "watching")
    assert caught.value.kind == "response"


# ----------------------------------------------------------------------
# fetch_list
# ----------------------------------------------------------------------


def test_pages_until_a_short_page() -> None:
    full = [mal_item(i) for i in range(1, MAL_PAGE_SIZE + 1)]
    network = FakeNetwork(mal_pages={(1, 0): full, (1, MAL_PAGE_SIZE): [mal_item(9999)]})
    entries = fetch_list("someone", ["watching"], network)
    assert len(entries) == MAL_PAGE_SIZE + 1
    assert [r[1]["offset"] for r in network.requests] == [0, MAL_PAGE_SIZE]


def test_statuses_merge_without_duplicates() -> None:
    network = FakeNetwork(mal_pages={(1, 0): [mal_item(1), mal_item(2)], (6, 0): [mal_item(2), mal_item(3)]})
    entries = fetch_list("someone", ["watching", "plan_to_watch"], network)
    assert [(e.mal_id, e.list_status) for e in entries] == [(1, "watching"), (2, "watching"), (3, "plan_to_watch")]


def test_unknown_user() -> None:
    with pytest.raises(SourceError) as caught:
        fetch_list("nobody", ["watching"], FakeNetwork(error=http_error(400)))
    assert caught.value.kind == "user"


@pytest.mark.parametrize(
    ("error", "kind"),
    [(http_error(429), "rate_limited"), (urllib.error.URLError("down"), "network")],
)
def test_rate_limit_and_network(error: Exception, kind: str) -> None:
    with pytest.raises(SourceError) as caught:
        fetch_list("u", ["watching"], FakeNetwork(error=error))
    assert caught.value.kind == kind


def test_username_is_quoted() -> None:
    seen: list[str] = []

    def fetch(request: urllib.request.Request) -> bytes:
        seen.append(request.full_url)
        return b"[]"

    fetch_list("a b/c", ["watching"], fetch)
    assert "/animelist/a%20b%2Fc/load.json" in seen[0]


# ----------------------------------------------------------------------
# fetch_snapshot
# ----------------------------------------------------------------------


def _network() -> FakeNetwork:
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


def test_only_shows_still_airing_reach_anilist() -> None:
    network = _network()
    snapshot = fetch_snapshot("u", ["watching"], network, now=1_500_000)
    assert network.first("media")["ids"] == [10]
    schedule_request = network.first("schedule")
    assert schedule_request["ids"] == [100]
    assert schedule_request["from"] < 1_500_000
    assert schedule_request["to"] > 1_500_000
    assert len(snapshot.entries) == 2
    assert [m.anilist_id for m in snapshot.media] == [100]
    assert snapshot.media[0].title_english == ""
    assert [a.episode for a in snapshot.airings] == [4, 5]


def test_nothing_airing_skips_anilist() -> None:
    network = FakeNetwork(mal_pages={(1, 0): [mal_item(20, airing_status=2)]})
    fetch_snapshot("u", ["watching"], network, now=1)
    assert [kind for kind, _ in network.requests] == ["mal"]


def test_graphql_error_is_named() -> None:
    def fetch(request: urllib.request.Request) -> bytes:
        if "myanimelist" in request.full_url:
            return json.dumps([mal_item(1)]).encode()
        return json.dumps({"errors": [{"message": "Too Many Requests."}], "data": None}).encode()

    with pytest.raises(SourceError) as caught:
        fetch_snapshot("u", ["watching"], fetch, now=1)
    assert "Too Many Requests" in str(caught.value)


def test_snapshot_round_trips_through_json() -> None:
    snapshot = fetch_snapshot("u", ["watching"], _network(), now=1_500_000)
    restored = Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
    assert restored == snapshot
    assert Snapshot.from_dict({"username": "u"}) is None
    assert Snapshot.from_dict(None) is None

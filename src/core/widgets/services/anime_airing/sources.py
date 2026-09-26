"""Where the airing schedule comes from.

MyAnimeList says *what* you are watching: a public list is served as JSON by
``/animelist/<user>/load.json``, with no API key and no login. It does not say *when* the
next episode airs - the list carries episode counts and an airing flag, never a broadcast
time. AniList fills that in: its public GraphQL API accepts MAL ids directly
(``idMal_in``) and returns each show's exact airing moments.

Two AniList queries are made per refresh. The first resolves MAL ids to AniList media.
The second reads the airing schedule inside a time window around now, so an episode that
aired an hour ago is still known after the refresh that moves ``nextAiringEpisode`` on to
the one after it. That is what lets a reminder fire late - after sleep, or with a
positive offset - without being lost.

Everything here is blocking and runs on a worker thread. ``fetch`` is injectable so the
parsing and pagination can be tested without a network.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

MAL_LIST_URL = "https://myanimelist.net/animelist/{user}/load.json"
MAL_PAGE_SIZE = 300
ANILIST_URL = "https://graphql.anilist.co"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) yasb-anime-airing"
REQUEST_TIMEOUT_S = 15

# The ``status`` codes MAL's load.json understands.
MAL_STATUS_CODES: dict[str, int] = {"watching": 1, "on_hold": 3, "plan_to_watch": 6}
# MAL's ``anime_airing_status``: 1 airing, 2 finished, 3 not yet aired.
MAL_FINISHED_AIRING = 2

# AniList caps a page at 50. A MAL id can map to more than one AniList entry (a split
# cour, a stage release), so a batch of 50 ids can still spill onto a second page.
ANILIST_BATCH = 50
MAX_PAGES = 20

# The schedule window: far enough back to recover an episode that aired while the machine
# was off, far enough ahead to always hold the next episode of a weekly show.
WINDOW_BEFORE_S = 2 * 86_400
WINDOW_AFTER_S = 8 * 86_400

MEDIA_QUERY = """
query ($ids: [Int], $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(idMal_in: $ids, type: ANIME) {
      id idMal status episodes siteUrl
      title { romaji english }
      coverImage { medium }
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

SCHEDULE_QUERY = """
query ($ids: [Int], $from: Int, $to: Int, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    airingSchedules(mediaId_in: $ids, airingAt_greater: $from, airingAt_lesser: $to, sort: TIME) {
      mediaId episode airingAt
    }
  }
}
"""

Fetch = Callable[[urllib.request.Request], bytes]


class SourceError(Exception):
    """A fetch that failed in a way worth naming to the user.

    ``kind`` is one of ``user`` (MAL rejected the username: unknown, or a private list),
    ``rate_limited``, ``network`` or ``response`` (an answer that could not be read).
    """

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind


@dataclass(frozen=True)
class ListEntry:
    """One anime on the user's MAL list."""

    mal_id: int
    title: str
    title_english: str
    list_status: str
    watched: int
    # MAL reports 0 while a show's length is unknown.
    total: int | None
    airing_finished: bool
    url: str


@dataclass(frozen=True)
class Media:
    """One AniList entry matched to a MAL id."""

    anilist_id: int
    mal_id: int
    status: str
    episodes: int | None
    title_romaji: str
    title_english: str
    site_url: str
    cover_url: str
    next_episode: int | None
    next_airing_at: int | None


@dataclass(frozen=True)
class Airing:
    """One scheduled broadcast, as a unix timestamp."""

    anilist_id: int
    episode: int
    airing_at: int


@dataclass(frozen=True)
class Snapshot:
    """Everything one refresh learned, in a form that round-trips through JSON."""

    username: str
    fetched_at: int
    entries: list[ListEntry] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)
    airings: list[Airing] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Snapshot | None:
        """Rebuild a cached snapshot, or None when the cache is not one this version wrote."""
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                username=str(data["username"]),
                fetched_at=int(data["fetched_at"]),
                entries=[ListEntry(**item) for item in data.get("entries", [])],
                media=[Media(**item) for item in data.get("media", [])],
                airings=[Airing(**item) for item in data.get("airings", [])],
            )
        except KeyError, TypeError, ValueError:
            return None


def _default_fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read()


def _request_json(request: urllib.request.Request, fetch: Fetch, source: str) -> Any:
    """Run *request* and decode its JSON body, turning failures into ``SourceError``."""
    try:
        raw = fetch(request)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise SourceError("rate_limited", f"{source} rate limit reached") from error
        # MAL answers an unknown user, and a list its owner has made private, with 400.
        if source == "MyAnimeList" and error.code in (400, 404):
            raise SourceError("user", "MyAnimeList user not found, or the list is private") from error
        raise SourceError("network", f"{source} returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SourceError("network", f"{source} unreachable") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise SourceError("response", f"{source} sent an unreadable response") from error


def _optional_int(value: Any) -> int | None:
    try:
        number = int(value)
    except TypeError, ValueError:
        return None
    return number if number > 0 else None


def parse_list_page(items: Any, list_status: str) -> list[ListEntry]:
    """Read one page of MAL's load.json into list entries, skipping anything malformed."""
    if not isinstance(items, list):
        raise SourceError("response", "MyAnimeList sent something other than a list")
    entries: list[ListEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mal_id = _optional_int(item.get("anime_id"))
        if mal_id is None:
            continue
        # A title that is all digits ("86") comes back as a JSON number.
        title = str(item.get("anime_title") or "").strip() or f"#{mal_id}"
        entries.append(
            ListEntry(
                mal_id=mal_id,
                title=title,
                title_english=str(item.get("anime_title_eng") or "").strip(),
                list_status=list_status,
                watched=_optional_int(item.get("num_watched_episodes")) or 0,
                total=_optional_int(item.get("anime_num_episodes")),
                airing_finished=_optional_int(item.get("anime_airing_status")) == MAL_FINISHED_AIRING,
                url=f"https://myanimelist.net/anime/{mal_id}",
            )
        )
    return entries


def fetch_list(username: str, statuses: Iterable[str], fetch: Fetch = _default_fetch) -> list[ListEntry]:
    """Read every entry in the given statuses of a public MAL list."""
    base = MAL_LIST_URL.format(user=urllib.parse.quote(username.strip(), safe=""))
    entries: list[ListEntry] = []
    seen: set[int] = set()
    for status in statuses:
        for page in range(MAX_PAGES):
            query = urllib.parse.urlencode({"status": MAL_STATUS_CODES[status], "offset": page * MAL_PAGE_SIZE})
            request = urllib.request.Request(f"{base}?{query}", headers={"User-Agent": USER_AGENT})
            items = _request_json(request, fetch, "MyAnimeList")
            for entry in parse_list_page(items, status):
                if entry.mal_id not in seen:
                    seen.add(entry.mal_id)
                    entries.append(entry)
            if len(items) < MAL_PAGE_SIZE:
                break
    return entries


def _graphql(query: str, variables: dict[str, Any], fetch: Fetch) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        ANILIST_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    payload = _request_json(request, fetch, "AniList")
    page = (payload.get("data") or {}).get("Page") if isinstance(payload, dict) else None
    if not isinstance(page, dict):
        errors = payload.get("errors") if isinstance(payload, dict) else None
        message = (
            errors[0].get("message") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else ""
        )
        raise SourceError("response", f"AniList: {message}" if message else "AniList sent no data")
    return page


def _chunks(values: Sequence[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _paged(query: str, variables: dict[str, Any], key: str, fetch: Fetch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_number in range(1, MAX_PAGES + 1):
        page = _graphql(query, {**variables, "page": page_number}, fetch)
        rows.extend(row for row in (page.get(key) or []) if isinstance(row, dict))
        if not (page.get("pageInfo") or {}).get("hasNextPage"):
            break
    return rows


def parse_media(row: dict[str, Any]) -> Media | None:
    anilist_id = _optional_int(row.get("id"))
    mal_id = _optional_int(row.get("idMal"))
    if anilist_id is None or mal_id is None:
        return None
    title = row.get("title") or {}
    cover = row.get("coverImage") or {}
    upcoming = row.get("nextAiringEpisode") or {}
    return Media(
        anilist_id=anilist_id,
        mal_id=mal_id,
        status=str(row.get("status") or ""),
        episodes=_optional_int(row.get("episodes")),
        title_romaji=str(title.get("romaji") or ""),
        title_english=str(title.get("english") or ""),
        site_url=str(row.get("siteUrl") or ""),
        cover_url=str(cover.get("medium") or ""),
        next_episode=_optional_int(upcoming.get("episode")),
        next_airing_at=_optional_int(upcoming.get("airingAt")),
    )


def parse_airing(row: dict[str, Any]) -> Airing | None:
    anilist_id = _optional_int(row.get("mediaId"))
    episode = _optional_int(row.get("episode"))
    airing_at = _optional_int(row.get("airingAt"))
    if anilist_id is None or episode is None or airing_at is None:
        return None
    return Airing(anilist_id=anilist_id, episode=episode, airing_at=airing_at)


def fetch_media(mal_ids: Sequence[int], fetch: Fetch = _default_fetch) -> list[Media]:
    media: list[Media] = []
    for chunk in _chunks(mal_ids, ANILIST_BATCH):
        for row in _paged(MEDIA_QUERY, {"ids": chunk}, "media", fetch):
            parsed = parse_media(row)
            if parsed is not None:
                media.append(parsed)
    return media


def fetch_airings(anilist_ids: Sequence[int], start: int, end: int, fetch: Fetch = _default_fetch) -> list[Airing]:
    airings: list[Airing] = []
    for chunk in _chunks(anilist_ids, ANILIST_BATCH):
        variables = {"ids": chunk, "from": start, "to": end}
        for row in _paged(SCHEDULE_QUERY, variables, "airingSchedules", fetch):
            parsed = parse_airing(row)
            if parsed is not None:
                airings.append(parsed)
    return sorted(airings, key=lambda airing: airing.airing_at)


def fetch_snapshot(
    username: str,
    statuses: Iterable[str],
    fetch: Fetch = _default_fetch,
    now: int | None = None,
) -> Snapshot:
    """Read the user's list, then the airing schedule of everything on it still airing."""
    now = int(time.time()) if now is None else now
    entries = fetch_list(username, statuses, fetch)
    # A show MAL already calls finished has no episodes left to remind anyone about.
    live_ids = [entry.mal_id for entry in entries if not entry.airing_finished]
    media = fetch_media(live_ids, fetch) if live_ids else []
    anilist_ids = sorted({item.anilist_id for item in media})
    airings = fetch_airings(anilist_ids, now - WINDOW_BEFORE_S, now + WINDOW_AFTER_S, fetch) if anilist_ids else []
    return Snapshot(username=username, fetched_at=now, entries=entries, media=media, airings=airings)

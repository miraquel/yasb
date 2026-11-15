"""A schedule fixture for the anime airing tests.

It mirrors a real list on 2026-09-26, including the case that shaped the design: Steel
Ball Run is one MAL entry but two AniList entries whose episode numbers restart.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.widgets.services.anime_airing.sources import Airing, ListEntry, Media, Snapshot

JAKARTA = ZoneInfo("Asia/Jakarta")
USERNAME = "example_user"


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=JAKARTA)


def ts(moment: datetime) -> int:
    return int(moment.timestamp())


def entry(mal_id: int, title: str, english: str, watched: int, total: int | None, finished: bool = False) -> ListEntry:
    return ListEntry(
        mal_id=mal_id,
        title=title,
        title_english=english,
        list_status="watching",
        watched=watched,
        total=total,
        airing_finished=finished,
        url=f"https://myanimelist.net/anime/{mal_id}",
    )


def media(
    anilist_id: int,
    mal_id: int,
    status: str,
    episodes: int | None,
    romaji: str,
    english: str,
    next_episode: int | None = None,
    next_at: datetime | None = None,
) -> Media:
    return Media(
        anilist_id=anilist_id,
        mal_id=mal_id,
        status=status,
        episodes=episodes,
        title_romaji=romaji,
        title_english=english,
        site_url=f"https://anilist.co/anime/{anilist_id}",
        cover_url="",
        next_episode=next_episode,
        next_airing_at=ts(next_at) if next_at else None,
    )


NOW = at(9, 26, 12)

SNAPSHOT = Snapshot(
    username=USERNAME,
    fetched_at=ts(NOW),
    entries=[
        entry(
            59193,
            "Mushoku Tensei III: Isekai Ittara Honki Dasu",
            "Mushoku Tensei: Jobless Reincarnation Season 3",
            12,
            14,
        ),
        entry(61316, "Re:Zero kara Hajimeru Isekai Seikatsu 4th Season", "Re:ZERO Season 4", 18, 19),
        entry(61469, "Steel Ball Run: JoJo no Kimyou na Bouken", "Steel Ball Run: JoJo's Bizarre Adventure", 1, None),
        entry(63403, "Yani Neko", "Chainsmoker Cat", 10, 12, finished=True),
    ],
    media=[
        media(178789, 59193, "RELEASING", 14, "Mushoku Tensei III", "Mushoku Tensei S3", 14, at(9, 27, 18)),
        media(189046, 61316, "RELEASING", 19, "Re:Zero 4th Season", "", 19, at(9, 30, 20)),
        media(190327, 61469, "FINISHED", 1, "JoJo SBR - 1st STAGE", "SBR 1st STAGE"),
        media(210482, 61469, "RELEASING", 11, "JoJo SBR - 2nd & 3rd STAGE", "SBR 2nd - 3rd STAGE", 2, at(10, 2, 15)),
    ],
    airings=[
        Airing(210482, 1, ts(at(9, 25, 15))),
        Airing(178789, 14, ts(at(9, 27, 18))),
        Airing(189046, 19, ts(at(9, 30, 20))),
        Airing(210482, 2, ts(at(10, 2, 15))),
    ],
)

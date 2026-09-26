"""Turning a snapshot into what the bar shows and when a reminder fires.

Everything here is pure: it takes a ``Snapshot`` and the current moment and returns plain
values, so the widget can re-derive its whole state every minute without a refetch. The
snapshot's airing window already holds the episodes due in the coming week, so a
countdown that reaches zero rolls straight on to the next episode.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.widgets.services.anime_airing.sources import ListEntry, Media, Snapshot

# AniList statuses that can still have an episode to come.
_LIVE_STATUSES = ("RELEASING", "NOT_YET_RELEASED")

# A reminder is never checked more often than once a minute, so a due moment is looked
# for in at least this much of the past even when catch-up is switched off.
MIN_NOTIFY_WINDOW = timedelta(minutes=5)

# "is out now" rather than "aired 3m ago" for this long after the broadcast.
_JUST_AIRED = timedelta(minutes=5)


@dataclass(frozen=True)
class Show:
    """One show on the list, joined with its airing schedule."""

    mal_id: int
    anilist_id: int
    title: str
    url: str
    cover_url: str
    list_status: str
    watched: int
    total: int | None
    # How many episodes have aired. None when the MAL entry maps to several AniList
    # entries, whose episode numbering does not line up with MAL's.
    aired: int | None
    next_episode: int | None
    next_at: datetime | None

    @property
    def unwatched(self) -> int | None:
        """Episodes that have aired but are not yet marked watched on MAL."""
        if self.aired is None:
            return None
        return max(self.aired - self.watched, 0)


@dataclass(frozen=True)
class Episode:
    """One broadcast of one show: what a reminder is about."""

    anilist_id: int
    mal_id: int
    title: str
    url: str
    episode: int
    at: datetime

    @property
    def key(self) -> str:
        return f"{self.anilist_id}:{self.episode}"


def _moment(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


def _pick_title(primary: str, english: str, language: str) -> str:
    if language == "english" and english:
        return english
    return primary or english


def _entry_title(entry: ListEntry, language: str) -> str:
    return _pick_title(entry.title, entry.title_english, language)


def _media_title(media: Media, language: str) -> str:
    return _pick_title(media.title_romaji, media.title_english, language)


def _airings_by_media(snapshot: Snapshot) -> dict[int, list[tuple[int, datetime]]]:
    grouped: dict[int, list[tuple[int, datetime]]] = {}
    for airing in snapshot.airings:
        grouped.setdefault(airing.anilist_id, []).append((airing.episode, _moment(airing.airing_at)))
    for episodes in grouped.values():
        episodes.sort(key=lambda item: item[1])
    return grouped


def _next_for(media: Media, airings: list[tuple[int, datetime]], now: datetime) -> tuple[int, datetime] | None:
    """The first broadcast of *media* still to come.

    The schedule window is preferred, since it keeps being right after an episode airs;
    ``nextAiringEpisode`` covers a show whose next episode is further out than the window.
    """
    for episode, at in airings:
        if at > now:
            return episode, at
    if media.next_episode and media.next_airing_at:
        at = _moment(media.next_airing_at)
        if at > now:
            return media.next_episode, at
    return None


def _aired_for(media: Media, airings: list[tuple[int, datetime]], now: datetime) -> int | None:
    """The highest episode number that has gone out by *now*."""
    counts = [episode for episode, at in airings if at <= now]
    if media.next_episode:
        passed = media.next_airing_at is not None and _moment(media.next_airing_at) <= now
        counts.append(media.next_episode if passed else media.next_episode - 1)
    elif media.status == "FINISHED" and media.episodes:
        counts.append(media.episodes)
    return max(counts) if counts else None


def build_shows(snapshot: Snapshot | None, now: datetime, language: str = "romaji") -> list[Show]:
    """Join every list entry with its AniList schedule.

    A MAL id that maps to several AniList entries - JoJo's Steel Ball Run is one MAL entry
    but two AniList "stages" - is represented by whichever of them airs next. Its title
    then comes from AniList, because AniList's episode numbers restart per entry and the
    row has to say which entry "Ep 2" belongs to.
    """
    if snapshot is None:
        return []
    media_by_mal: dict[int, list[Media]] = {}
    for media in snapshot.media:
        media_by_mal.setdefault(media.mal_id, []).append(media)
    airings = _airings_by_media(snapshot)

    shows: list[Show] = []
    for entry in snapshot.entries:
        candidates = media_by_mal.get(entry.mal_id)
        if not candidates:
            continue
        upcoming = {m.anilist_id: _next_for(m, airings.get(m.anilist_id, []), now) for m in candidates}
        far_future = datetime.max.replace(tzinfo=UTC)

        def rank(media: Media, upcoming=upcoming, far_future=far_future) -> tuple[int, datetime]:
            next_up = upcoming[media.anilist_id]
            live = 0 if media.status in _LIVE_STATUSES else 1
            return (0 if next_up else 1 + live, next_up[1] if next_up else far_future)

        chosen = min(candidates, key=rank)
        ambiguous = len(candidates) > 1
        next_up = upcoming[chosen.anilist_id]
        shows.append(
            Show(
                mal_id=entry.mal_id,
                anilist_id=chosen.anilist_id,
                title=_media_title(chosen, language) if ambiguous else _entry_title(entry, language),
                url=entry.url,
                cover_url=chosen.cover_url,
                list_status=entry.list_status,
                watched=entry.watched,
                total=entry.total,
                aired=None if ambiguous else _aired_for(chosen, airings.get(chosen.anilist_id, []), now),
                next_episode=next_up[0] if next_up else None,
                next_at=next_up[1] if next_up else None,
            )
        )
    return shows


def upcoming_shows(shows: Iterable[Show]) -> list[Show]:
    """Shows with an episode still to come, soonest first."""
    return sorted((show for show in shows if show.next_at is not None), key=lambda show: show.next_at)


def build_episodes(snapshot: Snapshot | None, language: str = "romaji") -> list[Episode]:
    """Every known broadcast of every show on the list, for the reminder check."""
    if snapshot is None:
        return []
    entries = {entry.mal_id: entry for entry in snapshot.entries}
    media_by_id = {media.anilist_id: media for media in snapshot.media}
    siblings: dict[int, int] = {}
    for media in snapshot.media:
        siblings[media.mal_id] = siblings.get(media.mal_id, 0) + 1

    def describe(media: Media) -> tuple[str, str] | None:
        entry = entries.get(media.mal_id)
        if entry is None:
            return None
        title = _media_title(media, language) if siblings[media.mal_id] > 1 else _entry_title(entry, language)
        return title, entry.url

    episodes: dict[str, Episode] = {}
    for airing in snapshot.airings:
        media = media_by_id.get(airing.anilist_id)
        described = describe(media) if media else None
        if media is None or described is None:
            continue
        episode = Episode(
            media.anilist_id, media.mal_id, described[0], described[1], airing.episode, _moment(airing.airing_at)
        )
        episodes[episode.key] = episode
    for media in snapshot.media:
        described = describe(media)
        if described is None or not (media.next_episode and media.next_airing_at):
            continue
        episode = Episode(
            media.anilist_id,
            media.mal_id,
            described[0],
            described[1],
            media.next_episode,
            _moment(media.next_airing_at),
        )
        episodes.setdefault(episode.key, episode)
    return sorted(episodes.values(), key=lambda episode: episode.at)


# ----------------------------------------------------------------------------------------
# Reminders
# ----------------------------------------------------------------------------------------


def due_episodes(
    episodes: Iterable[Episode],
    now: datetime,
    offset: timedelta,
    catch_up: timedelta,
    notified: Mapping[str, int],
) -> list[Episode]:
    """Episodes whose reminder moment has arrived and that have not been announced yet.

    The reminder moment is the broadcast shifted by *offset* (negative for a heads-up,
    positive to wait for a stream). A moment up to *catch_up* in the past still counts,
    so an episode that aired while the machine slept or yasb was closed is announced once
    it is back; anything older is left alone rather than arriving as a burst.
    """
    floor = now - max(catch_up, MIN_NOTIFY_WINDOW)
    return [episode for episode in episodes if episode.key not in notified and floor <= episode.at + offset <= now]


def already_due(episodes: Iterable[Episode], now: datetime, offset: timedelta) -> dict[str, int]:
    """Mark everything already past its reminder moment, so a first run does not replay it."""
    return {episode.key: int(episode.at.timestamp()) for episode in episodes if episode.at + offset <= now}


def prune_notified(notified: Mapping[str, int], now: datetime, keep: timedelta = timedelta(days=14)) -> dict[str, int]:
    """Forget announcements older than any schedule window could bring back."""
    cutoff = int((now - keep).timestamp())
    return {key: at for key, at in notified.items() if at >= cutoff}


def reminder_text(episode: Episode, now: datetime, unwatched: int | None = None) -> tuple[str, str]:
    """The (title, message) of a reminder toast."""
    number = f"Episode {episode.episode}"
    if episode.at > now:
        message = f"{number} airs in {format_countdown(episode.at, now)}"
    elif now - episode.at < _JUST_AIRED:
        message = f"{number} is out now"
    else:
        message = f"{number} aired {format_ago(episode.at, now)}"
    # The episode being announced is one of the unwatched ones; mention the backlog only
    # when there is more of it than this episode.
    if unwatched is not None and unwatched > 1:
        message = f"{message} · {unwatched} to catch up on"
    return episode.title, message


# ----------------------------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------------------------


def format_countdown(target: datetime, now: datetime) -> str:
    """Time until *target*: '3d 4h', '20h 05m', '45m', or 'now'."""
    seconds = int((target - now).total_seconds())
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def format_ago(moment: datetime, now: datetime) -> str:
    """How long ago *moment* was: 'just now', '12m ago', '3h ago', '2d ago'."""
    minutes = max(int((now - moment).total_seconds()) // 60, 0)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 48 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // (24 * 60)}d ago"


def format_air_time(moment: datetime, now: datetime) -> str:
    """When *moment* is, in local time: 'Today 18:00', 'Tomorrow 18:00', 'Wed 18:00', 'Sat 17 Oct 18:00'."""
    local = moment.astimezone(now.tzinfo) if now.tzinfo else moment.astimezone()
    days = (local.date() - now.date()).days
    clock = local.strftime("%H:%M")
    if days == 0:
        return f"Today {clock}"
    if days == 1:
        return f"Tomorrow {clock}"
    if 1 < days < 7:
        return f"{local:%a} {clock}"
    return f"{local:%a} {local.day} {local:%b} {clock}"


def shorten(text: str, limit: int) -> str:
    """Cut *text* to *limit* characters with an ellipsis; 0 means no limit."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip(" :-·") + "…"

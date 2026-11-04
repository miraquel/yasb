"""Tests for the anime airing schedule: joining MAL and AniList, countdowns and reminders."""

from datetime import UTC, datetime, timedelta

from core.widgets.services.anime_airing.schedule import (
    Episode,
    Show,
    already_due,
    build_episodes,
    build_shows,
    due_episodes,
    format_ago,
    format_air_time,
    format_countdown,
    prune_notified,
    reminder_text,
    shorten,
    upcoming_shows,
)
from core.widgets.services.anime_airing.sources import Airing, Snapshot
from tests.support.anime_airing import NOW, SNAPSHOT, at, entry, media, ts


def _shows(now: datetime = NOW, language: str = "romaji") -> dict[int, Show]:
    return {show.mal_id: show for show in build_shows(SNAPSHOT, now, language)}


# ----------------------------------------------------------------------
# build_shows
# ----------------------------------------------------------------------


def test_a_show_mal_calls_finished_has_no_schedule() -> None:
    assert 63403 not in _shows()


def test_behind_is_aired_minus_watched() -> None:
    shows = _shows()
    # Episode 14 is next, so 13 are out; 12 watched leaves one to catch up on.
    assert shows[59193].aired == 13
    assert shows[59193].unwatched == 1
    assert shows[61316].unwatched == 0


def test_split_mal_entry_takes_the_airing_anilist_entry_and_its_title() -> None:
    show = _shows()[61469]
    assert show.anilist_id == 210482
    assert show.title == "JoJo SBR - 2nd & 3rd STAGE"
    assert show.next_episode == 2
    # AniList's numbering restarts per stage, so MAL's watched count says nothing about it.
    assert show.unwatched is None


def test_title_language() -> None:
    assert _shows(language="english")[59193].title == "Mushoku Tensei: Jobless Reincarnation Season 3"
    assert _shows(language="romaji")[59193].title == "Mushoku Tensei III: Isekai Ittara Honki Dasu"


def test_english_falls_back_when_anilist_has_none() -> None:
    snapshot = Snapshot(
        "u", ts(NOW), [entry(1, "Romaji", "", 0, None)], [media(9, 1, "RELEASING", 12, "R", "", 3, at(9, 28, 1))]
    )
    assert build_shows(snapshot, NOW, "english")[0].title == "Romaji"


def test_upcoming_is_soonest_first() -> None:
    order = [show.mal_id for show in upcoming_shows(build_shows(SNAPSHOT, NOW))]
    assert order == [59193, 61316, 61469]


def test_countdown_rolls_on_after_an_episode_airs_without_a_refetch() -> None:
    mushoku = _shows(now=at(9, 27, 18, 30))[59193]
    # The snapshot knows no later episode, and 14 is the last one.
    assert mushoku.next_at is None
    assert mushoku.aired == 14
    assert mushoku.unwatched == 2
    sbr = _shows(now=at(10, 2, 15, 1))[61469]
    assert sbr.next_episode is None


def test_window_episode_beats_stale_next_airing() -> None:
    # nextAiringEpisode still says 19, but the window already holds 20 for next week.
    snapshot = Snapshot(
        "u",
        ts(NOW),
        [entry(1, "Show", "", 18, 24)],
        [media(9, 1, "RELEASING", 24, "Show", "", 19, at(9, 26, 11))],
        [Airing(9, 19, ts(at(9, 26, 11))), Airing(9, 20, ts(at(10, 3, 11)))],
    )
    show = build_shows(snapshot, NOW)[0]
    assert (show.next_episode, show.next_at) == (20, at(10, 3, 11))
    assert show.unwatched == 1


def test_no_snapshot() -> None:
    assert build_shows(None, NOW) == []
    assert build_episodes(None) == []


# ----------------------------------------------------------------------
# Reminders
# ----------------------------------------------------------------------


def _episodes() -> list[Episode]:
    return build_episodes(SNAPSHOT)


def _keys(episodes: list[Episode]) -> list[str]:
    return [episode.key for episode in episodes]


def test_episodes_cover_window_and_next_airing() -> None:
    assert _keys(_episodes()) == ["210482:1", "178789:14", "189046:19", "210482:2"]


def test_due_at_broadcast() -> None:
    due = due_episodes(_episodes(), at(9, 27, 18, 0), timedelta(0), timedelta(hours=12), {})
    assert _keys(due) == ["178789:14"]


def test_not_due_before_broadcast() -> None:
    assert due_episodes(_episodes(), at(9, 27, 17, 59), timedelta(0), timedelta(hours=12), {}) == []


def test_negative_offset_is_a_heads_up() -> None:
    due = due_episodes(_episodes(), at(9, 27, 17, 45), timedelta(minutes=-15), timedelta(0), {})
    assert _keys(due) == ["178789:14"]


def test_positive_offset_waits() -> None:
    episodes = _episodes()
    assert due_episodes(episodes, at(9, 27, 18, 30), timedelta(hours=1), timedelta(0), {}) == []
    due = due_episodes(episodes, at(9, 27, 19, 0), timedelta(hours=1), timedelta(0), {})
    assert _keys(due) == ["178789:14"]


def test_announced_once() -> None:
    due = due_episodes(_episodes(), at(9, 27, 18, 1), timedelta(0), timedelta(hours=12), {"178789:14": 1})
    assert due == []


def test_catch_up_after_sleep_is_bounded() -> None:
    episodes = _episodes()
    woke = at(9, 27, 22)
    assert _keys(due_episodes(episodes, woke, timedelta(0), timedelta(hours=12), {})) == ["178789:14"]
    # Without catch-up only the last few minutes count, so a 4-hour-old episode stays quiet.
    assert due_episodes(episodes, woke, timedelta(0), timedelta(0), {}) == []


def test_first_run_marks_the_past_as_announced() -> None:
    seeded = already_due(_episodes(), NOW, timedelta(0))
    assert set(seeded) == {"210482:1"}
    assert due_episodes(_episodes(), NOW, timedelta(0), timedelta(hours=48), seeded) == []


def test_prune() -> None:
    notified = {"old": ts(NOW - timedelta(days=30)), "new": ts(NOW - timedelta(days=1))}
    assert set(prune_notified(notified, NOW)) == {"new"}


def test_reminder_text() -> None:
    episode = Episode(1, 2, "Show & Co", "u", 14, at(9, 27, 18))
    assert reminder_text(episode, at(9, 27, 18, 2)) == ("Show & Co", "Episode 14 is out now")
    assert reminder_text(episode, at(9, 27, 20))[1] == "Episode 14 aired 2h ago"
    assert reminder_text(episode, at(9, 27, 17, 45))[1] == "Episode 14 airs in 15m"
    assert reminder_text(episode, at(9, 27, 18, 2), unwatched=1)[1] == "Episode 14 is out now"
    assert reminder_text(episode, at(9, 27, 18, 2), unwatched=2)[1] == "Episode 14 is out now · 2 to catch up on"


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------


def test_countdown() -> None:
    assert format_countdown(NOW + timedelta(seconds=30), NOW) == "now"
    assert format_countdown(NOW - timedelta(minutes=5), NOW) == "now"
    assert format_countdown(NOW + timedelta(minutes=45), NOW) == "45m"
    assert format_countdown(NOW + timedelta(hours=20, minutes=5), NOW) == "20h 05m"
    assert format_countdown(NOW + timedelta(days=3, hours=4, minutes=59), NOW) == "3d 4h"


def test_ago() -> None:
    assert format_ago(NOW, NOW) == "just now"
    assert format_ago(NOW - timedelta(minutes=12), NOW) == "12m ago"
    assert format_ago(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert format_ago(NOW - timedelta(days=3), NOW) == "3d ago"


def test_air_time_is_local_and_relative() -> None:
    assert format_air_time(at(9, 26, 18), NOW) == "Today 18:00"
    assert format_air_time(at(9, 27, 18), NOW) == "Tomorrow 18:00"
    assert format_air_time(at(9, 30, 20), NOW) == "Wed 20:00"
    assert format_air_time(at(10, 3, 9), NOW) == "Sat 3 Oct 09:00"
    # AniList times are UTC; they are shown in the viewer's zone.
    assert format_air_time(datetime(2026, 9, 27, 11, 0, tzinfo=UTC), NOW) == "Tomorrow 18:00"


def test_shorten() -> None:
    assert shorten("Mushoku Tensei III: Isekai", 16) == "Mushoku Tensei…"
    assert shorten("Short", 16) == "Short"
    assert shorten("Anything at all", 0) == "Anything at all"

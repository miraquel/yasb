"""Tests for the anime airing schedule: joining MAL and AniList, countdowns and reminders.

The fixture mirrors a real list on 2026-09-26, including the case that shaped the design:
Steel Ball Run is one MAL entry but two AniList entries whose episode numbers restart.
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.anime_airing.schedule import (  # noqa: E402
    Episode,
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
from core.widgets.services.anime_airing.sources import Airing, ListEntry, Media, Snapshot  # noqa: E402

JAKARTA = ZoneInfo("Asia/Jakarta")


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=JAKARTA)


def ts(moment: datetime) -> int:
    return int(moment.timestamp())


def entry(mal_id, title, english, watched, total, finished=False) -> ListEntry:
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


def media(anilist_id, mal_id, status, episodes, romaji, english, next_episode=None, next_at=None) -> Media:
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
    username="miraquel",
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


class BuildShowsTests(unittest.TestCase):
    def shows(self, now=NOW, language="romaji"):
        return {show.mal_id: show for show in build_shows(SNAPSHOT, now, language)}

    def test_a_show_mal_calls_finished_has_no_schedule(self):
        self.assertNotIn(63403, self.shows())

    def test_behind_is_aired_minus_watched(self):
        shows = self.shows()
        # Episode 14 is next, so 13 are out; 12 watched leaves one to catch up on.
        self.assertEqual(shows[59193].aired, 13)
        self.assertEqual(shows[59193].unwatched, 1)
        self.assertEqual(shows[61316].unwatched, 0)

    def test_split_mal_entry_takes_the_airing_anilist_entry_and_its_title(self):
        show = self.shows()[61469]
        self.assertEqual(show.anilist_id, 210482)
        self.assertEqual(show.title, "JoJo SBR - 2nd & 3rd STAGE")
        self.assertEqual(show.next_episode, 2)
        # AniList's numbering restarts per stage, so MAL's watched count says nothing about it.
        self.assertIsNone(show.unwatched)

    def test_title_language(self):
        self.assertEqual(self.shows(language="english")[59193].title, "Mushoku Tensei: Jobless Reincarnation Season 3")
        self.assertEqual(self.shows(language="romaji")[59193].title, "Mushoku Tensei III: Isekai Ittara Honki Dasu")

    def test_english_falls_back_when_anilist_has_none(self):
        snapshot = Snapshot(
            "u", ts(NOW), [entry(1, "Romaji", "", 0, None)], [media(9, 1, "RELEASING", 12, "R", "", 3, at(9, 28, 1))]
        )
        self.assertEqual(build_shows(snapshot, NOW, "english")[0].title, "Romaji")

    def test_upcoming_is_soonest_first(self):
        order = [show.mal_id for show in upcoming_shows(build_shows(SNAPSHOT, NOW))]
        self.assertEqual(order, [59193, 61316, 61469])

    def test_countdown_rolls_on_after_an_episode_airs_without_a_refetch(self):
        after = at(9, 27, 18, 30)
        mushoku = self.shows(now=after)[59193]
        # The snapshot knows no later episode, and 14 is the last one.
        self.assertIsNone(mushoku.next_at)
        self.assertEqual(mushoku.aired, 14)
        self.assertEqual(mushoku.unwatched, 2)
        sbr = self.shows(now=at(10, 2, 15, 1))[61469]
        self.assertIsNone(sbr.next_episode)

    def test_window_episode_beats_stale_next_airing(self):
        # nextAiringEpisode still says 19, but the window already holds 20 for next week.
        snapshot = Snapshot(
            "u",
            ts(NOW),
            [entry(1, "Show", "", 18, 24)],
            [media(9, 1, "RELEASING", 24, "Show", "", 19, at(9, 26, 11))],
            [Airing(9, 19, ts(at(9, 26, 11))), Airing(9, 20, ts(at(10, 3, 11)))],
        )
        show = build_shows(snapshot, NOW)[0]
        self.assertEqual((show.next_episode, show.next_at), (20, at(10, 3, 11)))
        self.assertEqual(show.unwatched, 1)

    def test_no_snapshot(self):
        self.assertEqual(build_shows(None, NOW), [])
        self.assertEqual(build_episodes(None), [])


class ReminderTests(unittest.TestCase):
    def episodes(self):
        return build_episodes(SNAPSHOT)

    def test_episodes_cover_window_and_next_airing(self):
        keys = [episode.key for episode in self.episodes()]
        self.assertEqual(keys, ["210482:1", "178789:14", "189046:19", "210482:2"])

    def test_due_at_broadcast(self):
        due = due_episodes(self.episodes(), at(9, 27, 18, 0), timedelta(0), timedelta(hours=12), {})
        self.assertEqual([e.key for e in due], ["178789:14"])

    def test_not_due_before_broadcast(self):
        self.assertEqual(due_episodes(self.episodes(), at(9, 27, 17, 59), timedelta(0), timedelta(hours=12), {}), [])

    def test_negative_offset_is_a_heads_up(self):
        due = due_episodes(self.episodes(), at(9, 27, 17, 45), timedelta(minutes=-15), timedelta(0), {})
        self.assertEqual([e.key for e in due], ["178789:14"])

    def test_positive_offset_waits(self):
        episodes = self.episodes()
        self.assertEqual(due_episodes(episodes, at(9, 27, 18, 30), timedelta(hours=1), timedelta(0), {}), [])
        due = due_episodes(episodes, at(9, 27, 19, 0), timedelta(hours=1), timedelta(0), {})
        self.assertEqual([e.key for e in due], ["178789:14"])

    def test_announced_once(self):
        due = due_episodes(self.episodes(), at(9, 27, 18, 1), timedelta(0), timedelta(hours=12), {"178789:14": 1})
        self.assertEqual(due, [])

    def test_catch_up_after_sleep_is_bounded(self):
        episodes = self.episodes()
        woke = at(9, 27, 22)
        self.assertEqual(
            [e.key for e in due_episodes(episodes, woke, timedelta(0), timedelta(hours=12), {})], ["178789:14"]
        )
        # Without catch-up only the last few minutes count, so a 4-hour-old episode stays quiet.
        self.assertEqual(due_episodes(episodes, woke, timedelta(0), timedelta(0), {}), [])

    def test_first_run_marks_the_past_as_announced(self):
        seeded = already_due(self.episodes(), NOW, timedelta(0))
        self.assertEqual(set(seeded), {"210482:1"})
        self.assertEqual(due_episodes(self.episodes(), NOW, timedelta(0), timedelta(hours=48), seeded), [])

    def test_prune(self):
        notified = {"old": ts(NOW - timedelta(days=30)), "new": ts(NOW - timedelta(days=1))}
        self.assertEqual(set(prune_notified(notified, NOW)), {"new"})

    def test_reminder_text(self):
        episode = Episode(1, 2, "Show & Co", "u", 14, at(9, 27, 18))
        self.assertEqual(reminder_text(episode, at(9, 27, 18, 2)), ("Show & Co", "Episode 14 is out now"))
        self.assertEqual(reminder_text(episode, at(9, 27, 20))[1], "Episode 14 aired 2h ago")
        self.assertEqual(reminder_text(episode, at(9, 27, 17, 45))[1], "Episode 14 airs in 15m")
        self.assertEqual(reminder_text(episode, at(9, 27, 18, 2), unwatched=1)[1], "Episode 14 is out now")
        self.assertEqual(
            reminder_text(episode, at(9, 27, 18, 2), unwatched=2)[1], "Episode 14 is out now · 2 to catch up on"
        )


class FormatTests(unittest.TestCase):
    def test_countdown(self):
        self.assertEqual(format_countdown(NOW + timedelta(seconds=30), NOW), "now")
        self.assertEqual(format_countdown(NOW - timedelta(minutes=5), NOW), "now")
        self.assertEqual(format_countdown(NOW + timedelta(minutes=45), NOW), "45m")
        self.assertEqual(format_countdown(NOW + timedelta(hours=20, minutes=5), NOW), "20h 05m")
        self.assertEqual(format_countdown(NOW + timedelta(days=3, hours=4, minutes=59), NOW), "3d 4h")

    def test_ago(self):
        self.assertEqual(format_ago(NOW, NOW), "just now")
        self.assertEqual(format_ago(NOW - timedelta(minutes=12), NOW), "12m ago")
        self.assertEqual(format_ago(NOW - timedelta(hours=3), NOW), "3h ago")
        self.assertEqual(format_ago(NOW - timedelta(days=3), NOW), "3d ago")

    def test_air_time_is_local_and_relative(self):
        self.assertEqual(format_air_time(at(9, 26, 18), NOW), "Today 18:00")
        self.assertEqual(format_air_time(at(9, 27, 18), NOW), "Tomorrow 18:00")
        self.assertEqual(format_air_time(at(9, 30, 20), NOW), "Wed 20:00")
        self.assertEqual(format_air_time(at(10, 3, 9), NOW), "Sat 3 Oct 09:00")
        # AniList times are UTC; they are shown in the viewer's zone.
        utc = datetime(2026, 9, 27, 11, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(format_air_time(utc, NOW), "Tomorrow 18:00")

    def test_shorten(self):
        self.assertEqual(shorten("Mushoku Tensei III: Isekai", 16), "Mushoku Tensei…")
        self.assertEqual(shorten("Short", 16), "Short")
        self.assertEqual(shorten("Anything at all", 0), "Anything at all")


if __name__ == "__main__":
    unittest.main()

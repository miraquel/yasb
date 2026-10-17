"""Tests for the Qt-free parts of the Claude widget's Clawd, sessions and plan helpers.

Clawd's moods and reactions are driven through the model with a seeded RNG and a fake clock,
and the session registry is read from a temporary folder with a stubbed process lookup, so
nothing here depends on what is running on the machine.
"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.widgets.claude_usage import clawd  # noqa: E402
from core.utils.widgets.claude_usage.clawd import Clawd, choose_mood, geometry, heart_halves  # noqa: E402
from core.widgets.services.claude_usage.claude_api import plan_name  # noqa: E402
from core.widgets.services.claude_usage.sessions import (  # noqa: E402
    count_sessions,
    is_live,
    parse_session,
    read_sessions,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_clawd(seed: int = 1) -> tuple[Clawd, FakeClock]:
    clock = FakeClock()
    return Clawd(rng=random.Random(seed), clock=clock), clock


def run(model: Clawd, ticks: int, width: float = 150.0):
    frame = None
    for _ in range(ticks):
        frame = model.step(width)
    return frame


class GeometryTests(unittest.TestCase):
    def grid(self, geo):
        """Occupied (column, row) pixels of the body and eyes, in grid units."""
        cells = set()
        for x, y, w, h in geo.body + geo.eyes:
            for gx in range(round(x / clawd.PX), round((x + w) / clawd.PX)):
                cells.add((gx, round(y / clawd.PY)))
        return cells

    def test_default_pose_is_clawd(self):
        geo = geometry()
        cells = self.grid(geo)
        # Head 13 px wide, arms row 17 px, four feet - the welcome-screen crab.
        self.assertEqual(sorted(x for x, y in cells if y == 0), list(range(3, 16)))
        self.assertEqual(sorted(x for x, y in cells if y == 4), list(range(1, 18)))
        self.assertEqual(sorted(x for x, y in cells if y == 8), [3, 5, 13, 15])
        # Eyes are dark pixels at the pupils' default spot.
        eyes = {(round(x / clawd.PX), round(y / clawd.PY)) for x, y, _, _ in geo.eyes}
        self.assertEqual(eyes, {(5, 2), (5, 3), (13, 2), (13, 3)})

    def test_runs_are_merged(self):
        # The head row is one rectangle, not thirteen.
        self.assertEqual(len([r for r in geometry().body if r[1] == 0]), 1)

    def test_flip_puts_feet_on_top(self):
        cells = self.grid(geometry(eyes="x", flip=True))
        self.assertEqual(sorted(x for x, y in cells if y == 0), [3, 5, 13, 15])

    def test_burrow_hides_body_below_ground_and_draws_sand(self):
        geo = geometry(dig=clawd.BURROW_DIG, eyes="closed")
        self.assertTrue(geo.sand)
        self.assertTrue(all(y < (clawd.GRID_H - 2) * clawd.PY for _, y, _, _ in geo.body))

    def test_every_sequence_frame_renders(self):
        for name, frames in clawd.SEQUENCES.items():
            for frame in frames:
                geometry(frame["eyes"], frame["arms"], frame["feet"], 0, False, frame["off"], frame["x"],
                         frame["facing"], frame["poof"], frame["shadow"])  # fmt: skip
            self.assertEqual(clawd.ACT_LENGTHS[name], len(frames))

    def test_click_acts_start_in_place(self):
        self.assertNotIn("celebrate", clawd.CLICK_ACTS)
        self.assertNotIn("skip", clawd.CLICK_ACTS)  # slides in from the side
        self.assertIn("jump", clawd.CLICK_ACTS)


class HeartsTests(unittest.TestCase):
    def test_halves_follow_what_is_left(self):
        self.assertEqual(heart_halves(0), 6)
        self.assertEqual(heart_halves(17), 5)
        self.assertEqual(heart_halves(50), 3)
        self.assertEqual(heart_halves(99), 1)
        self.assertEqual(heart_halves(100), 0)
        self.assertEqual(heart_halves(130), 0)

    def test_no_reading_no_hearts(self):
        self.assertIsNone(heart_halves(None))

    def test_half_heart_is_left_four_columns(self):
        half = clawd.heart_rects(4)
        self.assertTrue(half)
        self.assertTrue(all(x < 4 * clawd.HEART_PX for x, _, _, _ in half))


class MoodTests(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(choose_mood(100, busy=1, waiting=1, total=2), "dead")
        self.assertEqual(choose_mood(40, busy=1, waiting=1, total=2), "wait")
        self.assertEqual(choose_mood(40, busy=1, waiting=0, total=2), "work")
        self.assertEqual(choose_mood(40, busy=0, waiting=0, total=2), "idle")
        self.assertEqual(choose_mood(None, busy=0, waiting=0, total=0), "sleep")

    def test_falls_asleep_by_burrowing(self):
        model, _ = make_clawd()
        model.set_inputs(10, 0, 0, 0, None)
        frame = model.step(150)
        self.assertEqual(model.act, "burrow")
        frame = run(model, clawd.ACT_LENGTHS["burrow"] + 2)
        self.assertIsNone(model.act)
        self.assertEqual(frame.mood, "sleep")
        self.assertIsNotNone(frame.zzz)
        self.assertTrue(frame.geometry.sand)

    def test_wakes_by_climbing_out(self):
        model, _ = make_clawd()
        model.set_inputs(10, 0, 0, 0, None)
        run(model, 40)
        model.set_inputs(10, 1, 0, 1, None)
        model.step(150)
        self.assertEqual(model.act, "unburrow")

    def test_waiting_shows_a_question(self):
        model, _ = make_clawd()
        model.set_inputs(10, 0, 1, 1, None)
        frame = model.step(150)
        self.assertEqual(frame.bubble, "?")

    def test_work_runs_and_kicks_up_dust(self):
        model, _ = make_clawd(seed=3)
        model.set_inputs(10, 1, 0, 1, None)
        start = model.step(150).x
        moved = [f for f in (model.step(150) for _ in range(20)) if f.dust]
        self.assertTrue(moved)
        self.assertNotEqual(model.x, start)

    def test_jumps_when_a_session_finishes(self):
        model, _ = make_clawd()
        model.set_inputs(10, 2, 0, 2, None)
        model.set_inputs(10, 1, 0, 2, None)
        self.assertEqual(model.act, "jump")

    def test_dozes_after_ten_quiet_minutes(self):
        model, clock = make_clawd()
        model.set_inputs(10, 0, 0, 1, None)
        clock.now += 601
        model.act = None
        frame = model.step(150)
        self.assertEqual(frame.mood, "doze")

    def test_limit_reached_lies_down_and_soul_on_click(self):
        model, _ = make_clawd()
        model.set_inputs(100, 1, 0, 1, None)
        frame = model.step(150)
        self.assertEqual(frame.mood, "dead")
        self.assertEqual(frame.hearts, 0)
        model.click()
        self.assertEqual(model.act, "soul")
        souls = [f.soul for f in (model.step(150) for _ in range(30)) if f.soul]
        self.assertTrue(souls)

    def test_sweats_near_the_limit(self):
        model, _ = make_clawd()
        model.set_inputs(90, 0, 0, 1, None)
        frame = model.step(150)
        self.assertIsNotNone(frame.sweat)

    def test_celebrates_when_the_window_resets(self):
        model, _ = make_clawd()
        model.set_inputs(70, 0, 0, 1, 10_000.0)
        model.set_inputs(72, 0, 0, 1, 10_000.5)
        self.assertNotEqual(model.act, "celebrate")
        model.set_inputs(0, 0, 0, 1, 10_000.0 + 5 * 3600)
        self.assertEqual(model.act, "celebrate")
        frame = model.step(150)
        self.assertEqual(frame.bubble, "!")
        self.assertTrue(frame.confetti)

    def test_click_pets_him(self):
        model, _ = make_clawd()
        model.set_inputs(10, 0, 0, 1, None)
        run(model, 3)
        model.act = None
        model.click()
        self.assertIn(model.act, clawd.CLICK_ACTS)
        self.assertIsNotNone(model.step(150).love)

    def test_stays_inside_the_area(self):
        model, _ = make_clawd(seed=7)
        model.set_inputs(10, 1, 0, 1, None)
        for _ in range(400):
            frame = model.step(120)
            self.assertGreaterEqual(frame.x, -2)
            self.assertLessEqual(frame.x, 120 - clawd.WIDTH + 2)

    def test_lost_heart_blinks(self):
        model, _ = make_clawd()
        model.set_inputs(10, 0, 0, 1, None)
        model.step(150)
        model.set_inputs(40, 0, 0, 1, None)
        shown = [model.step(150).hearts for _ in range(16)]
        self.assertIn(6, shown)
        self.assertIn(4, shown)
        self.assertEqual(model.step(150).hearts, 4)


def write_session(folder: Path, pid: int, **fields) -> None:
    data = {"pid": pid, "sessionId": f"s-{pid}", "cwd": "C:\\work\\repo", "procStart": "100", "startedAt": pid}
    data.update(fields)
    (folder / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")


class SessionTests(unittest.TestCase):
    def test_parse_maps_status_and_names(self):
        session = parse_session({"pid": 5, "cwd": "D:\\code\\yasb", "status": "busy"})
        self.assertEqual(session["status"], "working")
        self.assertEqual(session["name"], "yasb")
        self.assertEqual(parse_session({"pid": 6, "status": "waiting"})["status"], "waiting")
        self.assertEqual(parse_session({"pid": 7, "status": "idle", "name": "x"})["status"], "idle")
        self.assertIsNone(parse_session({"cwd": "C:\\"}))
        self.assertIsNone(parse_session({"pid": "abc"}))

    def test_liveness_checks_start_time(self):
        session = parse_session({"pid": 9, "procStart": "1000000000"})
        self.assertTrue(is_live(session, lambda pid: 1000000000 + 10_000_000))
        self.assertFalse(is_live(session, lambda pid: 1000000000 + 600_000_000))  # recycled pid
        self.assertFalse(is_live(session, lambda pid: None))
        self.assertTrue(is_live(session, lambda pid: 0))  # alive, times unreadable

    def test_read_skips_dead_dedupes_and_counts(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            write_session(Path(a), 1, status="busy", name="one")
            write_session(Path(a), 2, status="waiting")
            write_session(Path(a), 3, status="idle")
            write_session(Path(b), 1, status="busy", name="one")  # same session seen twice
            (Path(b) / "junk.json").write_text("{not json", encoding="utf-8")
            alive = {1: 100, 2: 100}
            sessions = read_sessions([a, b], start_of=lambda pid: alive.get(pid))
            self.assertEqual([s["pid"] for s in sessions], [1, 2])
            self.assertEqual(count_sessions(sessions), {"total": 2, "working": 1, "waiting": 1, "idle": 0})


class PlanNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(plan_name("pro"), "Pro")
        self.assertEqual(plan_name("team", "default_claude_max_5x"), "Team")
        self.assertEqual(plan_name("max", "default_claude_max_20x"), "Max 20x")
        self.assertEqual(plan_name("max"), "Max")
        self.assertEqual(plan_name(""), "")
        self.assertEqual(plan_name("galaxy"), "Galaxy")


if __name__ == "__main__":
    unittest.main()

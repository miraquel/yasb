"""Tests for the Codex pet: its art (every pose on Clawd's grid) and its behaviour, driven tick
by tick with a seeded RNG so every run plays the same.
"""

import random
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.widgets.claude_usage.clawd import PX, PY  # noqa: E402
from core.utils.widgets.codex_usage.codex_pet import ACT_LENGTHS, CodexPet, choose_mood  # noqa: E402
from core.utils.widgets.codex_usage.codex_pet_art import (  # noqa: E402
    GRID_H,
    GRID_W,
    HEIGHT,
    IDLE,
    POSES,
    WIDTH,
    pose_rects,
)


class PetArtTest(unittest.TestCase):
    def test_size_is_clawds_width(self):
        self.assertEqual((GRID_W, GRID_H), (18, 20))
        self.assertAlmostEqual(WIDTH, 36.0)
        self.assertAlmostEqual(HEIGHT, 44.0)

    def test_every_pose_is_18_by_20_in_four_characters(self):
        self.assertEqual(
            set(POSES),
            {
                "idle",
                "blink",
                "asleep",
                "walk-1",
                "walk-2",
                "type-1",
                "type-2",
                "wait",
                "crouch",
                "jump",
                "failed",
                "wave-1",
                "wave-2",
            },
        )
        for name, rows in POSES.items():
            self.assertEqual(len(rows), GRID_H, name)
            for row in rows:
                self.assertEqual(len(row), GRID_W, name)
                self.assertLessEqual(set(row), set(".#S>"), name)

    def test_idle_is_the_agreed_art(self):
        self.assertEqual(POSES["idle"], IDLE)
        self.assertEqual(IDLE[0], ".......####.......")
        self.assertEqual(IDLE[8], "###SS>SSSS>>>SS###")
        self.assertEqual(IDLE[15], "...#.###>>###.#...")
        self.assertEqual(IDLE[19], "......##..##......")

    def test_the_head_stays_the_same_in_every_pose(self):
        # Rows 0-11 differ from idle only in the face (> versus S).
        head = [row.replace(">", "S") for row in IDLE[:12]]
        for name, rows in POSES.items():
            self.assertEqual([row.replace(">", "S") for row in rows[:12]], head, name)

    def test_blink_closes_the_eye_to_a_line(self):
        self.assertEqual(POSES["blink"][8], "###SS>>>SS>>>SS###")
        self.assertNotIn(">", POSES["blink"][6] + POSES["blink"][7])

    def test_rects_cover_each_pixel_once(self):
        rects = pose_rects("idle")
        area = sum(w * h for part in (rects.body, rects.screen, rects.face) for _, _, w, h in part)
        inked = sum(ch != "." for row in IDLE for ch in row)
        self.assertAlmostEqual(area, inked * PX * PY)

    def test_look_moves_the_face_and_cursor_hides(self):
        right = pose_rects("idle", look=1)
        self.assertAlmostEqual(min(x for x, *_ in right.face), 6 * PX)  # the > starts one column later
        left = pose_rects("idle", look=-1)
        self.assertAlmostEqual(min(x for x, *_ in left.face), 4 * PX)
        no_cursor = pose_rects("idle", cursor=False)
        self.assertEqual(len(no_cursor.face), len(pose_rects("idle").face) - 1)  # the _ run is gone


class PetBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.pet = CodexPet(random.Random(1))

    def test_moods(self):
        self.assertEqual(choose_mood(None, 0, 0, 0), "asleep")
        self.assertEqual(choose_mood(40, 0, 0, 2), "idle")
        self.assertEqual(choose_mood(40, 1, 0, 2), "work")
        self.assertEqual(choose_mood(40, 1, 1, 2), "wait")
        self.assertEqual(choose_mood(100, 1, 1, 2), "spent")

    def test_asleep_is_still_with_dim_closed_eyes(self):
        self.pet.set_inputs(None, 0, 0, 0, [])
        frames = [self.pet.step(200) for _ in range(50)]
        self.assertEqual({f.pose for f in frames}, {"asleep"})
        self.assertEqual({f.x for f in frames}, {frames[0].x})
        self.assertEqual(frames[0].face_opacity, 0.4)
        self.assertEqual(self.pet.mood_text(), "resting")

    def test_working_types_and_the_cursor_blinks(self):
        self.pet.set_inputs(40, 1, 0, 1, [])
        frames = [self.pet.step(200) for _ in range(20)]
        self.assertEqual({f.pose for f in frames}, {"type-1", "type-2"})
        self.assertEqual({f.cursor for f in frames}, {True, False})

    def test_waiting_shows_a_question_mark(self):
        self.pet.set_inputs(40, 1, 1, 1, [])
        frame = self.pet.step(200)
        self.assertEqual((frame.pose, frame.bubble), ("wait", "?"))
        self.assertGreater(frame.bubble_bottom, 44)

    def test_finished_jumps_then_settles(self):
        self.pet.set_inputs(40, 0, 0, 1, ["finished"])
        frames = [self.pet.step(200) for _ in range(ACT_LENGTHS["jump"])]
        self.assertEqual([f.pose for f in frames[:2]], ["crouch", "crouch"])
        self.assertIn("jump", {f.pose for f in frames})
        self.assertGreater(max(f.lift for f in frames), 6)
        self.assertIsNone(self.pet.act)
        self.assertEqual(self.pet.step(200).lift, 0)

    def test_failed_droops_for_about_three_seconds(self):
        self.pet.set_inputs(40, 0, 0, 1, ["failed"])
        frames = [self.pet.step(200) for _ in range(ACT_LENGTHS["failed"])]
        self.assertEqual({f.pose for f in frames}, {"failed"})
        self.assertGreaterEqual(ACT_LENGTHS["failed"] * frames[0].interval_ms, 2900)
        self.assertNotEqual(self.pet.step(200).pose, "failed")

    def test_failed_beats_finished_in_one_update(self):
        self.pet.set_inputs(40, 0, 0, 1, ["finished", "failed"])
        self.assertEqual(self.pet.act, "failed")
        self.pet.set_inputs(40, 0, 0, 1, ["finished"])
        self.assertEqual(self.pet.act, "failed")

    def test_spent_holds_the_failed_pose_and_ignores_clicks(self):
        self.pet.set_inputs(100, 0, 0, 1, [])
        self.pet.click()
        self.assertIsNone(self.pet.act)
        self.assertEqual({self.pet.step(200).pose for _ in range(40)}, {"failed"})

    def test_click_waves(self):
        self.pet.set_inputs(40, 0, 0, 1, [])
        self.pet.click()
        self.assertEqual(self.pet.act, "wave")
        poses = {self.pet.step(200).pose for _ in range(ACT_LENGTHS["wave"])}
        self.assertEqual(poses, {"wave-1", "wave-2"})

    def test_idle_strolls_and_blinks(self):
        self.pet.set_inputs(40, 0, 0, 1, [])
        frames = [self.pet.step(300) for _ in range(800)]
        self.assertGreater(len({f.x for f in frames}), 1)
        poses = {f.pose for f in frames}
        self.assertIn("blink", poses)
        self.assertTrue({"walk-1", "walk-2"} <= poses)
        walking = [f for f in frames if f.pose.startswith("walk")]
        self.assertTrue(all(f.look in (-1, 1) for f in walking))

    def test_standing_pet_looks_at_the_cursor(self):
        self.pet.set_inputs(40, 0, 0, 1, [])
        frame = self.pet.step(200)
        self.assertEqual(self.pet.step(200, mouse_x=frame.x + 200).look, 1)
        self.assertEqual(self.pet.step(200, mouse_x=-100).look, -1)

    def test_narrow_area_keeps_pet_at_left(self):
        self.pet.set_inputs(40, 0, 0, 1, [])
        self.assertEqual({self.pet.step(10).x for _ in range(300)}, {0})


if __name__ == "__main__":
    unittest.main()

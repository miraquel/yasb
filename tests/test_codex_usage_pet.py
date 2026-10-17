"""Tests for the Codex pet: its art (every pose on Clawd's grid) and, later in the file, its
behaviour, driven with a seeded RNG and a fake clock so nothing depends on the real time.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.widgets.claude_usage.clawd import PX, PY  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()

"""Pixel hearts for the AI usage popups: how much of a limit window is left, tamagotchi-style.

Qt-free and shared by the Claude and Codex widgets; ``scene.HeartsView`` paints them. The
heart is pixel art in ``HEART_ROWS``, one ``HEART_PX`` square per ``#``.
"""

import math
from functools import lru_cache

Rect = tuple[float, float, float, float]

HEALTH_NAMES = {
    6: "full of energy",
    5: "fine",
    4: "a bit tired",
    3: "tired",
    2: "exhausted",
    1: "barely alive",
    0: "out of strength",
}

HEART_ROWS = (".##.##.", "#######", "#######", ".#####.", "..###..", "...#...")
HEART_PX = 1.4
HEART_W = 7 * HEART_PX
HEART_H = len(HEART_ROWS) * HEART_PX


@lru_cache(maxsize=4)
def heart_rects(columns: int = 7) -> tuple[Rect, ...]:
    """A pixel heart as rectangles; ``columns=4`` is the left half, for a half heart."""
    return tuple(
        (x * HEART_PX, y * HEART_PX, HEART_PX, HEART_PX)
        for y, row in enumerate(HEART_ROWS)
        for x in range(min(columns, len(row)))
        if row[x] == "#"
    )


def heart_halves(percent: float | None) -> int | None:
    """Heart halves (0..6) left of a limit window: each is ~16.7%, empty only at 100%."""
    if percent is None:
        return None
    return max(0, min(6, math.ceil(max(0.0, 100.0 - float(percent)) * 6 / 100.0)))

"""The Codex pet's art: every pose as text pixel art on Clawd's grid. Qt-free.

The pet is the default Codex pet - a blue cloud whose face is a little screen showing ``>_`` -
redrawn by hand at Clawd's width: 18 x 20 pixels of ``PX`` x ``PY`` units. In a pose ``.`` is
empty, ``#`` the body, ``S`` the screen and ``>`` a face light (the ``>_`` and the chest light).
Stored as rows of characters like Clawd's hearts rather than as block glyphs, which only switch
pixels in pairs of rows and would turn the cloud's bumps into towers.

Poses change only the face, the arms and the legs; the head's outline is the same in all of
them, so the animation reads as one pet. ``pose_rects`` turns a pose into rectangles for the
painter, merging each row's runs as ``clawd.geometry`` does.
"""

from dataclasses import dataclass
from functools import lru_cache

from core.utils.widgets.claude_usage.clawd import PX, PY

GRID_W = 18
GRID_H = 20
WIDTH = GRID_W * PX
HEIGHT = GRID_H * PY
# The screen's rows; ``look`` slides the face lights inside them.
FACE_ROWS = range(4, 11)
# The "_" of ">_", which blinks like a cursor while the pet types.
CURSOR = ((10, 8), (11, 8), (12, 8))

Rect = tuple[float, float, float, float]

IDLE = (
    ".......####.......",
    "..####.####.####..",
    ".################.",
    ".################.",
    ".###SSSSSSSSSS###.",
    "###SSSSSSSSSSSS###",
    "###SS>SSSSSSSSS###",
    "###SSS>SSSSSSSS###",
    "###SS>SSSS>>>SS###",
    ".##SSSSSSSSSSSS##.",
    ".###SSSSSSSSSS###.",
    "..##############..",
    "....##########....",
    ".....########.....",
    "....##########....",
    "...#.###>>###.#...",
    "...#.########.#...",
    ".....########.....",
    "......##..##......",
    "......##..##......",
)

# Faces: rows 6-8 of the screen.
_CLOSED = ("###SSSSSSSSSSSS###", "###SSSSSSSSSSSS###", "###SS>>>SS>>>SS###")
_CROSS = ("###SS>S>SSSSSSS###", "###SSS>SSSSSSSS###", "###SS>S>SS>>>SS###")

# Bodies: rows 12-19, below the head.
_STRIDE = IDLE[12:18] + (
    ".....##....##.....",
    "....##......##....",
)
_PASSING = IDLE[12:18] + (
    ".......####.......",
    ".......####.......",
)
_TYPING = (
    "....##########....",
    ".....########.....",
    "...#SSSSSSSSSS#...",
    "...#SSSS>>SSSS#...",
    "...#SSSSSSSSSS#...",
)
_WAIT = (
    "....##########....",
    "...#.########.#...",
    "...#.########.#...",
    ".....###>>###.....",
    ".....########.....",
    ".....########.....",
    "......##..##......",
    "......##..##......",
)
_CROUCH = IDLE[12:18] + (
    "....###....###....",
    "...###......###...",
)
_JUMP = (
    "..#.##########.#..",
    "...#.########.#...",
    "....##########....",
    ".....###>>###.....",
    ".....########.....",
    ".....########.....",
    "......##..##......",
    ".......#..#.......",
)
_SLUMP = (
    "....##########....",
    ".....########.....",
    ".....########.....",
    ".....########.....",
    "...#.########.#...",
    "...#.########.#...",
    "......##..##......",
    "......##..##......",
)
_WAVE_UP = (
    "....##########.#..",
    ".....########.#...",
    "....##########....",
    "...#.###>>###.....",
    "...#.########.....",
    ".....########.....",
    "......##..##......",
    "......##..##......",
)
_WAVE_OUT = (
    "....##########..#.",
    ".....########..#..",
    "....###########...",
    "...#.###>>###.....",
    "...#.########.....",
    ".....########.....",
    "......##..##......",
    "......##..##......",
)
_SLEEPING = (*IDLE[12:15], "...#.########.#...", *IDLE[16:])


def _pose(face: tuple[str, str, str] | None = None, body: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """The idle pose with the face (rows 6-8) and/or the body (rows 12-19) swapped."""
    rows: list[str] = list(IDLE)
    if face is not None:
        rows[6:9] = face
    if body is not None:
        rows[12:20] = body
    return tuple(rows)


def _typing(*hands: int) -> tuple[str, ...]:
    # The laptop's back with a > on its lid, its lit keyboard below, and both hands on the keys;
    # the hands step between the two frames.
    keys = ["."] * 4 + [">"] * 10 + ["."] * 4
    for x in hands:
        keys[x] = "#"
    return _TYPING + ("".join(keys),) + IDLE[18:]


POSES: dict[str, tuple[str, ...]] = {
    "idle": IDLE,
    "blink": _pose(face=_CLOSED),
    "asleep": _pose(face=_CLOSED, body=_SLEEPING),
    "walk-1": _pose(body=_STRIDE),
    "walk-2": _pose(body=_PASSING),
    "type-1": _pose(body=_typing(5, 11)),
    "type-2": _pose(body=_typing(6, 12)),
    "wait": _pose(body=_WAIT),
    "crouch": _pose(body=_CROUCH),
    "jump": _pose(body=_JUMP),
    "failed": _pose(face=_CROSS, body=_SLUMP),
    "wave-1": _pose(body=_WAVE_UP),
    "wave-2": _pose(body=_WAVE_OUT),
}


@dataclass(frozen=True)
class PoseRects:
    """One pose as rectangles in logical units from the pet's top-left, one list per colour."""

    body: tuple[Rect, ...]
    screen: tuple[Rect, ...]
    face: tuple[Rect, ...]


@lru_cache(maxsize=256)
def pose_rects(pose: str, look: int = 0, cursor: bool = True) -> PoseRects:
    """Rasterise a pose. ``look`` (-1, 0, 1) slides the face lights a pixel that way inside the
    screen; ``cursor=False`` hides the ``_`` for the typing blink."""
    art = POSES[pose]
    grid = [list(row) for row in art]
    if not cursor:
        for x, y in CURSOR:
            if grid[y][x] == ">":
                grid[y][x] = "S"
    if look:
        lit = [(x, y) for y in FACE_ROWS for x in range(GRID_W) if grid[y][x] == ">"]
        for x, y in lit:
            grid[y][x] = "S"
        for x, y in lit:
            target = x + look
            # Only onto the screen: a light never spills onto the body.
            grid[y][target if 0 <= target < GRID_W and art[y][target] in "S>" else x] = ">"

    parts: dict[str, list[Rect]] = {"#": [], "S": [], ">": []}
    for y, row in enumerate(grid):
        x = 0
        while x < GRID_W:
            ch = row[x]
            start = x
            while x < GRID_W and row[x] == ch:
                x += 1
            if ch in parts:
                parts[ch].append((start * PX, y * PY, (x - start) * PX, PY))
    return PoseRects(tuple(parts["#"]), tuple(parts["S"]), tuple(parts[">"]))

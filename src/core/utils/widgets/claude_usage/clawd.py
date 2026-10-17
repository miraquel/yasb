"""Clawd, the crab from Claude Code's welcome screen, as a Qt-free animation model.

Ported from clawd-usage-winwidget (github.com/Enhed/clawd-usage-winwidget, MIT): the same
block-glyph body, the same click animations and the same moods. Nothing running - he burrows
into the sand and sleeps with only his eyes showing; sessions idle - he wanders and whistles,
and dozes standing after ten quiet minutes; a session working - he runs edge to edge kicking
up dust; a session waiting for you - he hops and waves under a "?"; the 5-hour limit nearly
gone - he sweats; used up - he lies legs-up with crosses for eyes.

Everything here is plain data so it can be tested without a display; ``ClawdScene`` paints
it. Coordinates are the original's logical units (one body pixel is ``PX`` x ``PY``), with
positions measured from the scene's left edge and *up* from the ground, the way WPF's
``Canvas.Left``/``Canvas.Bottom`` placed them, so the port can be checked line by line.
"""

import math
import random
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

# Clawd is 9 glyph cells by 3 rows, each cell split into 2x4 pixels: the quadrant glyphs and
# the eyelid's lower quarter then fit the grid losslessly.
COLS = 9
ROWS = 3
GRID_W = 2 * COLS
GRID_H = 4 * ROWS
PX = 2.0
PY = 2.2
WIDTH = GRID_W * PX
HEIGHT = GRID_H * PY
# The lower half of the legs row is empty, so the body is lowered by it onto the ground.
SINK = 2 * PY
BURROW_DIG = 4

# Glyph quadrants as bits: 1 top-left, 2 top-right, 4 bottom-left, 8 bottom-right.
_QUAD = {
    " ": 0, "█": 15, "▀": 3, "▄": 12, "▌": 5, "▐": 10, "▘": 1, "▝": 2,
    "▖": 4, "▗": 8, "▛": 7, "▜": 11, "▙": 13, "▟": 14,
}  # fmt: skip

# What sits left and right of the eyes (row 0) and of the chest (row 1).
_ARMS = {
    "down": (" ▐", "", "▝▜", "█▀"),
    "up": ("▗▟", "▄", " ▜", "█▘"),
    "right": (" ▐", "▄", "▝▜", "█▘"),  # one arm up, as Claude Code draws it
    "left": ("▗▟", "", " ▜", "█▀"),
}
_FEET = {
    "both": " ▝▝   ▝▝ ",
    "left": " ▝▝      ",
    "right": "      ▝▝ ",
}
# Turning in place: per glyph row, the glyphs and the column span where the dark face shows.
_FACING = {
    "right-12": ((" ▐█▜██▛█ ", 2, 8), ("▝▜██████▀", 2, 7), (" ▝▝   ▝▝ ", 0, 0)),
    "right-30": (("  █▛██▛▌ ", 2, 7), (" ▝█████▛ ", 2, 7), ("  ▘▘  ▘▘ ", 0, 0)),
    "right-55": (("  ▐█▛█▜  ", 3, 7), ("  ▐████  ", 3, 7), ("  ▝▝ ▝▝  ", 0, 0)),
    "right-75": (("   ██▛▌  ", 3, 6), ("   ███▌  ", 3, 6), ("   ▘  ▘  ", 0, 0)),
    "edge": (("   ▐██   ", 4, 6), ("   ▐██   ", 4, 6), ("   ▝ ▝   ", 0, 0)),
    "back-105": (("   ███▌  ", 3, 6), ("   ███▌  ", 3, 6), ("   ▘  ▘  ", 0, 0)),
    "back-125": (("  ▐████  ", 3, 7), ("  ▐████  ", 3, 7), ("  ▝▝ ▝▝  ", 0, 0)),
    "back-150": (("  █████▌ ", 2, 7), (" ▝█████▛ ", 2, 7), ("  ▘▘  ▘▘ ", 0, 0)),
    "back": ((" ▐██████ ", 2, 8), ("▝▜██████▀", 2, 7), (" ▝▝   ▝▝ ", 0, 0)),
    "left-75": (("   ▛██▌  ", 3, 6), ("   ███▌  ", 3, 6), ("   ▘  ▘  ", 0, 0)),
    "left-55": (("  ▐▜▛██  ", 3, 7), ("  ▐████  ", 3, 7), ("  ▝▝ ▝▝  ", 0, 0)),
    "left-30": (("  ▛██▛█▌ ", 2, 7), (" ▝█████▛ ", 2, 7), ("  ▘▘  ▘▘ ", 0, 0)),
    "left-12": ((" ▐▛███▜█ ", 2, 8), ("▝▜██████▀", 2, 7), (" ▝▝   ▝▝ ", 0, 0)),
}

# Dark pixels (dx, dy) from the top-left of each eye cell; a second tuple is the right eye.
# open/left/right/closed/wink are Claude Code's own; the rest are the original port's.
_EYES: dict[str, tuple[tuple[tuple[int, int], ...], ...]] = {
    "open": (((1, 2), (1, 3)),),
    "left": (((0, 0), (0, 1)),),
    "right": (((2, 0), (2, 1)),),
    "closed": (((0, 3), (1, 3)),),
    "blink": (((0, 3), (1, 3)),),
    "wink": (((1, 2), (1, 3)), ((0, 3), (1, 3))),
    "happy": (((0, 3), (1, 2), (2, 3)),),
    "focus": (((1, 3),),),
    "wide": (((0, 1), (1, 1), (0, 2), (1, 2), (0, 3), (1, 3)),),
    "x": (((0, 1), (2, 1), (1, 2), (0, 3), (2, 3)),),
    "yawn": (((0, 3), (1, 3)),),
    "gasp": (((0, 1), (2, 1), (1, 2), (0, 3), (2, 3)),),
}

MOODS = ("sleep", "doze", "idle", "work", "wait", "dead")
MOOD_NAMES = {
    "sleep": "sleeping",
    "doze": "dozing",
    "idle": "wandering",
    "work": "working",
    "wait": "waiting for you",
    "dead": "limit reached",
}
HEALTH_NAMES = {
    6: "full of energy",
    5: "fine",
    4: "a bit tired",
    3: "tired",
    2: "exhausted",
    1: "barely alive",
    0: "out of strength",
}

# Health by heart halves, applied on top of any mood: pace, tired eyes, yawns, sweat,
# swaying and stumbling. Zero halves is the "dead" mood.
_TIERS: dict[int, dict[str, Any]] = {
    6: {"speed": 1.25, "hop": 300},
    5: {"speed": 1.0},
    4: {"speed": 0.9, "yawn": 350},
    3: {"speed": 0.75, "yawn": 200, "eyes": "focus"},
    2: {"speed": 0.55, "yawn": 160, "eyes": "focus", "sweat": True},
    1: {"speed": 0.35, "eyes": "blink", "sweat": True, "stagger": True, "stumble": 220},
    0: {"speed": 0.0},
}

# Claude Code's animations run at its own pace; everything else ticks a little slower.
CLAUDE_FRAME_MS = 60
FRAME_MS = 90

CONFETTI_COLORS = ("#F87171", "#FBBF24", "#4ADE80", "#60A5FA", "#A78BFA", "#D77757")
HEART_ROWS = (".##.##.", "#######", "#######", ".#####.", "..###..", "...#...")
HEART_PX = 1.4
HEART_W = 7 * HEART_PX
HEART_H = len(HEART_ROWS) * HEART_PX

# The soul: a translucent mini-Clawd on a thread, which leaves the mouth when he is clicked
# while lying at the limit, hangs a moment and gets sucked back in.
_SOUL_UP = 26
_SOUL_BACK = 48
_SOUL_TOP = 20.0
SOUL_PX = 1.4
_SOUL_ART = (
    "..########..",
    "..#.####.#..",
    "############",
    "..########..",
    "...######...",
    "....####....",
    ".....##.....",
)

Rect = tuple[float, float, float, float]


# ------------------------------------------------------------- Claude Code animations ----
# A frame is a pose plus an offset: ``off`` lowers it by whole glyph rows (1 crouched with the
# legs hidden, 3 fully hidden, negative above the frame), ``x`` shifts it by cells, ``poof``
# puffs dust at the sides while crouched and ``shadow`` draws the coin-hop shadow. Anything
# outside the 9x3 frame is clipped, as in the terminal.
_POSES = {
    "default": "open/down/both",
    "arms-up": "open/up/both",
    "look-left": "left/down/both",
    "look-right": "right/down/both",
}


def _f(pose: str, n: int = 1, off: int = 0, x: int = 0, poof: str = "", shadow: str = "") -> list[dict]:
    if pose.startswith("face:"):
        frame = {"eyes": "open", "arms": "down", "feet": "both", "facing": pose[5:]}
    else:
        eyes, arms, feet = _POSES.get(pose, pose).split("/")
        frame = {"eyes": eyes, "arms": arms, "feet": feet, "facing": ""}
    frame.update(off=off, x=x, poof=poof, shadow=shadow)
    return [frame] * n


def _turn(facings: list[str], shadow: str = "") -> list[dict]:
    return [fr for p in facings for fr in _f(f"face:{p}", 1, shadow=shadow)]


def _build_sequences() -> dict[str, list[dict]]:
    crouch = _f("default", 1, off=1, poof="dot") + _f("default", 1, off=1, poof="wave")
    rest = _f("default")
    blink_out = _f("closed/down/both") + rest
    jump = crouch + _f("arms-up", 3) + rest + crouch + _f("arms-up", 3) + rest
    waddle = _f("look-right", 1, x=-9)
    for u in range(-6, 0):
        waddle += _f(f"right/down/{'left' if u % 2 == 0 else 'right'}", 2, x=u)
    return {
        "jump": jump,
        "look": _f("look-right", 5) + _f("look-left", 5) + rest,
        "celebrate": jump + _f("default", 3, off=1),
        "skip": (
            _f("default", 1, off=1, x=-9) + _f("arms-up", 2, x=-6) + _f("default", 1, x=-6)
            + _f("default", 1, off=1, x=-6) + _f("arms-up", 2, x=-3) + _f("default", 1, x=-3)
            + _f("default", 1, off=1, x=-3) + _f("arms-up", 2) + crouch + rest
        ),
        "spin": _f("look-left", 2) + _f("look-right", 2) + _f("look-left", 2) + _f("arms-up", 3) + rest,
        "peekaboo": (
            _f("default", 1, off=3) + _f("default", 3, off=2) + _f("look-right", 3, off=2)
            + _f("look-left", 3, off=2) + _f("default", 2, off=2) + _f("default", 1, off=1)
            + _f("arms-up", 4) + _f("default", 2) + blink_out
        ),
        "drop": (
            _f("arms-up", 1, off=-3) + _f("arms-up", 2, off=-2) + _f("arms-up", 2, off=-1)
            + _f("arms-up", 1) + crouch + _f("default", 3) + blink_out
        ),
        "waddle": waddle + _f("look-right", 2) + _f("default", 2) + blink_out,
        "peek": (
            _f("look-right", 1, x=-9) + _f("look-right", 5, x=-6) + _f("look-right", 3, x=-9)
            + _f("look-right", 4, x=-5) + _f("arms-up", 2, x=-3) + _f("arms-up", 2) + crouch + rest
        ),
        "wink": _f("wink/down/both", 5) + rest,
        "boop": (
            _f("closed/down/both", 1, off=1, poof="dot") + _f("closed/down/both", 2, off=1, poof="wave")
            + _f("look-left", 4) + _f("default", 2) + blink_out
        ),
        "tap": (
            _f("open/down/left", 2) + _f("open/down/right", 2) + _f("open/down/left", 2)
            + _f("open/down/right", 2) + _f("open/down/left", 1) + _f("open/down/right", 1)
            + _f("arms-up", 3) + rest
        ),
        "sneeze": (
            _f("closed/up/both", 4) + _f("closed/down/both", 2, off=1, poof="wave")
            + _f("closed/down/both", 2) + _f("default", 2) + blink_out
        ),
        "turn": (
            _turn(["right-12", "right-30", "right-55", "right-75", "edge"])
            + _turn(["back-105", "back-125", "back-150", "back", "back"])
            + _turn(["back-150", "back-125", "back-105", "edge"])
            + _turn(["left-75", "left-55", "left-30", "left-12"])
            + rest
        ),
        "coin-hop": (
            _f("default", 2, off=1) + _f("arms-up", 1, shadow="wide")
            + _turn(["right-55", "edge", "back-125", "back"], "narrow")
            + _turn(["back-125", "edge", "left-55"], "narrow")
            + _f("arms-up", 1, shadow="wide") + crouch + rest
        ),
    }  # fmt: skip


SEQUENCES = _build_sequences()
# On click, as in Claude Code: everything that starts in place (no slide-in).
CLICK_ACTS = tuple(k for k, v in SEQUENCES.items() if v[0]["x"] == 0 and k != "celebrate")
# When the popup first opens: an entrance from any of them, like a new version's first launch.
ENTRANCE_ACTS = tuple(k for k in SEQUENCES if k != "celebrate")
# Lengths in frames of the animations the original added on top of Claude Code's.
_CUSTOM_ACTS = {
    "wave": 24,
    "stretch": 22,
    "yawn": 22,
    "stumble": 20,
    "soul": 66,
    "burrow": 30,
    "unburrow": 28,
    "stir": 22,
}
ACT_LENGTHS = {**{k: len(v) for k, v in SEQUENCES.items()}, **_CUSTOM_ACTS}


# ----------------------------------------------------------------------- geometry ----
@dataclass(frozen=True)
class Geometry:
    """One rendered pose, as rectangles in logical units from the body's top-left corner.

    ``fx`` is dust and shadow, ``sand`` the burrow mound; both may reach outside the body's
    own box (the sand spray flies off to the sides), so the painter must not clip to it.
    """

    body: tuple[Rect, ...]
    eyes: tuple[Rect, ...]
    fx: tuple[Rect, ...]
    sand: tuple[Rect, ...]


@lru_cache(maxsize=512)
def geometry(
    eyes: str = "open",
    arms: str = "down",
    feet: str = "both",
    look: int = 0,
    flip: bool = False,
    off: int = 0,
    x: int = 0,
    facing: str = "",
    poof: str = "",
    shadow: str = "",
    dig: int = 0,
    spray: int = 0,
) -> Geometry:
    """Rasterise a pose: glyphs into a 18x12 pixel grid, then grid runs into rectangles."""
    # 0 empty, 1 body, 2 dark (eyes and face).
    grid = [[0] * GRID_H for _ in range(GRID_W)]

    def paint(glyphs: str, col: int, row: int, mode: str = "") -> None:
        # mode "eyes": dark background behind the glyph; "lid": dark glyph on the body colour.
        fg = 2 if mode == "lid" else 1
        bg = {"eyes": 2, "lid": 1}.get(mode, 0)
        for i, ch in enumerate(glyphs):
            for sy in range(4):
                for sx in range(2):
                    if ch == "▂":
                        on = sy == 3
                    else:
                        bit = (1 if sy < 2 else 4) * (2 if sx else 1)
                        on = bool(_QUAD.get(ch, 0) & bit)
                    value = fg if on else bg
                    if value:
                        grid[2 * (col + i) + sx][4 * row + sy] = value

    if facing:
        for r, (glyphs, start, end) in enumerate(_FACING[facing]):
            paint(glyphs[:start], 0, r)
            paint(glyphs[start:end], start, r, "eyes")
            paint(glyphs[end:], end, r)
    else:
        r1_left, r1_right, r2_left, r2_right = _ARMS[arms]
        paint(r1_left, 0, 0)
        paint("██████", 2, 0, "eyes")
        paint(r1_right, 8, 0)
        paint(r2_left, 0, 1)
        paint("█████", 2, 1, "eyes")
        paint(r2_right, 7, 1)
        paint(_FEET[feet], 0, 2)

        # Looking sideways with normal eyes uses Claude Code's own poses; any other
        # expression just shifts its pupils.
        shape, shift = eyes, 0
        if shape == "open" and look < 0:
            shape = "left"
        elif shape == "open" and look > 0:
            shape = "right"
        elif shape not in ("open", "left", "right", "wink"):
            shift = look
        per_eye = _EYES[shape]
        for k, eye_x in enumerate((4, 12)):
            for dx, dy in per_eye[min(k, len(per_eye) - 1)]:
                grid[eye_x + dx + shift][dy] = 2
        # Yawning and gasping: an open mouth under the eyes.
        if shape in ("yawn", "gasp"):
            for mx in range(8, 11):
                grid[mx][4] = 2
                grid[mx][5] = 2

    body: list[Rect] = []
    dark: list[Rect] = []
    # Lowered by `off` rows and shifted by `x` cells; anything outside the frame is clipped,
    # and whatever sank into the burrow is clipped at the ground.
    oy = 4 * off + dig
    ox = 2 * x
    limit = GRID_H - 2 if dig > 0 else GRID_H
    for y in range(GRID_H):
        sy = y
        if flip:
            # On his back, legs up; the empty lower half-row does not count.
            if y >= GRID_H - 2:
                continue
            sy = GRID_H - 3 - y
        yy = sy + oy
        if yy < 0 or yy >= limit:
            continue
        gx = 0
        while gx < GRID_W:
            colour = grid[gx][y]
            if not colour:
                gx += 1
                continue
            # Merge a run of same-coloured pixels into one rectangle.
            start = gx
            while gx < GRID_W and grid[gx][y] == colour:
                gx += 1
            left, right = max(0, start + ox), min(GRID_W, gx + ox)
            if right <= left:
                continue
            rect = (left * PX, yy * PY, (right - left) * PX, PY)
            (dark if colour == 2 else body).append(rect)

    fx: list[Rect] = []
    # Dust "·" and "~" at both edges of the bottom row while crouched.
    if poof and off > 0:
        if poof == "dot":
            puffs = ((0.6, 9.4, 0.8, 0.9),)
        else:
            puffs = ((0.0, 9.6, 0.7, 0.6), (0.7, 9.1, 0.6, 0.6), (1.3, 9.6, 0.7, 0.6))
        for cx in (0, GRID_W - 2):
            for px, py, pw, ph in puffs:
                fx.append(((cx + px) * PX, py * PY, pw * PX, ph * PY))
    # The coin-hop shadow.
    if shadow:
        start, span = (6, 6) if shadow == "wide" else (8, 2)
        fx.append((start * PX, (GRID_H - 0.5) * PY, span * PX, 0.5 * PY))

    sand: list[Rect] = []

    def grain(gx: float, gy: float, gw: float, gh: float) -> None:
        sand.append((gx * PX, gy * PY, gw * PX, gh * PY))

    # The mound over the burrow: a strip along the ground, and piles at the sides once dug in.
    if dig >= 1:
        grain(-2, GRID_H - 3, GRID_W + 4, 1)
    if dig >= 2:
        grain(-1, GRID_H - 4, GRID_W + 2, 1)
    if dig >= 3:
        grain(-1, GRID_H - 5, 2, 1)
        grain(GRID_W - 1, GRID_H - 5, 2, 1)
    # Grains fly in an arc from under the legs to both sides.
    if spray > 0:
        for k in (0, 1):
            d = spray + 2 * k
            spread = 1.5 + 0.9 * d
            height = (GRID_H - 4) - 0.9 * d * (5 - d) / 2
            grain(-spread, height, 0.8, 0.8)
            grain(GRID_W - 0.8 + spread, height, 0.8, 0.8)

    return Geometry(tuple(body), tuple(dark), tuple(fx), tuple(sand))


@lru_cache(maxsize=4)
def heart_rects(columns: int = 7) -> tuple[Rect, ...]:
    """A pixel heart as rectangles; ``columns=4`` is the left half, for a half heart."""
    return tuple(
        (x * HEART_PX, y * HEART_PX, HEART_PX, HEART_PX)
        for y, row in enumerate(HEART_ROWS)
        for x in range(min(columns, len(row)))
        if row[x] == "#"
    )


def soul_rects(height: float, t: int) -> tuple[Rect, ...]:
    """The soul at ``height`` above the mouth, swaying and pulling its thread; origin at the mouth."""
    p = SOUL_PX
    sway = 2.5 * math.sin(t / 4.0)
    rects: list[Rect] = []
    n = math.floor(height / p)
    for i in range(n):
        k = i / max(1, n)
        dx = sway * k + 1.2 * math.sin(t / 2.0 + i * 0.7) * math.sin(k * math.pi)
        rects.append((round(dx / p) * p - p / 2, -(i + 1) * p, p, p))
    top = -height - len(_SOUL_ART) * p
    x0 = round(sway / p) * p - 6 * p
    for y, row in enumerate(_SOUL_ART):
        x = 0
        while x < len(row):
            if row[x] != "#":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == "#":
                x += 1
            rects.append((x0 + start * p, top + y * p, (x - start) * p, p))
    return tuple(rects)


def heart_halves(percent: float | None) -> int | None:
    """Heart halves (0..6) left of the 5-hour window: each is ~16.7%, empty only at 100%."""
    if percent is None:
        return None
    return max(0, min(6, math.ceil(max(0.0, 100.0 - float(percent)) * 6 / 100.0)))


def choose_mood(percent: float | None, busy: int, waiting: int, total: int) -> str:
    """The resting mood the sessions and the 5-hour limit call for (before dozing)."""
    if percent is not None and percent >= 100:
        return "dead"
    if waiting:
        return "wait"
    if busy:
        return "work"
    if total:
        return "idle"
    return "sleep"


# -------------------------------------------------------------------------- frame ----
@dataclass
class Frame:
    """Everything the painter needs for one tick, in logical units (see the module docstring)."""

    geometry: Geometry
    x: float
    lift: float
    mood: str
    act: str | None
    bubble: str = ""
    bubble_bottom: float = 0.0
    # (left, bottom, font size, opacity)
    zzz: tuple[float, float, float, float] | None = None
    # (left, top, opacity), relative to the body's top-left
    sweat: tuple[float, float, float] | None = None
    # (left, bottom, opacity) per grain
    dust: list[tuple[float, float, float]] = field(default_factory=list)
    # (left, bottom, width, colour index) per flake
    confetti: list[tuple[float, float, float, int]] = field(default_factory=list)
    # (left, bottom, opacity)
    love: tuple[float, float, float] | None = None
    # (rects, mouth left, mouth bottom, opacity)
    soul: tuple[tuple[Rect, ...], float, float, float] | None = None
    # Halves to draw (blinking the lost part) and the beat scale when nearly out.
    hearts: int | None = None
    heart_beat: float = 1.0
    interval_ms: int = FRAME_MS


# -------------------------------------------------------------------------- model ----
class Clawd:
    """Clawd's state between ticks: where he is, what he is doing and what he feels like.

    ``set_inputs`` is called whenever the sessions or the 5-hour limit change, ``step`` once
    per animation tick, and ``click`` when someone pets him.
    """

    def __init__(self, rng: random.Random | None = None, crit_percent: float = 85, clock=time.monotonic):
        self._rng = rng or random.Random()
        self._clock = clock
        self.crit_percent = crit_percent
        self.x = -1.0
        self.dir = 1
        self.target: float | None = None
        self.look = 0
        self.tick = 0
        self.blink_at = 30
        self.mood = "sleep"
        self.current = "sleep"
        self.crit = False
        self.idle_since = clock()
        self.act: str | None = None
        self.act_t = 0
        self.percent: float | None = None
        self.halves: int | None = None
        self.lost_t = -1
        self.lost_from = 0
        self.love_t = -1
        self.note_t = -1
        self.confetti_t = -1
        self._confetti: list[list[float]] = []
        self.busy = -1
        self.waiting = 0
        self.last_reset: float | None = None
        self.last_percent: float | None = None
        self.buried = False

    # ----------------------------------------------------------------- inputs ----
    def set_inputs(self, percent: float | None, busy: int, waiting: int, total: int, reset_at: float | None) -> None:
        """Feed the latest sessions and 5-hour reading; ``reset_at`` is the reset's epoch seconds."""
        mood = choose_mood(percent, busy, waiting, total)
        if mood != self.mood:
            self.idle_since = self._clock()
        self.mood = mood
        # A session finished its reply (rather than stopping to ask something) - jump for it.
        if self.busy > 0 and busy < self.busy and waiting <= self.waiting and not self.act:
            self.start("jump")
        self.busy = busy
        self.waiting = waiting
        self.crit = percent is not None and percent >= self.crit_percent
        self.percent = percent
        # The 5-hour window reset: its reset moved well forward and usage dropped - celebrate.
        if reset_at is not None:
            if (
                self.last_reset is not None
                and reset_at > self.last_reset + 1800
                and self.last_percent is not None
                and percent is not None
                and percent < self.last_percent
            ):
                self.start("celebrate")
            self.last_reset = reset_at
            self.last_percent = percent

    def start(self, act: str) -> None:
        self.act = act
        self.act_t = 0
        if act == "celebrate":
            self._start_confetti()

    def start_entrance(self) -> None:
        if not self.act and not self.buried and self.mood != "dead":
            self.start(self._rng.choice(ENTRANCE_ACTS))

    def click(self) -> None:
        """Petted: a random Claude Code animation and a floating heart. Lying at the limit,
        his soul leaves the body instead; asleep in the burrow, he only peeks out."""
        if self.mood == "dead" or self.current == "dead":
            if not self.act:
                self.start("soul")
            return
        self.love_t = 0
        if self.buried and self.current == "sleep":
            if not self.act:
                self.start("stir")
            return
        if self.act:
            return
        self.start(self._rng.choice(CLICK_ACTS))

    def _start_confetti(self) -> None:
        rnd = self._rng.random
        x = max(self.x, 0.0)
        self._confetti = [
            [x - 12 + rnd() * (WIDTH + 24), 34 + rnd() * 12, 0.9 + rnd() * 1.2, (rnd() - 0.5) * 0.8] for _ in range(12)
        ]
        self.confetti_t = 0

    def mood_text(self) -> str:
        return MOOD_NAMES.get(self.current, self.current)

    # ------------------------------------------------------------------- step ----
    def _step_act(self, f: dict[str, Any]) -> str:
        """One frame of the running one-shot animation; returns the bubble over his head."""
        t = self.act_t
        act = self.act
        bubble = ""
        if act in SEQUENCES:
            # Claude Code's animations, frame by frame: the pose sets the gaze itself.
            frame = SEQUENCES[act][t]
            for key in ("eyes", "arms", "feet", "off", "x", "facing", "poof", "shadow"):
                f[key] = frame[key]
            f["look"] = 0
            if act == "celebrate":
                bubble = "!"
        elif act == "wave":
            f["look"] = 0
            f["eyes"] = "happy"
            f["arms"] = "down" if (t // 4) % 2 else "right"
        elif act == "stretch":
            if 4 <= t < 18:
                f.update(arms="up", eyes="closed", lift=1.5)
        elif act == "yawn":
            f["look"] = 0
            f["eyes"] = "yawn" if 3 <= t < 17 else "closed"
        elif act == "stumble":
            # Flops down with the legs hidden, then gets up and stares, stunned.
            if t < 12:
                f.update(off=1, eyes="closed")
            else:
                f["eyes"] = "wide"
            f["look"] = 0
        elif act == "soul":
            # The soul flies out of the open mouth on a thread, hangs over the body, then is
            # sucked back in - and the body twitches.
            f.update(flip=True, look=0)
            if t < 6:
                f["eyes"] = "x"
                f["feet"] = "left" if t % 2 else "right"
            elif t < _SOUL_BACK + 6:
                f["eyes"] = "gasp"
                f["soul_t"] = t
                if t < _SOUL_UP:
                    k = (t - 6) / (_SOUL_UP - 6.0)
                    f["soul"] = _SOUL_TOP * (1 - (1 - k) * (1 - k))
                elif t < _SOUL_BACK:
                    f["soul"] = _SOUL_TOP + 1.5 * math.sin((t - _SOUL_UP) / 2.5)
                else:
                    k = (t - _SOUL_BACK) / 6.0
                    f["soul"] = _SOUL_TOP * (1 - k * k)
            elif t < _SOUL_BACK + 9:
                f.update(eyes="wide", lift=2.5)
            else:
                f["eyes"] = "x"
        elif act == "burrow":
            # Looks around, digs in with the legs sinking into the sand, closes his eyes.
            if t < 4:
                f["look"] = -1 if t < 2 else 1
            elif t < 24:
                f.update(look=0, eyes="focus")
                f["dig"] = min(BURROW_DIG, math.floor((t - 4) / 3.5))
                f["feet"] = "left" if (t // 2) % 2 else "right"
                f["arms"] = "up" if (t // 2) % 2 else "down"
                f["spray"] = (t % 3) + 1
            else:
                f.update(look=0, dig=BURROW_DIG)
                f["eyes"] = "blink" if t < 27 else "closed"
        elif act == "unburrow":
            # Eyes wide, jumps out of the sand and shakes it off.
            f["look"] = 0
            if t < 3:
                f.update(dig=BURROW_DIG, eyes="wide")
            elif t < 9:
                f.update(dig=max(0, BURROW_DIG - (t - 3)), eyes="wide", arms="up", spray=(t % 3) + 1)
                if t == 8:
                    f["lift"] = 2
            elif t < 21:
                f["eyes"] = "closed"
                f["look"] = -1 if (t // 2) % 2 else 1
                f["feet"] = "left" if (t // 2) % 2 else "right"
                if t < 15:
                    f["spray"] = (t % 3) + 1
            elif t < 23:
                f["eyes"] = "blink"
        elif act == "stir":
            # Rises in the burrow, looks around and sinks back into the sand.
            f["dig"] = BURROW_DIG - 1 if t < 15 else BURROW_DIG
            if t < 3:
                f.update(eyes="wide", look=0)
            elif t < 13:
                f["look"] = -1 if t < 8 else 1
            elif t < 17:
                f.update(eyes="blink", look=0)
            else:
                f.update(eyes="closed", look=0)
        self.act_t += 1
        if self.act_t >= ACT_LENGTHS[act]:
            self.act = None
        return bubble

    def _mouse_look(self, mouse_x: float | None) -> int | None:
        if mouse_x is None:
            return None
        centre = self.x + WIDTH / 2
        if mouse_x > centre + 10:
            return 1
        if mouse_x < centre - 10:
            return -1
        return 0

    def _hearts(self) -> tuple[int | None, float]:
        halves = heart_halves(self.percent)
        if halves is None:
            self.halves = None
            return None, 1.0
        # Lost a half - the lost part blinks for a couple of seconds.
        if self.halves is not None and halves < self.halves:
            self.lost_t = 0
            self.lost_from = self.halves
        self.halves = halves
        show = halves
        if self.lost_t >= 0:
            if self.lost_t % 4 < 2:
                show = self.lost_from
            self.lost_t += 1
            if self.lost_t >= 16:
                self.lost_t = -1
        # The last bit of health left - the hearts beat.
        beat = 1.0
        if 0 < halves <= 2:
            phase = self.tick % 12
            if phase == 0:
                beat = 1.3
            elif phase == 1:
                beat = 1.15
        return show, beat

    def step(self, area_width: float, mouse_x: float | None = None) -> Frame:
        """Advance one tick. ``area_width`` is the play area in logical units; ``mouse_x`` is the
        cursor's logical x over it, or None when the cursor is elsewhere."""
        rnd = self._rng
        self.tick += 1
        span = max(0.0, area_width - WIDTH)
        if self.x < 0:
            self.x = span / 2
        if self.x > span:
            self.x = span

        mood = self.mood
        halves = heart_halves(self.percent)
        tier = _TIERS[5 if halves is None else halves]
        perky = tier["speed"] >= 0.9
        now = self._clock()
        # A cursor over him keeps him awake; ten quiet minutes and he dozes standing up.
        if mouse_x is not None:
            self.idle_since = now
        if mood == "idle" and now - self.idle_since >= 600:
            mood = "doze"

        # Falling asleep: burrows in once the current animation ends. Waking: climbs out at
        # once, whatever is playing.
        if mood == "sleep":
            if not self.buried and not self.act:
                self.buried = True
                self.start("burrow")
        elif self.buried:
            self.buried = False
            self.start("unburrow")

        f: dict[str, Any] = {
            "feet": "both", "look": self.look, "eyes": "open", "arms": "down", "flip": False, "lift": 0.0,
            "off": 0, "x": 0, "facing": "", "poof": "", "shadow": "", "soul": 0.0, "soul_t": 0, "dig": 0, "spray": 0,
        }  # fmt: skip
        self.current = mood
        bubble = ""
        zzz = False
        can_blink = True
        dust = False

        if self.act:
            bubble = self._step_act(f)
            can_blink = False
        elif mood == "sleep":
            f.update(dig=BURROW_DIG, eyes="closed", look=0)
            zzz = True
        elif mood == "doze":
            # Nods off, and now and then startles awake and goggles.
            f["look"] = 0
            phase = self.tick % 70
            if phase < 6:
                f["eyes"] = "wide"
                if phase < 2:
                    f["lift"] = 1.5
            else:
                f["eyes"] = "blink"
                zzz = True
        elif mood == "dead":
            f.update(flip=True, eyes="x", look=0)
            # Now and then his legs twitch.
            phase = self.tick % 50
            if phase < 6:
                f["feet"] = "left" if phase % 2 else "right"
        elif mood == "wait":
            bubble = "?"
            f["eyes"] = "wide"
            look = self._mouse_look(mouse_x)
            f["look"] = look if look is not None else 0
            # Hops and waves: hey, someone is waiting for you.
            phase = self.tick % 40
            if phase < 8:
                k = phase / 7.0
                f["lift"] = 12 * k * (1 - k)
                f["arms"] = "right"
        else:
            if mood == "work":
                speed = 1.6 * tier["speed"]
                # Runs from edge to edge.
                if self.target is None:
                    self.target = span if self.dir > 0 else 0.0
            else:
                speed = 0.6 * tier["speed"]
                if self.target is None:
                    if rnd.randrange(70) == 0:
                        self.target = rnd.random() * span
                    elif rnd.randrange(45) == 0:
                        self.look = rnd.randrange(-1, 2)
                    elif rnd.randrange(400) == 0:
                        self.start(rnd.choice(("wave", "stretch", "look")))
            walking = False
            if self.target is not None:
                d = self.target - self.x
                if abs(d) <= speed:
                    self.x = self.target
                    self.target = None
                    if mood == "work":
                        self.dir = -self.dir
                else:
                    self.dir = 1 if d > 0 else -1
                    self.x += speed * self.dir
                    self.look = self.dir
                    walking = True
            if walking:
                # The less energy, the slower the steps.
                step = 2 if mood == "work" else 3
                if tier["speed"] < 0.8:
                    step += 1
                if tier["speed"] < 0.5:
                    step += 1
                f["feet"] = "left" if (self.tick // step) % 2 else "right"
                if mood == "work":
                    if f["feet"] == "left" and perky:
                        f["lift"] = 1
                    dust = True
                    if perky and rnd.randrange(150) == 0:
                        self.start("jump")
                elif perky and self.note_t < 0 and rnd.randrange(80) == 0:
                    self.note_t = 0  # whistles while walking
                if tier.get("stumble") and rnd.randrange(tier["stumble"]) == 0:
                    self.start("stumble")
            elif self.crit:
                # The limit running out - his eyes dart nervously.
                self.look = -1 if (self.tick // 5) % 2 else 1
            else:
                # Standing - follows the cursor.
                look = self._mouse_look(mouse_x)
                if look is not None:
                    self.look = look
            f["look"] = self.look
            if mood == "work":
                f["eyes"] = "focus"
            # Full of energy - hops for joy; tired - yawns.
            if not self.act:
                if tier.get("hop") and rnd.randrange(tier["hop"]) == 0:
                    self.start("jump")
                if tier.get("yawn") and rnd.randrange(tier["yawn"]) == 0:
                    self.start("yawn")

        # Tired eyes on top of the normal and working ones.
        if tier.get("eyes") and not self.act and f["eyes"] in ("open", "focus"):
            f["eyes"] = tier["eyes"]
        # Petted - pleased.
        if self.love_t >= 0 and not self.act and f["eyes"] == "open":
            f["eyes"] = "happy"
        # Whistling: notes, when there is no other bubble.
        if self.note_t >= 0:
            if not bubble and mood == "idle":
                bubble = "♪"
            self.note_t += 1
            if self.note_t >= 30:
                self.note_t = -1
        if can_blink and f["eyes"] == "open" and self.tick >= self.blink_at:
            f["eyes"] = "blink"
            if self.tick >= self.blink_at + 1:
                self.blink_at = self.tick + rnd.randrange(25, 70)

        geo = geometry(
            f["eyes"], f["arms"], f["feet"], int(f["look"]), bool(f["flip"]), int(f["off"]), int(f["x"]),
            f["facing"], f["poof"], f["shadow"], int(f["dig"]), int(f["spray"]),
        )  # fmt: skip
        frame = Frame(geometry=geo, x=self.x, lift=float(f["lift"]), mood=mood, act=self.act)
        frame.interval_ms = CLAUDE_FRAME_MS if self.act in SEQUENCES else FRAME_MS
        # Barely alive - he sways.
        if tier.get("stagger") and mood not in ("sleep", "dead"):
            frame.x += 1.5 * math.sin(self.tick / 3.0)
        frame.x = round(frame.x)

        if zzz:
            p = (self.tick % 30) / 30.0
            base = 9 if f["dig"] > 0 else 12 if f["off"] > 0 else 19
            frame.zzz = (self.x + 28 + 3 * math.sin(p * 2 * math.pi), base + 14 * p, 7 + 4 * p, 1 - p)
        if bubble:
            frame.bubble = bubble
            frame.bubble_bottom = 22 + f["lift"] + 1.5 * math.sin(self.tick / 3.0)
        # Nearly out of the session limit - he sweats.
        if (self.crit or tier.get("sweat")) and mood not in ("sleep", "dead"):
            p = (self.tick % 20) / 20.0
            frame.sweat = (31 if f["look"] < 0 else 2, -2 + 6 * p - f["lift"], 1 - p)
        frame.hearts, frame.heart_beat = self._hearts()
        if dust:
            for i in range(3):
                p = ((self.tick + i * 3) % 9) / 9.0
                dx = 4 - 8 * p - 2 * i if self.dir > 0 else WIDTH - 6 + 8 * p + 2 * i
                frame.dust.append((self.x + dx, 4 * p, 0.7 * (1 - p)))
        if self.confetti_t >= 0:
            # Falls, drifts sideways and shimmers as it flips.
            for i, flake in enumerate(self._confetti):
                flake[1] -= flake[2]
                flake[0] += flake[3]
                if flake[1] > 0:
                    width = 2.5 if ((self.tick + i) // 2) % 2 else 1.2
                    frame.confetti.append((flake[0], flake[1], width, i % len(CONFETTI_COLORS)))
            self.confetti_t += 1
            if self.confetti_t >= 45:
                self.confetti_t = -1
        if self.love_t >= 0:
            # Petted - a heart floats up.
            k = self.love_t / 20.0
            frame.love = (self.x + WIDTH / 2 - 5 + 2 * math.sin(k * 6), 23 + f["lift"] + 14 * k, 1 - k)
            self.love_t += 1
            if self.love_t >= 20:
                self.love_t = -1
        if f["soul"] > 0.5:
            frame.soul = (
                soul_rects(f["soul"], f["soul_t"]),
                self.x + 9.5 * PX,
                f["lift"] + 6 * PY,
                0.7 + 0.15 * math.sin(f["soul_t"] / 1.7),
            )
        return frame

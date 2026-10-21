"""The Codex pet's behaviour, Qt-free: what it is doing and where, one frame at a time.

Driven like Clawd: ``set_inputs`` whenever the sessions or the main window change, ``step`` once
per animation tick and ``click`` when someone pets it. With no session open it sleeps, eyes shut
and its face dimmed; idle it blinks and now and then strolls across the strip, looking at the
cursor when it stands; while Codex works it types on its laptop; while Codex waits for your
approval it stands under a "?". A finished turn makes it jump, a failed or interrupted one makes
it droop for about three seconds, and once the window is used up it stays drooped. Positions are
in logical units from the strip's left edge and up from the ground; ``CodexPetScene`` paints it.
"""

import random
from dataclasses import dataclass

from core.utils.widgets.codex_usage.codex_pet_art import HEIGHT, WIDTH

FRAME_MS = 90
MOOD_NAMES = {
    "asleep": "resting",
    "idle": "idle",
    "work": "working",
    "wait": "waiting for you",
    "spent": "out of limit",
}
# One-shot reactions, in frames: failed is about three seconds at FRAME_MS.
ACT_LENGTHS = {"jump": 14, "failed": 33, "wave": 24}
_CROUCH_FRAMES = 2
_AIR_FRAMES = 10
_WALK_SPEED = 0.6


def choose_mood(percent: float | None, working: int, waiting: int, total: int) -> str:
    """The resting mood the sessions and the main window call for."""
    if percent is not None and percent >= 100:
        return "spent"
    if waiting:
        return "wait"
    if working:
        return "work"
    if total:
        return "idle"
    return "asleep"


@dataclass
class PetFrame:
    """Everything the painter needs for one tick."""

    pose: str
    look: int
    cursor: bool
    face_opacity: float
    x: float
    lift: float
    mood: str
    act: str | None
    bubble: str = ""
    bubble_bottom: float = 0.0
    interval_ms: int = FRAME_MS


class CodexPet:
    """The pet's state between ticks: where it is, what it is doing and what it reacts to."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self.x = -1.0
        self.dir = 1
        self.target: float | None = None
        self.look = 0
        self.tick = 0
        self.blink_at = 30
        self.mood = "asleep"
        self.act: str | None = None
        self.act_t = 0

    def set_inputs(self, percent: float | None, working: int, waiting: int, total: int, events: list[str]) -> None:
        """Feed the latest sessions, the main window's share used, and the turns that just ended."""
        self.mood = choose_mood(percent, working, waiting, total)
        # One reaction per update, and a failure is never cut short by a success.
        if "failed" in events:
            self._start("failed")
        elif "finished" in events and self.act != "failed":
            self._start("jump")

    def click(self) -> None:
        """Petted: a wave, unless it is busy reacting or the window is used up."""
        if self.act or self.mood == "spent":
            return
        self._start("wave")

    def mood_text(self) -> str:
        return MOOD_NAMES[self.mood]

    def _start(self, act: str) -> None:
        self.act = act
        self.act_t = 0

    def _step_act(self, act: str) -> tuple[str, float]:
        """One frame of the running reaction: its pose and how high it is off the ground."""
        t = self.act_t
        pose, lift = "failed", 0.0
        if act == "jump":
            air = t - _CROUCH_FRAMES
            if 0 <= air < _AIR_FRAMES:
                k = air / (_AIR_FRAMES - 1)
                pose, lift = "jump", 28 * k * (1 - k)
            else:
                pose = "crouch"
        elif act == "wave":
            pose = "wave-1" if (t // 4) % 2 == 0 else "wave-2"
        self.act_t += 1
        if self.act_t >= ACT_LENGTHS[act]:
            self.act = None
        return pose, lift

    def _mouse_look(self, mouse_x: float | None) -> int | None:
        if mouse_x is None:
            return None
        centre = self.x + WIDTH / 2
        if mouse_x > centre + 10:
            return 1
        if mouse_x < centre - 10:
            return -1
        return 0

    def _idle(self, span: float, mouse_x: float | None) -> tuple[str, int]:
        """Standing and blinking, or strolling to a spot it picked."""
        rnd = self._rng
        if self.target is None and span > 0 and rnd.randrange(70) == 0:
            self.target = rnd.random() * span
        if self.target is not None:
            d = self.target - self.x
            if abs(d) <= _WALK_SPEED:
                self.x = self.target
                self.target = None
            else:
                self.dir = 1 if d > 0 else -1
                self.x += _WALK_SPEED * self.dir
                self.look = self.dir
                return ("walk-1" if (self.tick // 3) % 2 else "walk-2"), self.dir
        look = self._mouse_look(mouse_x)
        if look is not None:
            self.look = look
        pose = "idle"
        if self.tick >= self.blink_at:
            pose = "blink"
            if self.tick >= self.blink_at + 1:
                self.blink_at = self.tick + rnd.randrange(25, 70)
        return pose, self.look

    def step(self, area_width: float, mouse_x: float | None = None) -> PetFrame:
        """Advance one tick. ``area_width`` is the strip in logical units; ``mouse_x`` is the
        cursor's logical x over it, or None when the cursor is elsewhere."""
        self.tick += 1
        span = max(0.0, area_width - WIDTH)
        if self.x < 0:
            self.x = span / 2
        self.x = min(self.x, span)

        mood = self.mood
        pose, look, cursor, face_opacity, lift, bubble = "idle", 0, True, 1.0, 0.0, ""
        if self.act:
            pose, lift = self._step_act(self.act)
        elif mood == "asleep":
            pose, face_opacity = "asleep", 0.4
        elif mood == "spent":
            pose = "failed"
        elif mood == "wait":
            # Hops now and then under its "?": someone is waiting for you.
            pose, bubble = "wait", "?"
            phase = self.tick % 40
            if phase < 8:
                k = phase / 7.0
                lift = 12 * k * (1 - k)
            look = self._mouse_look(mouse_x) or 0
        elif mood == "work":
            pose = "type-1" if (self.tick // 2) % 2 else "type-2"
            cursor = (self.tick // 5) % 2 == 0
        else:
            pose, look = self._idle(span, mouse_x)

        frame = PetFrame(pose, look, cursor, face_opacity, float(round(self.x)), lift, mood, self.act)
        if bubble:
            frame.bubble = bubble
            frame.bubble_bottom = HEIGHT + 2 + lift
        return frame

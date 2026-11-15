"""Frozen time for the clock widget tests."""

from datetime import datetime, tzinfo

import pytest

import core.widgets.yasb.clock as clock_module


class FrozenClock:
    """Stands in for ``datetime`` inside the clock module; the clock only ever calls ``datetime.now``."""

    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self, tz: tzinfo | None = None) -> datetime:
        return self.current.astimezone(tz) if tz else self.current.astimezone()


def freeze_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> FrozenClock:
    """Freeze the clock module's ``datetime.now`` at *now*; move it on through ``.current``."""
    clock = FrozenClock(now)
    monkeypatch.setattr(clock_module, "datetime", clock)
    return clock

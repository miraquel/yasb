# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.taskbar import BadgeConfig, TaskbarConfig
from core.widgets.services.taskbar import overlay_monitor
from core.widgets.services.taskbar.overlay_monitor import (
    TaskbarNotificationMonitor,
    count_by_app,
    match_notification_count,
)
from core.widgets.yasb.taskbar import BadgeLabel

BADGE_RGB = (255, 0, 0)
SIZE = 32


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_badge_is_off_by_default() -> None:
    config = TaskbarConfig.model_validate({})
    assert config.badge.enabled is False
    assert config.badge.type == "dot"
    assert config.badge.position == "top-right"


def test_badge_config_rejects_out_of_range_size() -> None:
    with pytest.raises(ValueError):
        BadgeConfig.model_validate({"size": 2})


# ---------------------------------------------------------------------------
# Counting and matching
# ---------------------------------------------------------------------------


def test_count_by_app_normalises_and_skips_blank_names() -> None:
    assert count_by_app(["WhatsApp", " whatsapp ", "Snipping Tool", "", "  "]) == {
        "whatsapp": 2,
        "snipping tool": 1,
    }


@pytest.mark.parametrize(
    ("process_name", "expected"),
    [
        ("WhatsApp.exe", 3),  # exact key after dropping .exe
        ("Discord.exe", 0),  # no notifications for it
        ("ms-teams.exe", 2),  # app name "teams" is inside the process key
        (None, 0),
        ("", 0),
    ],
)
def test_match_notification_count(process_name: str | None, expected: int) -> None:
    counts = {"whatsapp": 3, "teams": 2}
    assert match_notification_count(process_name, counts) == expected


def test_match_notification_count_with_no_counts() -> None:
    assert match_notification_count("WhatsApp.exe", {}) == 0


# ---------------------------------------------------------------------------
# Monitor snapshot with a fake listener (no real Notification Center)
# ---------------------------------------------------------------------------


@dataclass
class _DisplayInfo:
    display_name: str


@dataclass
class _AppInfo:
    display_info: _DisplayInfo


@dataclass
class _Notification:
    name: str | None

    @property
    def app_info(self) -> _AppInfo:
        if self.name is None:
            raise OSError("app info unavailable")
        return _AppInfo(_DisplayInfo(self.name))


@dataclass
class _FakeListener:
    notifications: Sequence[_Notification]
    kinds: list[object] = field(default_factory=lambda: [])
    fail: bool = False

    async def get_notifications_async(self, kinds: object) -> Sequence[_Notification]:
        self.kinds.append(kinds)
        if self.fail:
            raise OSError("listener gone")
        return self.notifications


def _snapshot(monitor: TaskbarNotificationMonitor, listener: _FakeListener) -> dict[str, int]:
    real = cast(overlay_monitor.management.UserNotificationListener, listener)
    return asyncio.run(monitor._snapshot(real))


def test_snapshot_counts_toasts_and_skips_unresolvable_apps(qapp: QApplication) -> None:
    monitor = TaskbarNotificationMonitor()
    listener = _FakeListener([_Notification("WhatsApp"), _Notification("WhatsApp"), _Notification(None)])
    try:
        assert _snapshot(monitor, listener) == {"whatsapp": 2}
        assert listener.kinds == [overlay_monitor.NotificationKinds.TOAST]
    finally:
        monitor._loop.close()


def test_snapshot_returns_empty_when_listener_fails(qapp: QApplication) -> None:
    monitor = TaskbarNotificationMonitor()
    try:
        assert _snapshot(monitor, _FakeListener([], fail=True)) == {}
    finally:
        monitor._loop.close()


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------


def _render(label: BadgeLabel) -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    label.render(painter)
    painter.end()
    return image


def _is_badge(image: QImage, x: int, y: int) -> bool:
    c = QColor(image.pixel(x, y))
    return (c.red(), c.green(), c.blue()) == BADGE_RGB and c.alpha() == 255


def _label(**cfg: object) -> BadgeLabel:
    label = BadgeLabel()
    label.setFixedSize(SIZE, SIZE)
    label.configure(BadgeConfig.model_validate({"enabled": True, "color": "#ff0000", "size": 10, **cfg}))
    return label


@pytest.mark.parametrize(
    ("position", "point"),
    [
        ("top-right", (SIZE - 5, 5)),
        ("top-left", (5, 5)),
        ("bottom-right", (SIZE - 5, SIZE - 5)),
        ("bottom-left", (5, SIZE - 5)),
    ],
)
def test_badge_paints_in_its_corner(qapp: QApplication, position: str, point: tuple[int, int]) -> None:
    label = _label(position=position)
    label.set_badge(True, count=1)
    image = _render(label)
    assert _is_badge(image, *point)
    assert not _is_badge(image, SIZE // 2, SIZE // 2)


def test_badge_offset_moves_it(qapp: QApplication) -> None:
    label = _label(position="top-left", offset_x=10, offset_y=10)
    label.set_badge(True)
    image = _render(label)
    assert _is_badge(image, 15, 15)
    assert not _is_badge(image, 3, 3)


def test_hidden_or_disabled_badge_paints_nothing(qapp: QApplication) -> None:
    hidden = _label()
    hidden.set_badge(False)
    assert not _is_badge(_render(hidden), SIZE - 5, 5)

    disabled = _label(enabled=False)
    disabled.set_badge(True, count=3)
    assert not _is_badge(_render(disabled), SIZE - 5, 5)

    unconfigured = BadgeLabel()
    unconfigured.setFixedSize(SIZE, SIZE)
    unconfigured.set_badge(True)
    assert not _is_badge(_render(unconfigured), SIZE - 5, 5)


def test_border_ring_surrounds_the_badge(qapp: QApplication) -> None:
    label = _label(position="top-left", offset_x=5, offset_y=5, border_color="#0000ff", border_width=3)
    label.set_badge(True)
    image = _render(label)
    # Badge centre (10, 10), radius 5; ring reaches radius 8
    assert _is_badge(image, 10, 10)
    ring = QColor(image.pixel(10, 16))
    assert (ring.red(), ring.green(), ring.blue()) == (0, 0, 255)


def test_number_mode_writes_the_count(qapp: QApplication) -> None:
    dot = _label(type="dot", size=20, font_size=14)
    dot.set_badge(True, count=7)
    number = _label(type="number", size=20, font_size=14)
    number.set_badge(True, count=7)
    assert _render(dot) != _render(number)

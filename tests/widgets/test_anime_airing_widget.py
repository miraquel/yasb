# pyright: reportPrivateUsage=false
"""Widget and service tests for anime airing: bar label states, the popup, and reminder toasts.

No network is touched: the widget gets a stub service, and the real service is built with
its fetch disabled and fed the schedule fixture directly. The popup body is filled into a
plain host frame, so no popup window is ever shown.
"""

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from core.validation.widgets.yasb.anime_airing import AnimeAiringConfig
from core.widgets.services.anime_airing import service as service_module
from core.widgets.services.anime_airing.service import AnimeAiringService, ReminderSettings
from core.widgets.services.anime_airing.sources import Snapshot
from core.widgets.yasb import anime_airing as widget_module
from core.widgets.yasb.anime_airing import AnimeAiringWidget
from tests.support.anime_airing import NOW, SNAPSHOT, USERNAME, at


class StubService(QObject):
    updated = pyqtSignal()

    def __init__(
        self,
        snapshot: Snapshot | None = None,
        loading: bool = False,
        error_kind: str = "",
        error_text: str = "",
    ) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.loading = loading
        self.error_kind = error_kind
        self.error_text = error_text
        self.username = USERNAME

    def refresh_now(self) -> None:
        pass

    def release(self) -> None:
        pass

    def test_reminder(self) -> None:
        pass


# The default icon, fa-tv (U+F26C).
ICON = "\uf26c"

type MakeWidget = Callable[..., AnimeAiringWidget]


def by_class(root: QWidget, cls: str) -> list[QWidget]:
    return [child for child in root.findChildren(QWidget) if cls in str(child.property("class") or "").split()]


def label_text(widget: QWidget) -> str:
    assert isinstance(widget, QLabel)
    return widget.text()


def classes(widget: QWidget) -> list[str]:
    return str(widget.property("class") or "").split()


def texts(widget: AnimeAiringWidget, alt: bool = False) -> list[str]:
    return [label.text() for label in (widget._widgets_alt if alt else widget._widgets)]


def set_now(monkeypatch: pytest.MonkeyPatch, target: object, now: datetime) -> None:
    monkeypatch.setattr(target, "_now", lambda: now)


@pytest.fixture
def make_widget(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeWidget]:
    widgets: list[AnimeAiringWidget] = []

    def make(stub: StubService, now: datetime = NOW, **options: Any) -> AnimeAiringWidget:
        config = AnimeAiringConfig.model_validate({"username": USERNAME, **options})

        def get_instance(*_: object) -> StubService:
            return stub

        with monkeypatch.context() as patch:
            patch.setattr(widget_module.AnimeAiringService, "get_instance", get_instance)
            widget = AnimeAiringWidget(config)
        set_now(monkeypatch, widget, now)
        widget._update_label()
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.deleteLater()


@pytest.fixture
def fill(qapp: QApplication) -> Iterator[Callable[[AnimeAiringWidget], QFrame]]:
    hosts: list[QFrame] = []

    def fill(widget: AnimeAiringWidget) -> QFrame:
        host = QFrame()
        hosts.append(host)
        widget._fill_popup(QVBoxLayout(host))
        return host

    yield fill
    for host in hosts:
        host.deleteLater()


# ----------------------------------------------------------------------
# Bar label
# ----------------------------------------------------------------------


def test_counts_down_to_the_soonest_episode(make_widget: MakeWidget) -> None:
    widget = make_widget(StubService(SNAPSHOT))
    assert texts(widget) == [ICON, "Mushoku Tensei III… 1d 6h"]
    assert "unwatched" in classes(widget._widgets[1])


def test_alt_label(make_widget: MakeWidget) -> None:
    widget = make_widget(StubService(SNAPSHOT))
    widget._toggle_label()
    assert texts(widget, alt=True) == [ICON, "Ep 14 · Tomorrow 18:00"]
    assert not widget._widgets[1].isVisibleTo(widget)


def test_soon(make_widget: MakeWidget) -> None:
    widget = make_widget(StubService(SNAPSHOT), now=at(9, 27, 17, 30))
    assert texts(widget)[1] == "Mushoku Tensei III… 30m"
    assert "soon" in classes(widget._widgets[1])


@pytest.mark.parametrize(
    ("stub_options", "text", "state"),
    [
        ({"loading": True}, "Loading...", "loading"),
        ({"error_kind": "user", "error_text": "MyAnimeList user not found"}, "User not found", "error"),
        ({"error_kind": "network"}, "Offline", "error"),
    ],
)
def test_states_replace_the_template(
    make_widget: MakeWidget, stub_options: dict[str, Any], text: str, state: str
) -> None:
    widget = make_widget(StubService(**stub_options))
    widget._toggle_label()
    assert texts(widget, alt=True) == [ICON, text]
    assert state in classes(widget._widgets_alt[1])


def test_nothing_airing(make_widget: MakeWidget) -> None:
    widget = make_widget(StubService(SNAPSHOT), now=at(10, 20, 0))
    assert texts(widget) == [ICON, "Nothing airing"]


def test_title_limit_and_language(make_widget: MakeWidget) -> None:
    widget = make_widget(StubService(SNAPSHOT), max_title_length=0, title_language="english")
    assert texts(widget)[1] == "Mushoku Tensei: Jobless Reincarnation Season 3 1d 6h"


# ----------------------------------------------------------------------
# Popup
# ----------------------------------------------------------------------


def test_hero_and_rows(make_widget: MakeWidget, fill: Callable[[AnimeAiringWidget], QFrame]) -> None:
    widget = make_widget(StubService(SNAPSHOT), menu={"show_covers": False})
    host = fill(widget)
    assert label_text(by_class(host, "hero-countdown")[0]) == "1d 6h"
    assert label_text(by_class(host, "hero-meta")[0]) == "Episode 14 · Tomorrow 18:00"
    assert label_text(by_class(host, "hero-unwatched")[0]) == "1 episode to catch up on"
    rows = by_class(host, "show-row")
    assert len(rows) == 3
    assert rows[0].property("class") == "show-row active unwatched"
    assert cast(widget_module._LinkFrame, rows[0]).url == "https://myanimelist.net/anime/59193"
    titles = [label_text(cast(QWidget, row.findChild(QLabel))) for row in rows]
    assert titles[2] == "JoJo SBR - 2nd & 3rd STAGE"
    badges = by_class(host, "show-unwatched")
    assert [label_text(b) for b in badges] == ["1 new", "", ""]


def test_footer_says_how_fresh(make_widget: MakeWidget, fill: Callable[[AnimeAiringWidget], QFrame]) -> None:
    host = fill(make_widget(StubService(SNAPSHOT), now=NOW + timedelta(minutes=5)))
    assert label_text(by_class(host, "status")[0]) == "Updated 5m ago"


def test_stale_footer(make_widget: MakeWidget, fill: Callable[[AnimeAiringWidget], QFrame]) -> None:
    stub = StubService(SNAPSHOT, error_kind="network", error_text="AniList unreachable")
    host = fill(make_widget(stub, now=NOW + timedelta(hours=2)))
    status = by_class(host, "status")[0]
    assert label_text(status) == "Offline · updated 2h ago"
    assert "stale" in classes(status)


def test_error_placeholder(make_widget: MakeWidget, fill: Callable[[AnimeAiringWidget], QFrame]) -> None:
    stub = StubService(error_kind="user", error_text="MyAnimeList user not found, or the list is private")
    host = fill(make_widget(stub))
    assert label_text(by_class(host, "placeholder")[0]) == "MyAnimeList user not found, or the list is private"
    assert by_class(host, "show-row") == []


def test_rows_update_in_place_then_rebuild_when_the_order_changes(
    qapp: QApplication,
    make_widget: MakeWidget,
    fill: Callable[[AnimeAiringWidget], QFrame],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = make_widget(StubService(SNAPSHOT))
    host = fill(widget)
    first = by_class(host, "show-row")[0]
    set_now(monkeypatch, widget, NOW + timedelta(minutes=1))
    widget._refresh_popup()
    assert by_class(host, "show-row")[0] is first
    assert label_text(by_class(host, "hero-countdown")[0]) == "1d 5h"
    set_now(monkeypatch, widget, at(9, 27, 18, 1))
    widget._refresh_popup()
    qapp.processEvents()
    assert len(by_class(host, "show-row")) == 2
    assert label_text(by_class(host, "hero-meta")[0]) == "Episode 19 · Wed 20:00"


# ----------------------------------------------------------------------
# Covers
# ----------------------------------------------------------------------


def test_cover_is_drawn_at_screen_density_with_rounded_corners(qapp: QApplication, tmp_path: Path) -> None:
    path = str(tmp_path / "cover.png")
    source = QPixmap(100, 142)
    source.fill(QColor("#c03030"))
    source.save(path)
    label = widget_module._CoverLabel(path, (30, 43, 3))
    pixmap = label.pixmap()
    dpr = label.devicePixelRatioF()
    assert (pixmap.width(), pixmap.height()) == (round(30 * dpr), round(43 * dpr))
    assert pixmap.devicePixelRatio() == dpr
    image = pixmap.toImage()
    # The corner is clipped away. Antialiasing leaves a trace of coverage at 1x (7/255),
    # so it is compared against the opaque centre rather than with an exact 0.
    assert image.pixelColor(0, 0).alpha() < 32
    assert image.pixelColor(pixmap.width() // 2, pixmap.height() // 2).alpha() == 255
    assert image.pixelColor(pixmap.width() // 2, pixmap.height() // 2).name() == "#c03030"
    label.deleteLater()


def test_missing_cover_leaves_an_empty_slot(qapp: QApplication) -> None:
    label = widget_module._CoverLabel(None, (30, 43, 3))
    assert label.pixmap().isNull()
    assert (label.width(), label.height()) == (30, 43)
    label.deleteLater()


# ----------------------------------------------------------------------
# Service reminders
# ----------------------------------------------------------------------


type Toast = tuple[str, str, str]
type MakeService = Callable[..., AnimeAiringService]


class FakeToastNotifier:
    """Stands in for ``ToastNotifier`` and records what each reminder would have shown."""

    shown: list[Toast] = []

    def show(self, icon: str, title: str, message: str, launch_url: str = "", launch_label: str = "") -> None:
        FakeToastNotifier.shown.append((title, message, launch_url))


@pytest.fixture
def toasts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Toast]]:
    def cache_path(username: str) -> Path:
        return tmp_path / "cache.json"

    def cover_path(anilist_id: int, url: str) -> Path:
        return tmp_path / f"{anilist_id}.jpg"

    monkeypatch.setattr(service_module, "cache_path", cache_path)
    monkeypatch.setattr(service_module, "cover_path", cover_path)
    monkeypatch.setattr(service_module, "ToastNotifier", FakeToastNotifier)
    FakeToastNotifier.shown = []
    AnimeAiringService._instances.clear()
    yield FakeToastNotifier.shown
    AnimeAiringService._instances.clear()


@pytest.fixture
def make_service(qapp: QApplication, toasts: list[Toast], monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeService]:
    services: list[AnimeAiringService] = []

    def make(now: datetime, **reminders: Any) -> AnimeAiringService:
        settings = ReminderSettings(**reminders)

        def no_fetch(self: AnimeAiringService) -> None:
            pass

        with monkeypatch.context() as patch:
            patch.setattr(AnimeAiringService, "refresh_now", no_fetch)
            service = AnimeAiringService.get_instance(USERNAME, ("watching",), 1800, settings)
        set_now(monkeypatch, service, now)
        services.append(service)
        return service

    yield make
    for service in services:
        service.release()


def test_first_snapshot_replays_nothing(make_service: MakeService, toasts: list[Toast]) -> None:
    service = make_service(NOW, catch_up_hours=72)
    service._on_done(SNAPSHOT, "")
    assert toasts == []


def test_fires_once_at_broadcast_and_survives_a_restart(
    make_service: MakeService, toasts: list[Toast], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(NOW)
    service._on_done(SNAPSHOT, "")
    set_now(monkeypatch, service, at(9, 27, 18, 0))
    service._check_reminders()
    service._check_reminders()
    assert toasts == [
        (
            "Mushoku Tensei III: Isekai Ittara Honki Dasu",
            "Episode 14 is out now · 2 to catch up on",
            "https://myanimelist.net/anime/59193",
        )
    ]

    # A new process starts with no live services, only the cache file on disk.
    AnimeAiringService._instances.clear()
    restarted = make_service(at(9, 27, 18, 3))
    assert restarted is not service
    assert restarted.snapshot is not None
    restarted._check_reminders()
    assert len(toasts) == 1


def test_titles_are_xml_escaped(
    make_service: MakeService, toasts: list[Toast], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(NOW)
    service._on_done(SNAPSHOT, "")
    set_now(monkeypatch, service, at(10, 2, 15, 0))
    service._check_reminders()
    # '&' in a title would otherwise break the toast's XML.
    assert "JoJo SBR - 2nd &amp; 3rd STAGE" in [title for title, _, _ in toasts]


def test_disabled(make_service: MakeService, toasts: list[Toast], monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service(NOW, enabled=False)
    service._on_done(SNAPSHOT, "")
    set_now(monkeypatch, service, at(9, 27, 18, 0))
    service._check_reminders()
    assert toasts == []


def test_retry_only_for_errors_that_can_clear(make_service: MakeService) -> None:
    service = make_service(NOW)
    service._on_done(None, "user:MyAnimeList user not found")
    assert not service._retry.isActive()
    assert service.error_kind == "user"
    service._on_done(None, "network:AniList unreachable")
    assert service._retry.isActive()


def test_one_service_per_configuration(make_service: MakeService) -> None:
    first = make_service(NOW)
    second = make_service(NOW)
    assert first is second
    assert first._refcount == 2

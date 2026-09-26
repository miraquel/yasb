import re
from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.utils.tooltip import set_tooltip
from core.utils.utilities import ElidedLabel, PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.anime_airing import AnimeAiringConfig
from core.widgets.base import BaseWidget
from core.widgets.services.anime_airing.schedule import (
    Show,
    build_shows,
    format_ago,
    format_air_time,
    format_countdown,
    shorten,
    upcoming_shows,
)
from core.widgets.services.anime_airing.service import AnimeAiringService, ReminderSettings, cover_path

# An episode this close is "soon": the label gains a class a theme can pick up.
_SOON_SECONDS = 3600

_HERO_COVER = (60, 86)
_ROW_COVER = (30, 43)

_ERROR_TEXT = {
    "config": "Set username",
    "user": "User not found",
    "rate_limited": "Rate limited",
    "network": "Offline",
    "response": "Unavailable",
}


class _LinkFrame(QFrame):
    """A frame that opens a URL when clicked."""

    def __init__(self, url: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.url:
            QDesktopServices.openUrl(QUrl(self.url))
        super().mousePressEvent(event)


def _label(cls: str, text: str = "", kind: type[QLabel] = QLabel) -> QLabel:
    """A popup label carrying *cls*, with QLabel's automatic indent switched off.

    The default indent of -1 becomes half an 'x' of the label's font as soon as a
    stylesheet gives it a margin, padding or border. Labels stacked in one column then
    drift right by different amounts per font size - 3px at 11px, 7px at a 28px
    countdown - and no longer share a left edge. Pinning it to 0 holds under any theme.
    """
    label = kind(text)
    label.setProperty("class", cls)
    label.setIndent(0)
    return label


def fit_to_width(widget: QWidget) -> None:
    """Size *widget* to its contents, measuring wrapped text at the width it really gets.

    adjustSize() takes the height at the natural width, before a minimum width widens the
    popup, so a word-wrapped title is measured on more lines than it paints and leaves a
    gap under it.
    """
    widget.adjustSize()
    layout = widget.layout()
    if layout is not None and layout.hasHeightForWidth():
        widget.resize(widget.width(), layout.totalHeightForWidth(widget.width()))


class AnimeAiringWidget(BaseWidget):
    """Counts down to the next episode of whatever is on a MyAnimeList list.

    MyAnimeList supplies the list and the watched counts; AniList supplies the airing
    times (see ``services.anime_airing.sources``). The shared ``AnimeAiringService`` does
    the fetching and fires the reminder toasts, so this class only renders: it re-derives
    everything from the latest snapshot on every minute tick.
    """

    validation_schema = AnimeAiringConfig

    def __init__(self, config: AnimeAiringConfig):
        super().__init__(class_name=f"anime-airing-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._service_released = False
        self._popup: PopupWidget | None = None
        self._popup_layout: QVBoxLayout | None = None
        self._popup_key: tuple | None = None
        self._popup_hero: dict[str, QWidget] = {}
        self._popup_rows: list[dict[str, QWidget]] = []
        self._popup_status: QLabel | None = None

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        for label in (*self._widgets, *self._widgets_alt):
            label.setProperty("base_class", label.property("class") or "")

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_card", self._toggle_card)
        self.register_callback("refresh", self._refresh)
        self.register_callback("open_list", self._open_list)
        self.register_callback("test_reminder", self._test_reminder)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle

        n = config.notifications
        self._service = AnimeAiringService.get_instance(
            config.username,
            tuple(config.statuses),
            config.update_interval,
            ReminderSettings(n.enabled, n.offset_minutes, n.catch_up_hours, config.title_language),
        )
        self._service.updated.connect(self._on_updated)
        self.destroyed.connect(lambda *_: self._release_service())
        self._update_label()

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    def _release_service(self) -> None:
        if getattr(self, "_service_released", False):
            return
        self._service_released = True
        try:
            self._service.release()
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._release_service()
        super().closeEvent(event)

    def _on_updated(self) -> None:
        self._update_label()
        self._sync_popup()

    def _refresh(self) -> None:
        self._service.refresh_now()

    def _open_list(self) -> None:
        if self.config.username:
            QDesktopServices.openUrl(QUrl(f"https://myanimelist.net/animelist/{self.config.username}?status=1"))

    def _test_reminder(self) -> None:
        self._service.test_reminder()

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()

    def _upcoming(self) -> list[Show]:
        return upcoming_shows(build_shows(self._service.snapshot, self._now(), self.config.title_language))

    # ------------------------------------------------------------------
    # Bar label
    # ------------------------------------------------------------------

    def _state(self, upcoming: list[Show]) -> tuple[str, str]:
        """Return (state class, title text) for when there is no countdown to show."""
        service = self._service
        if service.snapshot is None:
            if service.loading:
                return "loading", "Loading..."
            return "error", _ERROR_TEXT.get(service.error_kind, "Unavailable")
        if not upcoming:
            return "empty", "Nothing airing"
        return "", ""

    def _label_options(self, upcoming: list[Show]) -> tuple[dict[str, str], list[str]]:
        now = self._now()
        state, fallback = self._state(upcoming)
        unwatched = sum(show.unwatched or 0 for show in upcoming)
        options = {
            "{icon}": self.config.icons.default,
            "{title}": fallback,
            "{episode}": "",
            "{countdown}": "",
            "{air_time}": "",
            "{airing_count}": str(len(upcoming)),
            "{unwatched}": str(unwatched),
        }
        states = [state] if state else []
        if not state:
            show = upcoming[0]
            options["{title}"] = shorten(show.title, self.config.max_title_length)
            options["{episode}"] = str(show.next_episode or "")
            options["{countdown}"] = format_countdown(show.next_at, now)
            options["{air_time}"] = format_air_time(show.next_at, now)
            if (show.next_at - now).total_seconds() <= _SOON_SECONDS:
                states.append("soon")
            if unwatched:
                states.append("unwatched")
        return options, states

    def _update_label(self) -> None:
        upcoming = self._upcoming()
        options, states = self._label_options(upcoming)
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_content = self.config.label_alt if self._show_alt_label else self.config.label
        label_parts = [p for p in re.split(r"(<span.*?>.*?</span>)", active_content) if p]
        # With nothing to count down, a template such as "Ep {episode} · {air_time}" would
        # render as stray words and separators, so the first text label carries the state's
        # own message and any others go blank.
        message = options["{title}"] if set(states) & {"loading", "error", "empty"} else None
        widget_index = 0
        for part in label_parts:
            part = part.strip()
            if not part or widget_index >= len(active_widgets):
                continue
            widget = active_widgets[widget_index]
            widget_index += 1
            if not isinstance(widget, QLabel):
                continue
            is_icon = "<span" in part and "</span>" in part
            if is_icon:
                part = re.sub(r"<span.*?>|</span>", "", part)
            if message is not None and not is_icon:
                text, message = message, ""
            else:
                for placeholder, value in options.items():
                    part = part.replace(placeholder, value)
                text = " ".join(part.split())
            widget.setText(text)
            widget.setVisible(bool(text) and (widget in self._widgets) != self._show_alt_label)
            base = widget.property("base_class") or ""
            widget.setProperty("class", " ".join(p for p in (base, *states) if p))
            refresh_widget_style(widget)
        self._update_tooltip(upcoming)

    def _update_tooltip(self, upcoming: list[Show]) -> None:
        if not self.config.tooltip:
            return
        now = self._now()
        if not upcoming:
            _, text = self._state(upcoming)
            detail = self._service.error_text if self._service.error_kind else ""
            set_tooltip(self, "<br>".join(line for line in (text, detail) if line))
            return
        lines = ["<strong>Next episodes</strong>"]
        for show in upcoming[: self.config.menu.max_rows]:
            unwatched = f" · {show.unwatched} new" if show.unwatched else ""
            lines.append(
                f"{show.title} · Ep {show.next_episode} · {format_air_time(show.next_at, now)}"
                f" ({format_countdown(show.next_at, now)}){unwatched}"
            )
        set_tooltip(self, "<br>".join(lines))

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    # ------------------------------------------------------------------
    # Popup
    # ------------------------------------------------------------------

    def _toggle_card(self) -> None:
        m = self.config.menu
        popup = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        popup.setProperty("class", "anime-airing-menu")
        popup.setMinimumWidth(m.min_width)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._fill_popup(layout)
        fit_to_width(popup)
        popup.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        popup.show()
        if popup.isVisible():
            self._popup = popup
        else:
            # PopupWidget.show() found one already open and closed it instead.
            popup.deleteLater()
            self._forget_popup()

    def _forget_popup(self) -> None:
        self._popup = None
        self._popup_layout = None
        self._popup_key = None
        self._popup_hero = {}
        self._popup_rows = []
        self._popup_status = None

    def _sync_popup(self) -> None:
        if self._popup is None:
            return
        try:
            if not self._popup.isVisible():
                self._forget_popup()
                return
            self._refresh_popup()
        except RuntimeError:
            self._forget_popup()

    def _popup_state_key(self, upcoming: list[Show]) -> tuple:
        """What the popup's structure depends on; when it changes the popup is rebuilt."""
        shows = tuple(show.anilist_id for show in upcoming[: self.config.menu.max_rows])
        return (self._state(upcoming)[0], shows)

    def _fill_popup(self, layout: QVBoxLayout) -> None:
        while layout.count():
            old = layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        upcoming = self._upcoming()
        self._popup_layout = layout
        self._popup_key = self._popup_state_key(upcoming)
        self._popup_hero = {}
        self._popup_rows = []

        layout.addWidget(self._build_header())
        state, text = self._state(upcoming)
        if state:
            placeholder = _label(
                f"placeholder {state}", (self._service.error_text or text) if state == "error" else text
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder)
        else:
            layout.addWidget(self._build_hero(upcoming[0]))
            layout.addWidget(self._build_rows(upcoming[: self.config.menu.max_rows]))
        layout.addWidget(self._build_footer())
        self._refresh_popup()

    def _refresh_popup(self) -> None:
        if self._popup_layout is None:
            return
        upcoming = self._upcoming()
        if self._popup_state_key(upcoming) != self._popup_key:
            self._fill_popup(self._popup_layout)
            if self._popup is not None:
                fit_to_width(self._popup)
            return
        now = self._now()
        if self._popup_hero and upcoming:
            self._fill_hero(upcoming[0], now)
        for widgets, show in zip(self._popup_rows, upcoming, strict=False):
            self._fill_row(widgets, show, now, active=show is upcoming[0])
        self._fill_status()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        icon = _label("header-icon", self.config.icons.default)
        title = _label("title", "Next episodes")
        header_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch()
        if self.config.username:
            user = _label("username", self.config.username)
            header_layout.addWidget(user, alignment=Qt.AlignmentFlag.AlignVCenter)
        return header

    def _cover(self, show: Show, size: tuple[int, int], cls: str) -> QLabel | None:
        if not self.config.menu.show_covers:
            return None
        label = _label(cls)
        label.setFixedSize(*size)
        path = cover_path(show.anilist_id, show.cover_url) if show.cover_url else None
        if path is not None and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        size[0],
                        size[1],
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        return label

    def _build_hero(self, show: Show) -> QFrame:
        hero = _LinkFrame(show.url)
        hero.setProperty("class", "hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(0)
        cover = self._cover(show, _HERO_COVER, "hero-cover")
        if cover is not None:
            hero_layout.addWidget(cover, alignment=Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        title = _label("hero-title")
        title.setWordWrap(True)
        meta = _label("hero-meta")
        countdown = _label("hero-countdown")
        unwatched = _label("hero-unwatched")
        text.addWidget(title)
        text.addWidget(meta)
        text.addWidget(countdown)
        text.addWidget(unwatched)
        text.addStretch()
        hero_layout.addLayout(text, 1)

        self._popup_hero = {
            "frame": hero,
            "cover": cover,
            "title": title,
            "meta": meta,
            "countdown": countdown,
            "unwatched": unwatched,
        }
        return hero

    def _fill_hero(self, show: Show, now: datetime) -> None:
        hero = self._popup_hero
        soon = " soon" if (show.next_at - now).total_seconds() <= _SOON_SECONDS else ""
        hero["frame"].setProperty("class", f"hero{soon}")
        hero["frame"].url = show.url
        hero["title"].setText(show.title)
        hero["meta"].setText(f"Episode {show.next_episode} · {format_air_time(show.next_at, now)}")
        hero["countdown"].setText(format_countdown(show.next_at, now))
        hero["unwatched"].setText(self._unwatched_text(show))
        hero["unwatched"].setVisible(bool(show.unwatched))
        refresh_widget_style(*(w for w in hero.values() if w is not None))

    @staticmethod
    def _unwatched_text(show: Show) -> str:
        if not show.unwatched:
            return ""
        return "1 episode to catch up on" if show.unwatched == 1 else f"{show.unwatched} episodes to catch up on"

    def _build_rows(self, shows: list[Show]) -> QFrame:
        container = QFrame()
        container.setProperty("class", "rows-container")
        rows_layout = QVBoxLayout(container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        for show in shows:
            row = _LinkFrame(show.url)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)
            cover = self._cover(show, _ROW_COVER, "show-cover")
            if cover is not None:
                row_layout.addWidget(cover, alignment=Qt.AlignmentFlag.AlignVCenter)

            text = QVBoxLayout()
            text.setContentsMargins(0, 0, 0, 0)
            text.setSpacing(0)
            title = _label("show-title", kind=ElidedLabel)
            meta = _label("show-meta")
            text.addWidget(title)
            text.addWidget(meta)
            row_layout.addLayout(text, 1)

            right = QVBoxLayout()
            right.setContentsMargins(0, 0, 0, 0)
            right.setSpacing(0)
            countdown = _label("show-countdown")
            countdown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            unwatched = _label("show-unwatched")
            unwatched.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            right.addWidget(countdown)
            right.addWidget(unwatched)
            row_layout.addLayout(right)

            rows_layout.addWidget(row)
            self._popup_rows.append(
                {
                    "row": row,
                    "cover": cover,
                    "title": title,
                    "meta": meta,
                    "countdown": countdown,
                    "unwatched": unwatched,
                }
            )
        return container

    def _fill_row(self, widgets: dict[str, QWidget], show: Show, now: datetime, active: bool) -> None:
        classes = ["show-row"]
        if active:
            classes.append("active")
        if (show.next_at - now).total_seconds() <= _SOON_SECONDS:
            classes.append("soon")
        if show.unwatched:
            classes.append("unwatched")
        widgets["row"].setProperty("class", " ".join(classes))
        widgets["row"].url = show.url
        widgets["title"].setText(show.title)
        widgets["meta"].setText(f"Ep {show.next_episode} · {format_air_time(show.next_at, now)}")
        widgets["countdown"].setText(format_countdown(show.next_at, now))
        widgets["unwatched"].setText(f"{show.unwatched} new" if show.unwatched else "")
        widgets["unwatched"].setVisible(bool(show.unwatched))
        # Descendant rules such as `.show-row.active .show-title` only re-apply once the
        # children are repolished too, not just the row whose class changed.
        refresh_widget_style(*(w for w in widgets.values() if w is not None))

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setProperty("class", "footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        source = _label("source", "MyAnimeList · AniList")
        status = _label("status")
        status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer_layout.addWidget(source)
        footer_layout.addStretch()
        footer_layout.addWidget(status)
        self._popup_status = status
        return footer

    def _fill_status(self) -> None:
        if self._popup_status is None:
            return
        service = self._service
        snapshot = service.snapshot
        if snapshot is None:
            text, state = "", ""
        else:
            fetched = datetime.fromtimestamp(snapshot.fetched_at).astimezone()
            text = f"Updated {format_ago(fetched, self._now())}"
            state = ""
            if service.error_kind:
                text = f"{_ERROR_TEXT.get(service.error_kind, 'Unavailable')} · {text.lower()}"
                state = " stale"
        self._popup_status.setText(text)
        self._popup_status.setProperty("class", f"status{state}")
        refresh_widget_style(self._popup_status)

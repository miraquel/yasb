import logging
import re
import time
from datetime import UTC, datetime
from functools import partial
from typing import Any, override

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.utils.qobject import is_valid_qobject
from core.utils.stat_popup import GraphWidget
from core.utils.tooltip import set_tooltip
from core.utils.utilities import (
    PopupWidget,
    align_label_ink,
    align_label_text,
    build_progress_widget,
    refresh_widget_style,
)
from core.utils.widgets.ai_usage.hearts import heart_halves
from core.utils.widgets.ai_usage.scene import HeartsView, SkyScene
from core.utils.widgets.ai_usage.sky import apply_sky_settings
from core.utils.widgets.claude_usage.clawd import Frame
from core.utils.widgets.claude_usage.clawd_scene import ClawdScene
from core.validation.widgets.yasb.claude_usage import ClaudeUsageConfig
from core.widgets.base import BaseWidget
from core.widgets.services.ai_usage.weather import SkyWeatherService
from core.widgets.services.claude_usage.claude_api import ClaudeUsageService, read_account, read_plan
from core.widgets.services.claude_usage.sessions import (
    STATUS_IDLE,
    STATUS_WAITING,
    STATUS_WORKING,
    ClaudeSessionsService,
    count_sessions,
)
from core.widgets.services.claude_usage.status import STATUS_LEVELS, ClaudeStatusService
from core.widgets.services.claude_usage.token_history import TokenHistoryService, summarize

logger = logging.getLogger("claude_usage")

_TOKEN_PERIODS: list[tuple[str, str]] = [
    ("session", "Session"),
    ("today", "Today"),
    ("week", "Week"),
    ("month", "Month"),
    ("year", "Year"),
]
_EMPTY_TOKEN_SUMMARY: dict[str, Any] = {
    "totals": {},
    "series_by_period": {},
    "models_by_period": {},
    "session_id": None,
}
# {hearts} on the bar: nf-md-heart, nf-md-heart_half_full, nf-md-heart_outline.
_HEART_GLYPHS = ("\U000f02d1", "\U000f06df", "\U000f02d5")
_LEVELS = ("low", "medium", "high", "unknown")
_SESSION_STATES = (STATUS_WORKING, STATUS_WAITING, STATUS_IDLE)


class UsageBar(QFrame):
    """A rounded progress bar drawn as a track QFrame with a child `.fill` QFrame.

    Keeps the fill at least as wide as it is tall so the rounded corners are preserved at
    low values (the QProgressBar::chunk square-fill issue), and stays fully CSS-styleable.
    """

    # Must match the stylesheet min/max-height for this bar.
    TRACK_HEIGHT = 6

    def __init__(self, value: int, level: str, accent: str = "", parent: QFrame | None = None):
        super().__init__(parent)
        self._value = max(0, min(100, value))
        self.setProperty("class", " ".join(c for c in ("progress", level, accent) if c))
        self._fill = QFrame(self)
        self._fill.setProperty("class", "fill")

    def set_value(self, value: int, level: str) -> None:
        """Update the value and level class in place, so a refresh can reuse the bar
        instead of rebuilding it (rebuilding the section is what causes the menu flicker)."""
        self._value = max(0, min(100, value))
        self.setProperty("class", f"progress {level}")
        refresh_widget_style(self)
        self._update_fill()

    def _track_height(self) -> int:
        """Height of the painted track.

        The stylesheet engine paints this frame's background at its styled height and
        centres it, but sets no Qt geometry - minimumHeight() stays 0 - so the widget keeps
        whatever height the layout gave it (routinely ~40px). Filling that drew the value as
        a slab standing proud of the track, so the height is pinned here instead.
        TRACK_HEIGHT must match the stylesheet's min/max-height for this bar.
        """
        return min(self.TRACK_HEIGHT, self.height()) if self.height() > 0 else self.TRACK_HEIGHT

    def _update_fill(self) -> None:
        height = self._track_height()
        fill_width = int(self.width() * self._value / 100)
        if fill_width > 0:
            fill_width = max(fill_width, height)
        # Centred to match the track behind it; the +1 rounds the half-pixel the same
        # way the stylesheet engine does, otherwise the fill sits 2px high.
        self._fill.setGeometry(0, max(0, (self.height() - height + 1) // 2), fill_width, height)

    @override
    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._update_fill()


class ClaudeUsageWidget(BaseWidget):
    validation_schema = ClaudeUsageConfig

    # Shown via {stale} when Claude Code's OAuth token has expired (nf-fa-warning).
    STALE_ICON = ""

    def __init__(self, config: ClaudeUsageConfig):
        super().__init__(class_name="claude-usage")
        self.config = config
        self._show_alt_label = False
        self._usage_mode = self.config.usage_mode
        self._menu: PopupWidget | None = None
        self._usage_frames: list[QFrame] = []
        # Per-window references to the live bar/labels, so a data refresh updates them in place.
        self._section_widgets: dict[str, dict[str, Any]] = {}
        self._service_released = False

        self._service = ClaudeUsageService.get_instance(self.config.update_interval, self.config.cache_ttl)
        self._data: dict[str, Any] = self._service.latest()
        # Static until the user re-logs in, so read once here and again on a manual refresh
        # rather than re-parsing a ~95 KB json on every poll.
        self._account: dict[str, str] = read_account() if self.config.show_account else {}

        # Local token-history (optional): scans Claude Code's session transcripts off-thread.
        self._token_service: TokenHistoryService | None = None
        self._token_summary: dict[str, Any] = dict(_EMPTY_TOKEN_SUMMARY)
        self._selected_period = self.config.token_history.default_period
        self._period_buttons: dict[str, QPushButton] = {}
        self._token_total_label: QLabel | None = None
        self._token_graph: GraphWidget | None = None
        self._model_container: QFrame | None = None
        self._model_layout: QGridLayout | None = None
        if self.config.token_history.enabled:
            self._token_service = TokenHistoryService.get_instance(self.config.token_history.scan_interval)
            self._token_summary = self._summarize_tokens(self._token_service.latest())

        # Claude API status (optional): polls the public status page off-thread.
        self._status_service: ClaudeStatusService | None = None
        self._status: dict[str, Any] = {"indicator": "unknown", "description": ""}
        self._status_dot: QLabel | None = None
        self._status_text_label: QLabel | None = None
        if self.config.status.enabled:
            self._status_service = ClaudeStatusService.get_instance(self.config.status.poll_interval)
            self._status = self._status_service.latest()

        # Live Claude Code sessions (optional): Clawd's moods come from these, so he polls them
        # even when the sessions list itself is turned off.
        self._sessions_service: ClaudeSessionsService | None = None
        self._sessions: list[dict[str, Any]] = []
        self._session_summary: QLabel | None = None
        self._session_rows: QFrame | None = None
        self._session_layout: QGridLayout | None = None
        if self.config.sessions.enabled or self.config.clawd.enabled:
            self._sessions_service = ClaudeSessionsService.get_instance(
                self.config.sessions.poll_interval, self.config.sessions.dirs
            )
            self._sessions = self._sessions_service.latest()

        # Weather for the sky (optional): fetched only for configured coordinates, never guessed.
        sky = self.config.sky
        self._weather_service: SkyWeatherService | None = None
        self._weather: dict[str, Any] = {}
        if sky.enabled and sky.weather and sky.latitude is not None and sky.longitude is not None:
            self._weather_service = SkyWeatherService.get_instance(sky.latitude, sky.longitude, sky.weather_interval)
            self._weather = self._weather_service.latest()

        # Built with the popup; None until it first opens.
        self._clawd: ClawdScene | None = None
        self._sky: SkyScene | None = None
        self._hearts: HeartsView | None = None
        self._meta_account: QLabel | None = None
        self._meta_updated: QLabel | None = None
        self._plan = read_plan() if self.config.footer.enabled and self.config.footer.show_plan else ""

        self.progress_widget = build_progress_widget(self, self.config.progress_bar.model_dump())
        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)
        if self.progress_widget:
            position = 0 if self.config.progress_bar.position == "left" else self._widget_container_layout.count()
            self._widget_container_layout.insertWidget(position, self.progress_widget)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_menu", self._toggle_menu)
        self.register_callback("refresh", self._refresh)
        self.register_callback("toggle_usage_mode", self._toggle_usage_mode)

        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right

        self._service.data_ready.connect(self._on_data)
        if self._token_service is not None:
            self._token_service.data_ready.connect(self._on_token_data)
        if self._status_service is not None:
            self._status_service.data_ready.connect(self._on_status_data)
        if self._sessions_service is not None:
            self._sessions_service.data_ready.connect(self._on_sessions_data)
        if self._weather_service is not None:
            self._weather_service.data_ready.connect(self._on_weather_data)
        self.destroyed.connect(lambda *_: self._release_service())
        self._update_label()

    def _release_service(self) -> None:
        if getattr(self, "_service_released", False):
            return
        self._service_released = True
        try:
            self._service.release()
        except RuntimeError:
            pass
        if self._token_service is not None:
            try:
                self._token_service.release()
            except RuntimeError:
                pass
        if self._status_service is not None:
            try:
                self._status_service.release()
            except RuntimeError:
                pass
        if self._sessions_service is not None:
            try:
                self._sessions_service.release()
            except RuntimeError:
                pass
        if self._weather_service is not None:
            try:
                self._weather_service.release()
            except RuntimeError:
                pass

    @override
    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self._release_service()
        super().closeEvent(a0)

    def _on_data(self, data: dict[str, Any]) -> None:
        self._data = data
        self._update_label()
        self._sync_usage_sections()
        self._feed_clawd()
        self._sync_meta()

    def _refresh(self) -> None:
        if self.config.show_account:
            self._account = read_account()
        if self.config.footer.enabled and self.config.footer.show_plan:
            self._plan = read_plan()
        self._service.refresh_now()
        if self._status_service is not None:
            self._status_service.refresh_now()
        if self._sessions_service is not None:
            self._sessions_service.refresh_now()

    def _on_sessions_data(self, sessions: list[dict[str, Any]]) -> None:
        self._sessions = sessions
        self._update_label()
        self._feed_clawd()
        self._sync_sessions_section()

    @staticmethod
    def _epoch(iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _feed_clawd(self) -> None:
        """Hand Clawd and the hearts the latest sessions and 5-hour reading."""
        percent = self._data.get("five")
        if self._hearts is not None:
            try:
                self._hearts.set_state(heart_halves(percent), percent=percent)
            except RuntimeError:
                self._hearts = None
        if self._clawd is not None:
            counts = count_sessions(self._sessions)
            try:
                self._clawd.set_inputs(
                    percent,
                    counts[STATUS_WORKING],
                    counts[STATUS_WAITING],
                    counts["total"],
                    self._epoch(self._data.get("five_reset_iso")),
                )
            except RuntimeError:
                self._clawd = None

    def _on_weather_data(self, data: dict[str, Any]) -> None:
        self._weather = data
        self._feed_sky()

    def _clock_minutes(self, minutes: float) -> str:
        m = round(minutes) % 1440
        return self._clock(datetime(2000, 1, 1, m // 60, m % 60))

    def _feed_sky(self) -> None:
        """Hand the sky its location, the latest weather and any preview, and word its tooltip."""
        if self._sky is None:
            return
        model = self._sky.model
        apply_sky_settings(model, self.config.sky, self._weather)
        tip = "\n".join(model.describe(datetime.now().astimezone(), self._clock_minutes))
        try:
            # Clawd covers most of the sky, so his tooltip carries it; without him the sky has its own.
            if self._clawd is not None:
                self._clawd.set_tip_extra(tip)
            else:
                self._sky.set_tip(tip)
        except RuntimeError:
            self._sky = None

    def _on_clawd_step(self, frame: Frame) -> None:
        # While Clawd animates, the hearts follow his frame: the lost half blinks, and they
        # beat when nearly out.
        if self._hearts is not None:
            self._hearts.set_state(frame.hearts, frame.heart_beat, self._data.get("five"))

    def _summarize_tokens(self, agg: dict[str, Any]) -> dict[str, Any]:
        th = self.config.token_history
        return summarize(agg, count_cache_read=th.count_cache_read, week_starts_on=th.week_starts_on)

    def _on_token_data(self, agg: dict[str, Any]) -> None:
        self._token_summary = self._summarize_tokens(agg)
        self._update_label()
        self._sync_token_section()

    def _on_status_data(self, data: dict[str, Any]) -> None:
        self._status = data
        self._update_label()
        self._sync_status()

    def _status_level(self) -> str:
        level = self._status.get("indicator")
        return level if level in STATUS_LEVELS else "unknown"

    def _build_status_row(self) -> QFrame:
        row = QFrame()
        row.setProperty("class", "status-row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        self._status_dot = QLabel(self.config.status.icon)
        self._status_dot.setProperty("class", "dot")
        row_layout.addWidget(self._status_dot)
        self._status_text_label = QLabel("")
        self._status_text_label.setProperty("class", "status-text")
        row_layout.addWidget(self._status_text_label)
        row_layout.addStretch()
        self._sync_status()
        return row

    def _sync_status(self) -> None:
        """Update the menu status dot colour and description in place."""
        if self._status_dot is None or self._status_text_label is None:
            return
        try:
            self._status_dot.setProperty("class", f"dot {self._status_level()}")
            self._status_text_label.setText(self._status.get("description", "") or "Claude status unknown")
            refresh_widget_style(self._status_dot, self._status_text_label)
        except RuntimeError:
            self._status_dot = None
            self._status_text_label = None

    @staticmethod
    def _fmt_tokens(value: Any) -> str:
        """Compact token count, e.g. '15K', '1.2M', '218M', '3.4B', '1T'; '--' when unknown."""
        if not isinstance(value, (int, float)):
            return "--"
        n = int(value)
        if n < 1000:
            return str(n)
        units = ("K", "M", "B", "T")
        magnitude = 0
        scaled = n / 1000.0
        # Rounding can lift a value to 1000 of its unit (999_999 -> "1000K"); carry it up instead.
        while round(scaled, 1) >= 1000 and magnitude < len(units) - 1:
            scaled /= 1000.0
            magnitude += 1
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + units[magnitude]

    def _format_values(self) -> dict[str, str]:
        totals = self._token_summary.get("totals", {})
        return {
            "five_hour": self._pct(self._data.get("five")),
            "seven_day": self._pct(self._data.get("seven")),
            # Explicit pair, unaffected by usage_mode.
            "five_hour_used": self._pct(self._data.get("five")),
            "seven_day_used": self._pct(self._data.get("seven")),
            "five_hour_remaining": self._pct_remaining(self._data.get("five")),
            "seven_day_remaining": self._pct_remaining(self._data.get("seven")),
            # Mode-aware pair, flipped by the toggle_usage_mode callback.
            "five_hour_value": self._mode_value(self._data.get("five")),
            "seven_day_value": self._mode_value(self._data.get("seven")),
            "mode": (
                self.config.mode_label_remaining if self._usage_mode == "remaining" else self.config.mode_label_used
            ),
            "five_hour_reset": self._fmt_reset(self._data.get("five_reset_iso")),
            "seven_day_reset": self._fmt_reset(self._data.get("seven_reset_iso")),
            "stale": self.STALE_ICON if self._data.get("token_expired") else "",
            "session_tokens": self._fmt_tokens(totals.get("session")),
            "today_tokens": self._fmt_tokens(totals.get("today")),
            "week_tokens": self._fmt_tokens(totals.get("week")),
            "month_tokens": self._fmt_tokens(totals.get("month")),
            "year_tokens": self._fmt_tokens(totals.get("year")),
            "status": self.config.status.icon if self.config.status.enabled else "",
            "status_text": self._status.get("description", "") if self.config.status.enabled else "",
            "hearts": self._hearts_text(),
            **self._session_values(),
        }

    def _hearts_text(self) -> str:
        """The 5-hour hearts as Nerd Font glyphs, e.g. full-full-half; empty with no reading."""
        halves = heart_halves(self._data.get("five"))
        if halves is None:
            return ""
        full, half, empty = _HEART_GLYPHS
        return "".join(full if halves - 2 * i >= 2 else half if halves - 2 * i == 1 else empty for i in range(3))

    def _session_values(self) -> dict[str, str]:
        counts = count_sessions(self._sessions)
        sc = self.config.sessions
        badge = []
        if counts[STATUS_WORKING]:
            badge.append(f"{sc.working_icon}{counts[STATUS_WORKING]}")
        if counts[STATUS_WAITING]:
            badge.append(f"{sc.waiting_icon}{counts[STATUS_WAITING]}")
        return {
            "sessions_total": str(counts["total"]),
            "sessions_working": str(counts[STATUS_WORKING]),
            "sessions_waiting": str(counts[STATUS_WAITING]),
            "sessions_idle": str(counts[STATUS_IDLE]),
            # Only what needs attention, so it renders empty (and hides) when all is quiet.
            "sessions_badge": " ".join(badge),
        }

    def _session_state(self) -> str:
        """The most pressing session state, for the label's state class."""
        counts = count_sessions(self._sessions)
        if counts[STATUS_WAITING]:
            return STATUS_WAITING
        if counts[STATUS_WORKING]:
            return STATUS_WORKING
        return STATUS_IDLE

    def _sessions_summary_text(self) -> str:
        counts = count_sessions(self._sessions)
        if not counts["total"]:
            return "None running"
        parts = [f"{counts['total']} open"]
        if counts[STATUS_WORKING]:
            parts.append(f"{counts[STATUS_WORKING]} working")
        if counts[STATUS_WAITING]:
            parts.append(f"{counts[STATUS_WAITING]} waiting")
        return " · ".join(parts)

    @staticmethod
    def _pretty_model(model_id: str) -> str:
        """Display name derived from the id so new models need no upkeep: the name is the first
        word after the 'claude-' prefix and the version is the first two short (<=2 digit) groups
        (date stamps and a bracketed suffix are dropped). A '[fast]' tag, added when the request
        ran in fast mode, renders as a trailing 'Fast'. Non-Claude ids are returned unchanged."""
        lowered = model_id.lower()
        if not lowered.startswith("claude-"):
            return model_id
        is_fast = "[fast]" in lowered
        parts = lowered.split("[", 1)[0].removeprefix("claude-").split("-")
        name = next((p for p in parts if p.isalpha()), None)
        if name is None:
            return model_id
        nums = [p for p in parts if p.isdigit() and len(p) <= 2]
        label = f"{name.capitalize()} {'.'.join(nums[:2])}".rstrip()
        return f"{label} Fast" if is_fast else label

    @staticmethod
    def _pct(value: Any) -> str:
        return "--" if value is None else str(value)

    @staticmethod
    def _pct_remaining(value: Any) -> str:
        """The share of a window still available, i.e. the complement of utilization.

        Clamped at zero: the endpoint can report over 100% utilization, and "-4 left"
        would be worse than useless on the bar.
        """
        if not isinstance(value, (int, float)):
            return "--"
        return str(max(0, 100 - round(value)))

    def _mode_value(self, value: Any) -> str:
        return self._pct_remaining(value) if self._usage_mode == "remaining" else self._pct(value)

    def _toggle_usage_mode(self) -> None:
        """Flip the bar between 'consumed so far' and 'still available'."""
        self._usage_mode = "used" if self._usage_mode == "remaining" else "remaining"
        self._update_label()

    @staticmethod
    def _pct_decimal(raw: Any, rounded: Any) -> str:
        """One-decimal percentage ('28.0') from the raw value, falling back to the rounded one."""
        value = raw if isinstance(raw, (int, float)) else rounded
        return f"{value:.1f}" if isinstance(value, (int, float)) else "--"

    def _clock(self, local: datetime) -> str:
        """Local time of day in the configured clock style ('6:00 AM' or '18:00')."""
        if self.config.time_format == "24h":
            return f"{local.hour:02d}:{local.minute:02d}"
        hour12 = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        return f"{hour12}:{local.minute:02d} {ampm}"

    def _fmt_reset(self, iso: str | None) -> str:
        """Short time-until-reset: a countdown ('4h 14m') when under a day away,
        otherwise a local weekday + time ('Sat 6:00 AM')."""
        if not iso:
            return "--"
        try:
            target = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            seconds = int((target - datetime.now(UTC)).total_seconds())
            if seconds <= 0:
                return "0m"
            if seconds < 24 * 3600:
                hours, minutes = divmod(seconds // 60, 60)
                return f"{hours}h {minutes}m" if hours else f"{minutes}m"
            local = target.astimezone()
            return f"{local:%a} {self._clock(local)}"
        except Exception:
            return "--"

    @staticmethod
    def _fmt_duration(iso: str | None) -> str:
        """Relative time-until-reset, e.g. '6d 21h', '4h 14m', '10m'; '--' when unknown."""
        if not iso:
            return "--"
        try:
            target = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            seconds = int((target - datetime.now(UTC)).total_seconds())
            if seconds <= 0:
                return "0m"
            minutes = seconds // 60
            days, rem = divmod(minutes, 1440)
            hours, mins = divmod(rem, 60)
            if days:
                return f"{days}d {hours}h"
            if hours:
                return f"{hours}h {mins}m"
            return f"{mins}m"
        except Exception:
            return "--"

    def _fmt_weekday(self, iso: str | None, with_date: bool = False) -> str:
        """Absolute reset as a local weekday + time, e.g. 'Sat @ 6:00 AM'; '--' when unknown.

        With ``with_date`` the month/day is included ('Sat, Jun 13 @ 6:00 AM') so two windows
        resetting on the same weekday stay distinguishable.
        """
        if not iso:
            return "--"
        try:
            local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
            day = f"{local:%a, %b} {local.day}" if with_date else f"{local:%a}"
            return f"{day} @ {self._clock(local)}"
        except Exception:
            return "--"

    def _reset_phrase(self, iso: str | None, reset_format: str) -> str:
        """Reset line for the popup footer, phrased per the window's reset_format.

        An absolute line says when the window lands but not how far off it is, so the
        countdown is appended: every window then answers both questions, however it is
        phrased. A relative line already is the countdown, so nothing is added.
        """
        if reset_format == "absolute":
            value = self._fmt_weekday(iso, with_date=self.config.reset_show_date)
            if value == "--":
                return "Reset time unknown"
            phrase = f"Resets on {value}"
            duration = self._fmt_duration(iso)
            if self.config.show_reset_duration and duration != "--":
                phrase += f" · in {duration}"
            return phrase
        value = self._fmt_duration(iso)
        return f"Resets in {value}" if value != "--" else "Reset time unknown"

    def _fmt_reset_at(self, iso: str | None) -> str:
        """Absolute local reset timestamp, rendered with ``reset_datetime_format``.

        A bad strftime template falls back to the built-in layout rather than blanking the
        line, so a typo in the config never silently loses the timestamp.
        """
        if not iso:
            return "--"
        try:
            local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        except Exception:
            return "--"
        try:
            return local.strftime(self.config.reset_datetime_format)
        except Exception:
            logger.debug("invalid reset_datetime_format: %r", self.config.reset_datetime_format)
            return f"{local.month}/{local.day}/{local.year}, {self._clock(local)}"

    def _build_header_icon(self) -> QLabel | None:
        """The product mark at the left of the header, when a path is configured.

        Rendered as rich text rather than a QPixmap so the same <img> the bar label accepts
        works here, and a missing file degrades to an empty label instead of raising.
        """
        path = (self.config.menu.icon or "").strip()
        if not path:
            return None
        label = QLabel(f"<img src='{path}' width='22' height='22'>")
        label.setProperty("class", "app-icon")
        return label

    def _account_line(self) -> str:
        """Who these numbers belong to: the email, which is the unambiguous identifier.

        Empty when signed out or when show_account is off, so the caller omits the line
        entirely rather than rendering a placeholder.
        """
        if not self.config.show_account:
            return ""
        return self._account.get("email") or self._account.get("name") or ""

    def _account_tooltip(self) -> str:
        """Fuller account detail on hover, where there is room for the name and org."""
        parts = [p for p in (self._account.get("name"), self._account.get("email")) if p]
        organization = self._account.get("organization")
        if organization:
            parts.append(organization)
        return "\n".join(parts)

    def _apply_date(self, label: QLabel, reset_iso: str | None) -> None:
        """Set the absolute reset timestamp, hiding the line entirely when it is unknown.

        A visible '--' row is worse than no row: it reads as broken and leaves an orphan
        line of dead space under a window whose reset time the endpoint has not reported yet.
        """
        text = self._fmt_reset_at(reset_iso)
        label.setText("" if text == "--" else text)
        label.setVisible(text != "--")

    def _level_class(self, value: Any) -> str:
        """Traffic light for a utilization: low below warn_percent, high from crit_percent."""
        if not isinstance(value, (int, float)):
            return "unknown"
        if value >= self.config.crit_percent:
            return "high"
        if value >= self.config.warn_percent:
            return "medium"
        return "low"

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    def _update_label(self) -> None:
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_template = self.config.label_alt if self._show_alt_label else self.config.label
        values = self._format_values()
        # Skip whitespace-only parts so the widget/template indices stay aligned with
        # build_widget_label (which drops them); otherwise multi-<span> labels misalign.
        label_parts = [part for part in re.split(r"(<span.*?>.*?</span>)", active_template) if part.strip()]

        for index, part in enumerate(label_parts):
            if index >= len(active_widgets):
                continue
            current_widget = active_widgets[index]
            if "<span" in part and "</span>" in part:
                text = re.sub(r"<span.*?>|</span>", "", part).strip()
            else:
                text = part.strip()
            try:
                rendered = text.format(**values)
            except Exception:
                rendered = text
            current_widget.setText(rendered)
            # Hide the label when its placeholder renders empty (e.g. {stale} on a valid
            # token) so it does not leave a constant gap from its own margin/spacing.
            current_widget.setVisible(bool(rendered))
            if "{status}" in part:
                base = current_widget.property("class") or "status"
                base = " ".join(t for t in base.split() if t not in STATUS_LEVELS)
                current_widget.setProperty("class", f"{base} {self._status_level()}")
            if "{sessions_" in part:
                # .working / .waiting on the badge's own label, so waiting can stand out.
                base = current_widget.property("class") or "sessions"
                base = " ".join(t for t in base.split() if t not in _SESSION_STATES)
                current_widget.setProperty("class", f"{base} {self._session_state()}")
            if "{five_hour" in part or "{hearts}" in part:
                # .low / .medium / .high from the same thresholds as the popup bars.
                base = current_widget.property("class") or "label"
                base = " ".join(t for t in base.split() if t not in _LEVELS)
                current_widget.setProperty("class", f"{base} {self._level_class(self._data.get('five'))}")
            if self.config.tooltip:
                # Spell out both sides here regardless of usage_mode, so the hover always
                # answers the question the bar's single number cannot.
                tip = (
                    f"Claude - 5h: {values['five_hour']}% used / {values['five_hour_remaining']}% left"
                    f" · 7d: {values['seven_day']}% used / {values['seven_day_remaining']}% left"
                )
                if self._sessions_service is not None:
                    tip += f"\nSessions: {self._sessions_summary_text().lower()}"
                account = self._account_line()
                if account:
                    tip += f"\n{account}"
                if self._data.get("token_expired"):
                    tip += "\nToken expired - run `claude -p` to refresh"
                set_tooltip(current_widget, tip)
        refresh_widget_style(*active_widgets)
        self._sync_progress_bar()

    def _sync_progress_bar(self) -> None:
        """Drive the optional bar-level progress ring from the window the label is showing.

        This is utilization, so the ring fills up as the window is consumed - the opposite
        of the Codex widget, which reports remaining.
        """
        if not self.progress_widget:
            return
        value = self._data.get("seven" if self._show_alt_label else "five")
        self.progress_widget.setVisible(value is not None)
        level_colors = self.config.progress_bar.level_colors
        if level_colors is not None and isinstance(value, (int, float)):
            # The level comes from consumption whichever way the ring runs, so red always
            # means close to the limit.
            self.progress_widget.set_color(getattr(level_colors, self._level_class(value)))
        if isinstance(value, (int, float)):
            # Follow usage_mode so the ring never contradicts the number beside it:
            # filling up as the window is consumed, or draining as it runs out.
            filled = max(0.0, 100.0 - float(value)) if self._usage_mode == "remaining" else float(value)
            self.progress_widget.set_value(filled)

    def _toggle_menu(self) -> None:
        if is_valid_qobject(self._menu) and self._menu.isVisible():
            self._menu.hide_animated()
            return
        self._show_menu()

    def _show_menu(self) -> None:
        """Build the popup once and reuse it on every open, same as `control_center`'s popup.

        ``persistent=True`` keeps ``PopupWidget`` from tearing it down on hide, so reopening
        never redoes the widget-tree construction and layout pass.
        """
        menu = self._menu if is_valid_qobject(self._menu) else self._build_menu()
        # Before show(): Clawd picks his entrance when he first appears, from these inputs.
        self._feed_clawd()
        self._feed_sky()
        menu.setPosition(
            alignment=self.config.menu.alignment,
            direction=self.config.menu.direction,
            offset_left=self.config.menu.offset_left,
            offset_top=self.config.menu.offset_top,
        )
        menu.show()
        # The popup ignores refreshes while hidden (see the sync methods' isVisible() guard), so
        # push the latest data in now rather than showing whatever was true when it last closed.
        self._sync_usage_sections()
        self._sync_token_section()
        self._sync_status()
        self._sync_sessions_section()
        self._sync_meta()

    def _build_sessions_section(self) -> QFrame:
        """Sessions section: what Claude Code is doing right now, one row per open session."""
        frame = QFrame()
        frame.setProperty("class", "section sessions")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_row = QFrame()
        title_row.setProperty("class", "title-row")
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_label = QLabel("Sessions")
        title_label.setProperty("class", "title")
        title_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_layout.addStretch()
        self._session_summary = QLabel("")
        self._session_summary.setProperty("class", "summary")
        self._session_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(self._session_summary)
        layout.addWidget(title_row)

        self._session_rows = QFrame()
        self._session_rows.setProperty("class", "session-rows")
        self._session_layout = QGridLayout(self._session_rows)
        self._session_layout.setContentsMargins(0, 0, 0, 0)
        self._session_layout.setHorizontalSpacing(8)
        self._session_layout.setVerticalSpacing(4)
        self._session_layout.setColumnStretch(1, 1)
        layout.addWidget(self._session_rows)

        self._sync_sessions_section()
        return frame

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    def _session_detail(self, session: dict[str, Any]) -> str:
        if session["status"] == STATUS_WORKING:
            return "working"
        if session["status"] == STATUS_WAITING:
            return f"needs you · {session['waiting_for']}" if session["waiting_for"] else "needs you"
        return "idle"

    def _sync_sessions_section(self) -> None:
        """Rebuild the session rows and refit the popup's height to them."""
        if self._session_layout is None:
            return
        sc = self.config.sessions
        icons = {STATUS_WORKING: sc.working_icon, STATUS_WAITING: sc.waiting_icon, STATUS_IDLE: sc.idle_icon}
        try:
            self._session_summary.setText(self._sessions_summary_text())
            while self._session_layout.count():
                item = self._session_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    # Detached now (not just deleteLater) so the size hint below is current.
                    widget.setParent(None)
                    widget.deleteLater()
            # Waiting first: those are the rows that want something from you.
            order = {STATUS_WAITING: 0, STATUS_WORKING: 1, STATUS_IDLE: 2}
            sessions = sorted(self._sessions, key=lambda s: order[s["status"]])
            shown = sessions[: sc.max_rows]
            for row, session in enumerate(shown):
                marker = QLabel(icons[session["status"]])
                marker.setProperty("class", f"marker {session['status']}")
                name = QLabel(self._clip(session["name"], 30))
                name.setProperty("class", "name")
                detail = QLabel(self._clip(self._session_detail(session), 24))
                detail.setProperty("class", f"detail {session['status']}")
                detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                folder = session["cwd"] or session["name"]
                for widget in (marker, name, detail):
                    set_tooltip(widget, f"{session['name']}\n{folder}")
                self._session_layout.addWidget(marker, row, 0)
                self._session_layout.addWidget(name, row, 1)
                self._session_layout.addWidget(detail, row, 2)
            if len(sessions) > len(shown) and sc.max_rows:
                more = QLabel(f"+{len(sessions) - len(shown)} more")
                more.setProperty("class", "more")
                self._session_layout.addWidget(more, len(shown), 1, 1, 2)
            self._session_rows.setVisible(bool(shown))
            align_label_text(self._session_rows)
            if self._menu is not None and self._menu.isVisible():
                # Same refit as the token section: recompute now, then resize the height only.
                self._menu_layout.activate()
                self._menu.resize(self._menu.width(), self._menu.sizeHint().height())
        except RuntimeError:
            self._session_summary = None
            self._session_rows = None
            self._session_layout = None

    def _stale_after(self) -> int:
        configured = self.config.footer.stale_after
        if configured:
            return configured
        # Serving from cache is normal for up to cache_ttl, so stale starts past that.
        return max(3 * self.config.update_interval, self.config.cache_ttl + 2 * self.config.update_interval)

    def _build_meta_line(self) -> QFrame:
        """Closing line: whose plan these numbers are, and how fresh they are."""
        frame = QFrame()
        frame.setProperty("class", "meta")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._meta_account = QLabel("")
        self._meta_account.setProperty("class", "account")
        set_tooltip(self._meta_account, self._account_tooltip())
        layout.addWidget(self._meta_account)
        layout.addStretch()
        self._meta_updated = QLabel("")
        self._meta_updated.setProperty("class", "updated")
        self._meta_updated.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._meta_updated)
        self._sync_meta()
        return frame

    def _sync_meta(self) -> None:
        if self._meta_account is None:
            return
        try:
            email = self._account_line()
            signed_out = self.config.show_account and not email
            if signed_out:
                account_text = " · ".join(p for p in (self._plan, "not signed in") if p)
            else:
                account_text = " · ".join(p for p in (self._plan, email) if p)
            self._meta_account.setText(self._clip(account_text, 40))
            self._meta_account.setProperty("class", "account signed-out" if signed_out else "account")

            fetched_at = int(self._data.get("fetched_at") or 0)
            if not fetched_at:
                updated, stale = "no data yet", True
            else:
                stamp = self._clock(datetime.fromtimestamp(fetched_at).astimezone())
                stale = time.time() - fetched_at > self._stale_after()
                updated = f"stale · {stamp}" if stale else f"updated {stamp}"
            self._meta_updated.setText(updated)
            self._meta_updated.setProperty("class", "updated stale" if stale else "updated")
            refresh_widget_style(self._meta_account, self._meta_updated)
        except RuntimeError:
            self._meta_account = None
            self._meta_updated = None

    def _build_token_section(self) -> QFrame:
        """Tokens section: a Session/Today/Week/Month/Year toggle, the selected total,
        and an optional usage graph for the selected period."""
        th = self.config.token_history
        frame = QFrame()
        frame.setProperty("class", "section tokens")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_label = QLabel("Tokens")
        title_label.setProperty("class", "title")
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)

        toggle = QFrame()
        toggle.setProperty("class", "period-toggle")
        toggle_layout = QHBoxLayout(toggle)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)
        self._period_buttons = {}
        for key, text in _TOKEN_PERIODS:
            btn = QPushButton(text)
            btn.setProperty("class", "period-btn")
            btn.clicked.connect(partial(self._select_period, key))
            toggle_layout.addWidget(btn)
            self._period_buttons[key] = btn
        layout.addWidget(toggle)

        self._token_total_label = QLabel("--")
        self._token_total_label.setProperty("class", "token-total")
        layout.addWidget(self._token_total_label)

        if th.show_graph:
            graph_container = QFrame()
            graph_container.setProperty("class", "graph-container")
            graph_layout = QVBoxLayout(graph_container)
            graph_layout.setContentsMargins(0, 0, 0, 0)
            graph_layout.setSpacing(0)
            self._token_graph = GraphWidget("token-graph", show_grid=th.show_graph_grid)
            graph_layout.addWidget(self._token_graph)
            layout.addWidget(graph_container)
        else:
            self._token_graph = None

        # Last in the section: these rows break down the total and graph above them, so they
        # read as a detail of it. Placed before the title they floated above the section's own
        # label, belonging to nothing.
        if th.show_models:
            self._model_container = QFrame()
            self._model_container.setProperty("class", "model-usage")
            container_layout = QVBoxLayout(self._model_container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            rows = QFrame()
            rows.setProperty("class", "model-rows")
            self._model_layout = QGridLayout(rows)
            self._model_layout.setContentsMargins(0, 0, 0, 0)
            self._model_layout.setHorizontalSpacing(8)
            self._model_layout.setVerticalSpacing(4)
            self._model_layout.setColumnStretch(1, 1)
            container_layout.addWidget(rows)
            layout.addWidget(self._model_container)
        else:
            self._model_container = None
            self._model_layout = None

        self._sync_token_section()
        return frame

    def _select_period(self, period: str, checked: bool = False) -> None:
        self._selected_period = period
        self._sync_token_section()

    def _sync_token_section(self) -> None:
        """Refresh the token total, active toggle button, and graph in place."""
        if self._token_total_label is None:
            return
        totals = self._token_summary.get("totals", {})
        try:
            self._token_total_label.setText(self._fmt_tokens(totals.get(self._selected_period)))
            for key, btn in self._period_buttons.items():
                active = key == self._selected_period
                btn.setProperty("class", "period-btn active" if active else "period-btn")
                refresh_widget_style(btn)
            if self._token_graph is not None:
                series = self._token_summary.get("series_by_period", {}).get(self._selected_period, [])
                peak = max(series) if series else 0
                normalized = [(v / peak * 100.0) if peak else 0.0 for v in series]
                if len(normalized) == 1:
                    # Duplicate a lone sample so the graph draws a flat line rather than nothing.
                    normalized.append(normalized[0])
                self._token_graph.set_data(normalized)
            self._sync_model_rows()
            if self._menu is not None and self._menu.isVisible():
                # activate() forces the layout to recompute now; without it, sizeHint() below
                # still reflects the pre-switch row count (Qt only invalidates the cached hint
                # lazily), so shrinking to a period with fewer models left a gap under the graph.
                self._menu_layout.activate()
                # Width is locked, so refit only the height to the new model-row count: no gap under
                # the graph on shorter periods, no cramming on taller ones.
                self._menu.resize(self._menu.width(), self._menu.sizeHint().height())
        except RuntimeError:
            # Popup (and its labels) was destroyed; references are stale until reopened.
            self._token_total_label = None
            self._token_graph = None
            self._period_buttons = {}

    def _sync_model_rows(self) -> None:
        """Rebuild the per-model bars for the selected period; hide the container when empty."""
        if self._model_layout is None or self._model_container is None:
            return
        try:
            while self._model_layout.count():
                item = self._model_layout.takeAt(0)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    # Detach now (not just deleteLater) so the popup's size hint reflects the new
                    # row count synchronously, letting the caller resize the popup correctly.
                    widget.setParent(None)
                    widget.deleteLater()
            models = self._token_summary.get("models_by_period", {}).get(self._selected_period, [])[:5]
            self._model_container.setVisible(bool(models))
            peak = models[0][1] if models else 0
            # A grid keeps the name and total columns the same width across rows (sized to their
            # widest cell at layout time), so the bar column lines up without measuring fonts.
            for index, (model_id, total) in enumerate(models):
                name = QLabel(self._pretty_model(model_id))
                name.setProperty("class", "model-name")
                bar = UsageBar(int(total / peak * 100) if peak else 0, "", accent=f"model-{index % 5}")
                total_label = QLabel(self._fmt_tokens(total))
                total_label.setProperty("class", "model-total")
                total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._model_layout.addWidget(name, index, 0)
                self._model_layout.addWidget(bar, index, 1)
                self._model_layout.addWidget(total_label, index, 2)
            align_label_text(self._model_container)
        except RuntimeError:
            self._model_container = None
            self._model_layout = None

    def _add_menu_sections(self, layout: QVBoxLayout) -> None:
        """Lay the popup out as one hero reading followed by a compact ledger.

        The 5-hour window is the constraint that actually stops you working, so it gets the
        hero treatment and answers "how close am I?" on its own. The 7-day window and any
        per-model weekly caps are slower-moving context, so they compress to one line each.
        Giving all three equal weight - which is what a uniform list did - left the panel with
        nothing for the eye to land on.
        """
        self._section_widgets = {}
        self._usage_frames = [self._build_hero_frame("five", self.config.five_hour_reset_format)]

        secondary = [("seven", "7-day", self.config.seven_day_reset_format)]
        secondary += [
            (f"scoped:{s['name']}", s["name"], self.config.seven_day_reset_format) for s in self._data.get("scoped", [])
        ]
        ledger = self._build_ledger_frame(secondary)
        if ledger is not None:
            self._usage_frames.append(ledger)

        for frame in self._usage_frames:
            layout.addWidget(frame)
        if self.config.sessions.enabled and self.config.sessions.show_in_menu:
            layout.addWidget(self._build_sessions_section())
        if self.config.token_history.enabled:
            layout.addWidget(self._build_token_section())
        if self.config.footer.enabled:
            layout.addWidget(self._build_meta_line())

    def _build_hero_frame(self, key: str, reset_format: str) -> QFrame:
        """The one reading the popup exists to deliver: percentage, what it measures, bar, countdown.

        The percentage is named by a sentence rather than a chip - a bare number means nothing,
        and a chip here would collide with the chips that label actual sections below.
        """
        value = self._data.get(key)
        raw = self._data.get(f"{key}_raw")
        reset_iso = self._data.get(f"{key}_reset_iso")
        level = self._level_class(value)

        frame = QFrame()
        frame.setProperty("class", "section hero")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        value_label = QLabel(f"{self._pct_decimal(raw, value)}%")
        value_label.setProperty("class", f"hero-value {level}")
        caption = QLabel("of your 5-hour window")
        caption.setProperty("class", "hero-caption")

        if self.config.clawd.enabled or self.config.sky.enabled:
            # Clawd lives beside the reading, on the same ground line as its caption, as in
            # the original widget's top row, and the sky spans the two of them from behind.
            if self.config.sky.enabled:
                self._sky = SkyScene(self.config.clawd.scale)
                top = self._sky
            else:
                top = QFrame()
                top.setProperty("class", "hero-top")
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(0, 0, 0, 0)
            top_layout.setSpacing(0)
            reading = QFrame()
            reading.setProperty("class", "hero-reading")
            reading_layout = QVBoxLayout(reading)
            reading_layout.setContentsMargins(0, 0, 0, 0)
            reading_layout.setSpacing(0)
            reading_layout.addWidget(value_label, 0, Qt.AlignmentFlag.AlignLeft)
            reading_layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignLeft)
            top_layout.addWidget(reading, 0, Qt.AlignmentFlag.AlignBottom)
            if self.config.clawd.enabled:
                self._clawd = ClawdScene(self.config.clawd.scale, self.config.crit_percent)
                self._clawd.stepped.connect(self._on_clawd_step)
                top_layout.addWidget(self._clawd, 1, Qt.AlignmentFlag.AlignBottom)
            else:
                top_layout.addStretch(1)
            layout.addWidget(top)
            self._feed_sky()
        else:
            layout.addWidget(value_label, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignLeft)

        progress = UsageBar(int(value) if isinstance(value, (int, float)) else 0, level)
        layout.addWidget(progress)

        footer = QFrame()
        footer.setProperty("class", "footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        reset_label = QLabel(self._reset_phrase(reset_iso, reset_format))
        reset_label.setProperty("class", "reset")
        footer_layout.addWidget(reset_label)
        footer_layout.addStretch()
        date_label = QLabel()
        date_label.setProperty("class", "date")
        date_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._apply_date(date_label, reset_iso)
        footer_layout.addWidget(date_label)
        layout.addWidget(footer)

        self._section_widgets[key] = {
            "variant": "hero",
            "reset_format": reset_format,
            "bar": progress,
            "reset": reset_label,
            "percent": value_label,
            "caption": caption,
            "date": date_label,
        }
        return frame

    def _build_ledger_frame(self, entries: list[tuple[str, str, str]]) -> QFrame | None:
        """The slower windows, one line each: name, bar, percentage, countdown.

        Tight rows against the hero's generous block is what creates the hierarchy; these are
        context you scan, not the number you came for.
        """
        if not entries:
            return None
        frame = QFrame()
        frame.setProperty("class", "section ledger")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for key, name, reset_format in entries:
            if key.startswith("scoped:"):
                scoped = next(
                    (s for s in self._data.get("scoped", []) if s["name"] == key.removeprefix("scoped:")),
                    None,
                )
                value = scoped["value"] if scoped else None
                reset_iso = scoped["reset_iso"] if scoped else None
            else:
                value = self._data.get(key)
                reset_iso = self._data.get(f"{key}_reset_iso")
            level = self._level_class(value)

            row = QFrame()
            row.setProperty("class", "row")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            name_label = QLabel(name)
            name_label.setProperty("class", "name")
            row_layout.addWidget(name_label)

            progress = UsageBar(int(value) if isinstance(value, (int, float)) else 0, level)
            row_layout.addWidget(progress, 1)

            percent_label = QLabel(f"{self._pct(value)}%")
            percent_label.setProperty("class", f"percent {level}")
            percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(percent_label)

            countdown = QLabel(self._fmt_duration(reset_iso))
            countdown.setProperty("class", "countdown")
            countdown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(countdown)

            layout.addWidget(row)
            self._section_widgets[key] = {
                "variant": "ledger",
                "reset_format": reset_format,
                "bar": progress,
                "percent": percent_label,
                "countdown": countdown,
            }
        return frame

    def _sync_usage_sections(self) -> None:
        """Update the 5h/7d bars, percentages and reset lines in place when fresh data arrives.

        Mutating the existing widgets (rather than destroying the frames and inserting new ones)
        avoids the layout recalculation and flash that rebuilding causes on every poll.
        """
        if not self._section_widgets:
            return
        try:
            # isVisible() can raise if the popup's C++ object was already deleted, so it stays
            # inside the guard rather than in the early-return check above.
            if self._menu is None or not self._menu.isVisible():
                return
            scoped_by_name = {s["name"]: s for s in self._data.get("scoped", [])}
            for key, w in self._section_widgets.items():
                if key.startswith("scoped:"):
                    scoped = scoped_by_name.get(key.removeprefix("scoped:"))
                    if scoped is None:
                        # Cap disappeared mid-session (rare, plan/model change). The bar just
                        # stops updating rather than being removed; see _build_scoped_sections.
                        continue
                    value, raw, reset_iso = scoped["value"], scoped["raw"], scoped["reset_iso"]
                else:
                    value = self._data.get(key)
                    raw = self._data.get(f"{key}_raw")
                    reset_iso = self._data.get(f"{key}_reset_iso")
                level = self._level_class(value)
                w["bar"].set_value(int(value) if isinstance(value, (int, float)) else 0, level)
                if w.get("variant") == "ledger":
                    # One line: whole percent is enough at this size, and the countdown stands
                    # in for the full reset phrase.
                    w["percent"].setText(f"{self._pct(value)}%")
                    w["percent"].setProperty("class", f"percent {level}")
                    w["countdown"].setText(self._fmt_duration(reset_iso))
                    refresh_widget_style(w["percent"])
                    continue
                w["reset"].setText(self._reset_phrase(reset_iso, w["reset_format"]))
                w["percent"].setText(f"{self._pct_decimal(raw, value)}%")
                w["percent"].setProperty("class", f"hero-value {level}")
                self._apply_date(w["date"], reset_iso)
                refresh_widget_style(w["percent"])
                # Re-measured here, not at build time: the percentage's leading digit is what
                # sets the rail, and it changes as the window fills.
                align_label_ink(w["percent"], w.get("caption"))
        except RuntimeError:
            # Popup was destroyed; references are stale until it reopens.
            self._section_widgets = {}
            self._menu = None

    def _build_menu(self) -> PopupWidget:
        menu = PopupWidget(
            self,
            self.config.menu.blur,
            self.config.menu.round_corners,
            self.config.menu.round_corners_type,
            self.config.menu.border_color,
            persistent=True,
            pinnable=True,
        )
        self._menu = menu
        menu.setProperty("class", "claude-usage-menu")

        layout = QVBoxLayout(menu)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._menu_layout = layout

        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        # Title and account stack, so the header answers "usage for whom" as well as "what".
        # It matters on a machine signed into more than one account.
        app_icon = self._build_header_icon()
        if app_icon is not None:
            header_layout.addWidget(app_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title_stack = QFrame()
        title_stack.setProperty("class", "title-stack")
        title_layout = QVBoxLayout(title_stack)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        title_label = QLabel("Claude Usage")
        title_label.setProperty("class", "text")
        title_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)

        # With the footer on, the account is part of its closing line instead.
        account_text = "" if self.config.footer.enabled else self._account_line()
        if account_text:
            account_label = QLabel(account_text)
            account_label.setProperty("class", "account")
            set_tooltip(account_label, self._account_tooltip())
            title_layout.addWidget(account_label, 0, Qt.AlignmentFlag.AlignLeft)
            # Title and account are fixed for the life of the popup, so one measure is enough.
            align_label_ink(title_label, account_label)

        header_layout.addWidget(title_stack)
        header_layout.addStretch()

        if self.config.hearts.enabled:
            self._hearts = HeartsView(self.config.hearts.scale)
            header_layout.addWidget(self._hearts, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh_btn = QPushButton("\U000f0450")
        refresh_btn.setProperty("class", "refresh")
        set_tooltip(refresh_btn, "Refresh now")
        refresh_btn.clicked.connect(self._refresh)
        header_layout.addWidget(refresh_btn)

        pin_btn = QPushButton(self.config.menu.pin_icon)
        pin_btn.setCheckable(True)
        pin_btn.setProperty("class", "pin-btn")
        set_tooltip(pin_btn, "Pin this window")

        def on_pin_toggled(checked: bool) -> None:
            pin_btn.setText(self.config.menu.unpin_icon if checked else self.config.menu.pin_icon)
            pin_btn.setProperty("class", "pin-btn pinned" if checked else "pin-btn")
            set_tooltip(pin_btn, "Unpin this window" if checked else "Pin this window")
            refresh_widget_style(pin_btn)
            menu.set_pinned(checked)

        pin_btn.toggled.connect(on_pin_toggled)
        header_layout.addWidget(pin_btn)

        layout.addWidget(header)
        if self.config.status.enabled and self.config.status.show_in_menu:
            layout.addWidget(self._build_status_row())
        self._add_menu_sections(layout)
        # Surplus height (when a period switch shrinks the model rows) pools here at the bottom
        # rather than spreading as gaps between sections; the height resize below then trims it.
        layout.addStretch(1)

        # Before the first measure: the indent it removes is part of each label's width.
        align_label_text(menu)
        menu.adjustSize()
        # Lock the width after the first layout so switching periods only changes the height. This
        # respects the stylesheet min-width (adjustSize already applied it) without letting longer
        # model names reflow the popup - which is what made the bars change length between periods.
        menu.setFixedWidth(menu.width())
        return menu

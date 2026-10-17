from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClaudeUsageCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_right: str = "toggle_label"
    on_middle: str = "do_nothing"


class ClaudeUsageMenuConfig(CustomBaseModel):
    # Path to an image shown at the left of the popup header. The mark already identifies
    # the widget on the bar, so repeating it here lets a pinned or detached popup say what it
    # belongs to on its own. Blank leaves the header as it was.
    icon: str = ""
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    pin_icon: str = "\ue718"
    unpin_icon: str = "\ue77a"


class ClaudeTokenHistoryConfig(CustomBaseModel):
    enabled: bool = False
    default_period: Literal["session", "today", "week", "month", "year"] = "today"
    show_graph: bool = False
    show_graph_grid: bool = False
    show_models: bool = False
    week_starts_on: Literal["monday", "sunday"] = "monday"
    # Cache-read tokens dominate the totals for heavy users; set false for "new work only".
    count_cache_read: bool = True
    scan_interval: int = Field(default=120, ge=30, le=3600)


class ClaudeStatusConfig(CustomBaseModel):
    enabled: bool = False
    show_in_menu: bool = True
    icon: str = "●"  # coloured via .status.<level> CSS classes
    poll_interval: int = Field(default=300, ge=60, le=3600)


class ClaudeLevelColorsConfig(CustomBaseModel):
    low: str = "#4ade80"
    medium: str = "#fbbf24"
    high: str = "#f87171"


class ClaudeUsageProgressBarConfig(CustomBaseModel):
    enabled: bool = False
    progress_type: Literal["circular", "linear_horizontal", "linear_vertical"] = "circular"
    size: int = Field(default=36, ge=1, le=200)
    thickness: int = Field(default=6, ge=1, le=100)
    radius: int = Field(default=3, ge=0, le=100)
    color: str | list[str] = "#4caf50"
    background_color: str = "#3c3c3c"
    position: Literal["left", "right"] = "left"
    animation: bool = True
    # Recolour the ring by the same warn/crit thresholds as the popup bars (traffic light).
    # Unset keeps the single `color` whatever the value.
    level_colors: ClaudeLevelColorsConfig | None = None


class ClaudeClawdConfig(CustomBaseModel):
    # Clawd, the Claude Code crab, living in the popup beside the 5-hour reading.
    enabled: bool = False
    # Size of one of his pixels relative to the original widget's; 1.35 is its default.
    scale: float = Field(default=1.35, ge=0.6, le=4.0)


class ClaudeSessionsConfig(CustomBaseModel):
    # Live Claude Code sessions (working / waiting / idle), from Claude Code's own registry.
    enabled: bool = False
    show_in_menu: bool = True
    # Rows listed in the popup; the rest collapse into "+N more". 0 shows only the counts.
    max_rows: int = Field(default=6, ge=0, le=20)
    poll_interval: int = Field(default=2, ge=1, le=60)
    # Claude config directories to watch (each holding a `sessions` folder). Empty finds
    # every ~/.claude* directory, so all accounts on the machine count.
    dirs: list[str] = []
    # nf-md-play: a plain U+25B6 is missing from most Nerd Fonts, and the fallback that
    # supplies it on Windows is Segoe UI Emoji, which paints a blue emoji tile on the bar.
    working_icon: str = "\U000f040a"
    waiting_icon: str = "?"
    idle_icon: str = "○"


class ClaudeHeartsConfig(CustomBaseModel):
    # Three pixel hearts in the popup header: how much of the 5-hour window is left.
    enabled: bool = False
    scale: float = Field(default=1.35, ge=0.6, le=4.0)


class ClaudeFooterConfig(CustomBaseModel):
    # Closing line: plan and account on the left, when the numbers last arrived on the right.
    enabled: bool = False
    show_plan: bool = True
    # Mark the reading stale once it is older than this; 0 picks 3 x update_interval.
    stale_after: int = Field(default=0, ge=0, le=86400)


class ClaudeUsageConfig(CustomBaseModel):
    label: str = "Claude {five_hour}%"
    label_alt: str = "Claude {seven_day}%"
    update_interval: int = Field(default=60, ge=30, le=3600)
    cache_ttl: int = Field(default=120, ge=0, le=3600)
    token_history: ClaudeTokenHistoryConfig = ClaudeTokenHistoryConfig()
    status: ClaudeStatusConfig = ClaudeStatusConfig()
    # Popup reset line per window: "relative" -> "Resets in 4h 11m", "absolute" -> "Resets on Sat @ 6:00 AM".
    five_hour_reset_format: Literal["relative", "absolute"] = "relative"
    seven_day_reset_format: Literal["relative", "absolute"] = "absolute"
    reset_show_date: bool = True
    # Show which account the numbers belong to, under the popup title and in the tooltip.
    # Worth turning off if you screenshot the bar, since it puts an email on screen.
    show_account: bool = True
    # Clock style for every time the popup renders. 24h also drops the AM/PM suffix.
    time_format: Literal["12h", "24h"] = "12h"
    # strftime template for the exact reset timestamp under each window. The default keeps
    # the widget's original US-style line; "%Y-%m-%d %H:%M" matches the clock widget.
    reset_datetime_format: str = "%m/%d/%Y, %I:%M:%S %p"
    # Append the countdown to reset lines phrased absolutely, so every window shows how long
    # is left and not just when it lands. No effect on relative lines, which are already a duration.
    show_reset_duration: bool = True
    # Whether {five_hour_value}/{seven_day_value} (and the progress bar) report the share
    # of the window consumed or the share still available. Flipped at runtime by the
    # "toggle_usage_mode" callback. The explicit {*_used}/{*_remaining} placeholders ignore it.
    usage_mode: Literal["used", "remaining"] = "used"
    mode_label_used: str = "used"
    mode_label_remaining: str = "left"
    tooltip: bool = True
    # Where the bars, percentages and ring turn from low to medium (warn) and high (crit).
    warn_percent: int = Field(default=60, ge=1, le=100)
    crit_percent: int = Field(default=85, ge=1, le=100)
    clawd: ClaudeClawdConfig = ClaudeClawdConfig()
    sessions: ClaudeSessionsConfig = ClaudeSessionsConfig()
    hearts: ClaudeHeartsConfig = ClaudeHeartsConfig()
    footer: ClaudeFooterConfig = ClaudeFooterConfig()
    # Tracks whichever window the bar label is currently showing (5h, or 7d after toggle_label).
    progress_bar: ClaudeUsageProgressBarConfig = ClaudeUsageProgressBarConfig()
    callbacks: ClaudeUsageCallbacksConfig = ClaudeUsageCallbacksConfig()
    menu: ClaudeUsageMenuConfig = ClaudeUsageMenuConfig()
    keybindings: list[KeybindingConfig] = []

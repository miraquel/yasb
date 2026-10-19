from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig
from core.validation.widgets.yasb.claude_usage import ClaudeLevelColorsConfig, ClaudeSkyConfig


class CodexUsageCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_middle: str = "refresh"
    on_right: str = "toggle_label"


class CodexUsageMenuConfig(CustomBaseModel):
    # Path to an image shown at the left of the popup header. The mark already identifies
    # the widget on the bar, so repeating it here lets a pinned or detached popup say what it
    # belongs to on its own. Blank leaves the header as it was.
    icon: str = ""
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: Literal["up", "down"] = "down"
    offset_top: int = 6
    offset_left: int = 0
    show_overview: bool = True
    show_models: bool = True
    show_activity: bool = True
    show_resets: bool = True
    show_details: bool = True
    refresh_icon: str = "\ue72c"
    previous_page_icon: str = "\ue76b"
    next_page_icon: str = "\ue76c"


class CodexUsageProgressBarConfig(CustomBaseModel):
    enabled: bool = True
    progress_type: Literal["circular", "linear_horizontal", "linear_vertical"] = "linear_horizontal"
    size: int = Field(default=36, ge=1, le=200)
    thickness: int = Field(default=6, ge=1, le=100)
    radius: int = Field(default=3, ge=0, le=100)
    color: str | list[str] = "#4caf50"
    background_color: str = "#3c3c3c"
    position: Literal["left", "right"] = "left"
    animation: bool = True
    # Recolour the ring by warn_percent / crit_percent (traffic light), as on the Claude widget:
    # `low` while under warn, `medium` from warn, `high` from crit. Unset keeps `color`.
    level_colors: ClaudeLevelColorsConfig | None = None


class CodexSessionsConfig(CustomBaseModel):
    # Live Codex sessions (working / waiting / idle), read from Codex's own files in ~/.codex.
    enabled: bool = False
    show_in_menu: bool = True
    # Rows listed in the popup; the rest collapse into "+N more". 0 shows only the counts.
    max_rows: int = Field(default=6, ge=0, le=20)
    poll_interval: int = Field(default=2, ge=1, le=60)
    # Codex keeps finished chats loaded for hours (Claude Code's Codex plugin, the desktop app),
    # so an idle one only counts while its last turn is this recent.
    idle_minutes: int = Field(default=30, ge=1, le=1440)
    # nf-md-play, as on the Claude widget.
    working_icon: str = "󰐊"
    waiting_icon: str = "?"
    idle_icon: str = "○"


class CodexPetConfig(CustomBaseModel):
    # The Codex pet, living in the popup beside the main reading, as Clawd does for Claude.
    enabled: bool = False
    # Size of one of its pixels, on Clawd's scale; 1.35 matches Clawd's default.
    scale: float = Field(default=1.35, ge=0.6, le=4.0)


class CodexHeartsConfig(CustomBaseModel):
    # Three pixel hearts in the popup header: how much of the main (primary) window is left.
    enabled: bool = False
    scale: float = Field(default=1.35, ge=0.6, le=4.0)


class CodexFooterConfig(CustomBaseModel):
    # Closing line: plan and account on the left, when the numbers last arrived on the right.
    enabled: bool = False
    show_plan: bool = True
    # Mark the reading stale once it is older than this; 0 picks cache_ttl + 2 x update_interval.
    stale_after: int = Field(default=0, ge=0, le=86400)


class CodexUsageConfig(CustomBaseModel):
    label: str = "Codex {primary_remaining}%"
    label_alt: str = "Codex {secondary_window} {secondary_remaining}%"
    codex_path: str = "codex"
    update_interval: int = Field(default=60, ge=30, le=3600)
    cache_ttl: int = Field(default=120, ge=0, le=3600)
    timeout: float = Field(default=15.0, ge=1.0, le=60.0)
    tooltip: bool = True
    # Whether {primary_value}/{secondary_value} (and the progress bar) report the share of
    # the window still available or the share consumed. Flipped at runtime by the
    # "toggle_usage_mode" callback. The explicit {*_used}/{*_remaining} placeholders ignore it.
    usage_mode: Literal["used", "remaining"] = "remaining"
    mode_label_used: str = "used"
    mode_label_remaining: str = "left"
    # Show which account the numbers belong to, beside the popup title and in the tooltip.
    # Read over the app-server (account/read), never from ~/.codex/auth.json. Turn it off if
    # you screenshot your bar, since it puts an email on screen - and the request is then
    # not made at all.
    show_account: bool = True
    show_token_usage: bool = True
    stale_icon: str = "⚠"
    # Share used where the bars, percentages and ring turn from good to low (warn) and critical
    # (crit). The defaults are the widget's original split: 50% and 20% left.
    warn_percent: int = Field(default=50, ge=1, le=100)
    crit_percent: int = Field(default=80, ge=1, le=100)
    pet: CodexPetConfig = CodexPetConfig()
    # The sky behind the reading and the pet; the same options as the Claude widget's.
    sky: ClaudeSkyConfig = ClaudeSkyConfig()
    sessions: CodexSessionsConfig = CodexSessionsConfig()
    hearts: CodexHeartsConfig = CodexHeartsConfig()
    footer: CodexFooterConfig = CodexFooterConfig()
    progress_bar: CodexUsageProgressBarConfig = CodexUsageProgressBarConfig()
    callbacks: CodexUsageCallbacksConfig = CodexUsageCallbacksConfig()
    menu: CodexUsageMenuConfig = CodexUsageMenuConfig()
    keybindings: list[KeybindingConfig] = []

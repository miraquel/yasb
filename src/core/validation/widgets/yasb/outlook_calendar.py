from datetime import datetime

from pydantic import Field, field_validator

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class OutlookCalendarCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_card"
    on_middle: str = "open_outlook"
    on_right: str = "toggle_label"


class OutlookCalendarIconsConfig(CustomBaseModel):
    # Nerd Fonts v3 codepoint, outside the pre-v3 Material Design range (U+F500-U+FD46)
    # that v3 removed.
    default: str = ""  # fa-calendar


class OutlookCalendarMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    min_width: int = Field(default=340, ge=200, le=1000)
    max_rows: int = Field(default=12, ge=1, le=50)


class OutlookCalendarConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {countdown} · {title}"
    label_alt: str = "<span>{icon}</span> {time} · {title}"
    # Shown in place of the template when there is nothing to count down to.
    empty_text: str = "No events"
    closed_text: str = "Outlook closed"
    class_name: str = ""
    days: int = Field(default=7, ge=1, le=31)
    update_interval: int = Field(default=300, ge=60, le=3600)
    soon_minutes: int = Field(default=15, ge=0, le=240)
    max_title_length: int = Field(default=20, ge=0, le=200)
    time_format: str = "%H:%M"
    # Look for a Teams, Zoom or Meet link in the event body too. Turn off if Outlook ever
    # asks whether to allow a program to access it (its antivirus check has lapsed).
    scan_body: bool = True
    tooltip: bool = True
    icons: OutlookCalendarIconsConfig = OutlookCalendarIconsConfig()
    menu: OutlookCalendarMenuConfig = OutlookCalendarMenuConfig()
    callbacks: OutlookCalendarCallbacksConfig = OutlookCalendarCallbacksConfig()
    keybindings: list[KeybindingConfig] = []

    @field_validator("time_format")
    @classmethod
    def _valid_time_format(cls, value: str) -> str:
        # Windows strftime rejects flags such as %-I with a ValueError, which would otherwise
        # surface when the widget builds its first label.
        try:
            datetime(2026, 1, 1, 13, 5).strftime(value)
        except ValueError as error:
            raise ValueError(f"invalid time_format {value!r}: {error}") from error
        return value

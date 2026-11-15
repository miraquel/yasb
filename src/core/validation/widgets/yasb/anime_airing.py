from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)

ListStatus = Literal["watching", "on_hold", "plan_to_watch"]


class AnimeAiringCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_card"
    on_middle: str = "do_nothing"
    on_right: str = "toggle_label"


class AnimeAiringIconsConfig(CustomBaseModel):
    # Nerd Fonts v3 codepoints, outside the pre-v3 Material Design range (U+F500-U+FD46)
    # that v3 removed.
    default: str = ""  # fa-tv


class AnimeAiringMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    min_width: int = Field(default=340, ge=200, le=1000)
    max_rows: int = Field(default=10, ge=1, le=50)
    show_covers: bool = True


class AnimeAiringNotificationsConfig(CustomBaseModel):
    enabled: bool = True
    # Negative for a heads-up before the broadcast, positive to wait for a stream to go up.
    offset_minutes: int = Field(default=0, ge=-1440, le=1440)
    # An episode that aired while the machine slept or yasb was closed is still announced
    # if it is at most this old; older ones are skipped rather than arriving as a burst.
    catch_up_hours: int = Field(default=12, ge=0, le=168)


class AnimeAiringConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {title} {countdown}"
    label_alt: str = "<span>{icon}</span> Ep {episode} · {air_time}"
    class_name: str = ""
    username: str = ""
    statuses: list[ListStatus] = Field(default=["watching"], min_length=1)
    title_language: Literal["romaji", "english"] = "romaji"
    max_title_length: int = Field(default=20, ge=0, le=200)
    update_interval: int = Field(default=1800, ge=300, le=86400)
    tooltip: bool = True
    icons: AnimeAiringIconsConfig = AnimeAiringIconsConfig()
    menu: AnimeAiringMenuConfig = AnimeAiringMenuConfig()
    notifications: AnimeAiringNotificationsConfig = AnimeAiringNotificationsConfig()
    callbacks: AnimeAiringCallbacksConfig = AnimeAiringCallbacksConfig()
    keybindings: list[KeybindingConfig] = []

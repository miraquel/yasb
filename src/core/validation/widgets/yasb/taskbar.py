# validation model for the taskbar widget

from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    AnimationConfig,
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
    PaddingConfig,
    ShadowConfig,
)


class IgnoreAppsConfig(CustomBaseModel):
    classes: list[str] = []
    processes: list[str] = []
    titles: list[str] = []


class TitleLabelConfig(CustomBaseModel):
    enabled: bool = False
    show: Literal["focused", "always"] = "focused"
    min_length: int = 10
    max_length: int = 30


class PreviewConfig(CustomBaseModel):
    enabled: bool = False
    width: int = Field(default=240, ge=100)
    delay: int = 400
    padding: int = 8
    margin: int = 8


class BadgeConfig(CustomBaseModel):
    enabled: bool = False
    type: Literal["dot", "number"] = "dot"
    position: Literal["top-right", "top-left", "bottom-right", "bottom-left"] = "top-right"
    color: str = "#ff5555"
    border_color: str = "transparent"
    border_width: int = Field(default=0, ge=0, le=10)
    size: int = Field(default=8, ge=4, le=32)
    font_size: int = Field(default=7, ge=4, le=24)
    offset_x: int = Field(default=0, ge=-20, le=20)
    offset_y: int = Field(default=0, ge=-20, le=20)


class TaskbarCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_window"
    on_right: str = "context_menu"


class TaskbarConfig(CustomBaseModel):
    icon_size: int = 16
    tooltip: bool = False
    monitor_exclusive: bool = False
    show_only_visible: bool = False
    strict_filtering: bool = True
    ignore_apps: IgnoreAppsConfig = IgnoreAppsConfig()
    animation: AnimationConfig | bool = AnimationConfig()
    title_label: TitleLabelConfig = TitleLabelConfig()
    hide_empty: bool = False
    container_padding: PaddingConfig = PaddingConfig()
    label_shadow: ShadowConfig = ShadowConfig()
    container_shadow: ShadowConfig = ShadowConfig()
    preview: PreviewConfig = PreviewConfig()
    badge: BadgeConfig = BadgeConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: TaskbarCallbacksConfig = TaskbarCallbacksConfig()

from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class SpeedThresholdConfig(CustomBaseModel):
    min_upload: int = 1000
    min_download: int = 1000


class TrafficMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "system"
    alignment: str = "left"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    show_interface_name: bool = True
    show_internet_info: bool = True


class TrafficSparklineConfig(CustomBaseModel):
    enabled: bool = False
    bars: int = Field(default=12, ge=1, le=200)
    bar_width: int = Field(default=2, ge=1, le=32)
    # 0 is allowed: bars that touch.
    bar_gap: int = Field(default=1, ge=0, le=32)
    # At least 3 so both directions keep a row of their own next to the baseline.
    height: int = Field(default=16, ge=3, le=128)
    # Bytes/s; the smallest speed that fills a bar, so a quiet line never draws full height.
    scale_floor: int = Field(default=65536, ge=1)


class TrafficCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"
    on_middle: str = "do_nothing"
    on_right: str = "do_nothing"


class TrafficWidgetConfig(CustomBaseModel):
    label: str = "\ueb01 \ueab4 {download_speed} | \ueab7 {upload_speed}"
    label_alt: str = "\ueb01 \ueab4 {upload_speed} | \ueab7 {download_speed}"
    class_name: str = ""
    interface: str = "auto"
    update_interval: int = 1000
    hide_if_offline: bool = False
    max_label_length: int = 0
    max_label_length_align: Literal["left", "center", "right"] = "left"
    speed_unit: Literal["bits", "bytes"] = "bits"
    hide_decimal: bool = False
    speed_threshold: SpeedThresholdConfig = SpeedThresholdConfig()
    menu: TrafficMenuConfig = TrafficMenuConfig()
    sparkline: TrafficSparklineConfig = TrafficSparklineConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: TrafficCallbacksConfig = TrafficCallbacksConfig()

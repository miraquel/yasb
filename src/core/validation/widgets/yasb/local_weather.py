from typing import Self

from pydantic import Field, model_validator

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)
from core.validation.widgets.yasb.weather import WeatherIconsConfig


class LocalWeatherCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_card"
    on_middle: str = "do_nothing"
    on_right: str = "toggle_label"


class LocalWeatherMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class LocalWeatherRainConfig(CustomBaseModel):
    # An hour counts as wet at this chance of rain or more, and as heavy at the second.
    wet_threshold: int = Field(default=30, ge=1, le=100)
    heavy_threshold: int = Field(default=80, ge=1, le=100)
    # How many hours the pill's strip and the card's bars cover, starting with this one.
    pill_hours: int = Field(default=6, ge=1, le=12)
    card_hours: int = Field(default=12, ge=2, le=24)

    @model_validator(mode="after")
    def _heavy_is_wet(self) -> Self:
        if self.heavy_threshold < self.wet_threshold:
            raise ValueError("heavy_threshold must be at least wet_threshold")
        return self


class LocalWeatherConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {temp}"
    label_alt: str = "{location} {min_temp}–{max_temp}"
    class_name: str = ""
    # "env" reads YASB_WEATHER_API_KEY, so the key never sits in config.yaml.
    api_key: str = "env"
    # Only used when Windows location is off or has no fix.
    location: str = Field(min_length=1)
    update_interval: int = Field(default=600, ge=60, le=86400)
    rain: LocalWeatherRainConfig = LocalWeatherRainConfig()
    icons: WeatherIconsConfig = WeatherIconsConfig()
    menu: LocalWeatherMenuConfig = LocalWeatherMenuConfig()
    callbacks: LocalWeatherCallbacksConfig = LocalWeatherCallbacksConfig()
    keybindings: list[KeybindingConfig] = []

import logging
import os
import re
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from core.utils.utilities import PopupWidget, refresh_widget_style
from core.utils.widgets.local_weather.bars import RainBars
from core.utils.widgets.local_weather.card import WeatherCard
from core.utils.widgets.local_weather.forecast import Forecast, parse_forecast
from core.utils.widgets.local_weather.location import LocationTracker, Place
from core.utils.widgets.local_weather.rain import Thresholds
from core.utils.widgets.local_weather.views import NO_DATA_ICON, CardView, card_view, pill_view
from core.validation.widgets.yasb.local_weather import LocalWeatherConfig
from core.widgets.base import BaseWidget
from core.widgets.services.local_weather.fetcher import LocalWeatherFetcher
from core.widgets.services.local_weather.geolocation import windows_fix


class LocalWeatherWidget(BaseWidget):
    """Is it about to rain where I am? The pill shows the next hours as bars with when rain starts
    (or, while it rains, stops); the card adds twelve hours and the next two days.

    The forecast follows the laptop through Windows location, falling back to the configured
    address. Its colours come from state classes on the container (the condition, then the rain
    state), so styles.css owns every colour.
    """

    validation_schema = LocalWeatherConfig

    def __init__(self, config: LocalWeatherConfig):
        super().__init__(class_name=f"local-weather-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._forecast: Forecast | None = None
        self._place: Place | None = None  # where self._forecast came from
        self._popup: PopupWidget | None = None
        self._card: WeatherCard | None = None
        self._thresholds = Thresholds(config.rain.wet_threshold, config.rain.heavy_threshold)
        self._icons = config.icons.model_dump()

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        # The strip and the time are children of their own, so they stay in both label modes.
        self._strip = RainBars(config.rain.pill_hours, 3, 2, 1, 13)
        self._strip.setProperty("class", "rain-strip")
        self._time = QLabel()
        self._time.setProperty("class", "rain-time")
        self._time.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._widget_container_layout.addWidget(self._strip, 0, Qt.AlignmentFlag.AlignVCenter)
        self._widget_container_layout.addWidget(self._time)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_card", self._toggle_card)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle

        self._fetcher: LocalWeatherFetcher | None = None
        key = config.api_key if config.api_key != "env" else os.getenv("YASB_WEATHER_API_KEY", "")
        if key:
            self._fetcher = LocalWeatherFetcher(
                self, key, LocationTracker(config.location), windows_fix, config.update_interval * 1000
            )
            self._fetcher.finished.connect(self._on_forecast)
            self._fetcher.failed.connect(self._on_failed)
            self._fetcher.start()
        else:
            logging.error("Local weather: no WeatherAPI key; set api_key, or YASB_WEATHER_API_KEY in .env")

        # Re-render on the minute, aligned to the wall clock, so the bars move on the hour.
        self._minute_timer = QTimer(self)
        self._minute_timer.setInterval(60_000)
        self._minute_timer.timeout.connect(self._render)
        now = datetime.now()
        QTimer.singleShot(max((60 - now.second) * 1000 - now.microsecond // 1000, 0), self._start_minute_timer)

        self._render()

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()

    def _start_minute_timer(self) -> None:
        self._render()
        self._minute_timer.start()

    # ------------------------------------------------------------------ data ----
    def _on_forecast(self, payload: dict, place: Place) -> None:
        forecast = parse_forecast(payload, self._now().timestamp())
        if forecast is not None:
            self._forecast, self._place = forecast, place
        self._render()

    def _on_failed(self, place: Place) -> None:
        # Keep the last forecast: the views decide when it is stale, and when it is too old.
        self._render()

    # ------------------------------------------------------------------ pill ----
    def _render(self) -> None:
        view = pill_view(
            self._forecast, self.config.location, self._now(), self._thresholds, self.config.rain.pill_hours
        )
        values = {**view.placeholders, "{icon}": self._icons.get(view.icon_key, self._icons[NO_DATA_ICON])}
        self._fill(self._widgets, self.config.label, values)
        self._fill(self._widgets_alt, self.config.label_alt, values)
        self._widget_container.setProperty("class", f"widget-container {view.condition} {view.reading.state}")
        self._strip.set_bars(view.reading.bars)
        self._time.setText(view.reading.time)
        self._time.setHidden(not view.reading.time)
        refresh_widget_style(self._widget_container, *self._widgets, *self._widgets_alt, self._strip, self._time)
        self._sync_card()

    @staticmethod
    def _fill(widgets: list[QLabel], content: str, values: dict[str, str]) -> None:
        parts = [p.strip() for p in re.split(r"(<span.*?>.*?</span>)", content) if p.strip()]
        for widget, part in zip(widgets, parts, strict=False):
            for placeholder, value in values.items():
                part = part.replace(placeholder, value)
            widget.setText(re.sub(r"<span.*?>|</span>", "", part).strip())

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._render()

    # ------------------------------------------------------------------ card ----
    def _card_view(self) -> CardView:
        return card_view(
            self._forecast,
            self._place,
            self.config.location,
            self._now(),
            self._thresholds,
            self.config.rain.card_hours,
        )

    def _build_card(self) -> WeatherCard:
        card = WeatherCard(self._icons, card_hours=self.config.rain.card_hours)
        card.set_view(self._card_view())
        return card

    def _toggle_card(self) -> None:
        m = self.config.menu
        popup = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        popup.setProperty("class", "local-weather-menu")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        card = self._build_card()
        layout.addWidget(card)
        popup.adjustSize()
        popup.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        popup.show()
        if popup.isVisible():
            self._popup, self._card = popup, card
        else:
            # PopupWidget.show() found this bar's card already open and closed it instead.
            popup.deleteLater()
            self._forget_card()

    def _forget_card(self) -> None:
        self._popup = None
        self._card = None

    def _sync_card(self) -> None:
        if self._popup is None or self._card is None:
            return
        try:
            if not self._popup.isVisible():
                self._forget_card()
                return
            self._card.set_view(self._card_view())
            self._popup.adjustSize()
        except RuntimeError:
            self._forget_card()  # the popup's C++ object is already gone

"""The weather card: the answer, then the bars.

A header (where and how warm), the hero (when rain starts or stops, as the one Display figure,
over twelve hourly bars with the pixel sky behind it), then the next two days. ``set_view``
updates it in place, so the sky keeps animating across the minute refreshes.
"""

from collections.abc import Mapping

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.utils.utilities import ElidedLabel, align_label_text, refresh_widget_style
from core.utils.widgets.ai_usage.scene import SkyScene
from core.utils.widgets.ai_usage.sky import Weather
from core.utils.widgets.local_weather.bars import RainBars
from core.utils.widgets.local_weather.views import NO_DATA, NO_DATA_ICON, CardView

SKY_HEIGHT = 150
DAY_ROWS = 2


def _label(cls: str, align: Qt.AlignmentFlag | None = None) -> QLabel:
    label = QLabel()
    label.setProperty("class", cls)
    if align is not None:
        label.setAlignment(align)
    return label


def _frame(cls: str) -> QFrame:
    frame = QFrame()
    frame.setProperty("class", cls)
    return frame


def _box(layout: QHBoxLayout | QVBoxLayout) -> QHBoxLayout | QVBoxLayout:
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return layout


class _DayRow(QFrame):
    def __init__(self):
        super().__init__()
        self.setProperty("class", "day")
        row = _box(QHBoxLayout(self))
        self.name = _label("name")
        self.mini = RainBars(8, 5, 2, 1.5, 14)
        self.mini.setProperty("class", "mini")
        self.text = _label("text")
        self.range = _label("range", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.name)
        row.addWidget(self.mini, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.text, 1)
        row.addWidget(self.range)


class WeatherCard(QFrame):
    def __init__(self, icons: Mapping[str, str], card_hours: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._icons = dict(icons)
        root = _box(QVBoxLayout(self))

        header = _frame("header")
        head = _box(QHBoxLayout(header))
        self._glyph = _label("glyph")
        text = _box(QVBoxLayout())
        self._title = _label("title")
        self._line = _label("line")
        text.addWidget(self._title)
        text.addWidget(self._line)
        temps = _box(QVBoxLayout())
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self._temp = _label("temp", right)
        self._feels = _label("feels", right)
        temps.addWidget(self._temp)
        temps.addWidget(self._feels)
        head.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(text)
        head.addStretch(1)
        head.addLayout(temps)
        root.addWidget(header)

        self._hero = _frame("section hero")
        hero = _box(QVBoxLayout(self._hero))
        self._hero_label = _label("hero-label")
        self._figure = _label("hero-figure")
        self._hero_line = _label("hero-line")
        self._alert = ElidedLabel()
        self._alert.setProperty("class", "hero-alert")
        self._alert.hide()
        self._bars = RainBars(card_hours, 14, 0, 3, 78, spread=True)
        self._bars.setProperty("class", "hour-bars")
        axis = _frame("axis")
        ticks = _box(QHBoxLayout(axis))
        self._ticks: list[QLabel] = []
        for i in range(card_hours):
            tick = _label("tick now" if i == 0 else "tick", Qt.AlignmentFlag.AlignHCenter)
            ticks.addWidget(tick, 1)
            self._ticks.append(tick)
        for widget in (self._hero_label, self._figure, self._hero_line, self._alert, self._bars, axis):
            hero.addWidget(widget)
        # The sky sits behind the hero's contents, outside its layout, pinned to the top.
        self.sky = SkyScene(parent=self._hero)
        self.sky.setProperty("class", "sky")
        self.sky.lower()
        self.sky.hide()
        self._hero.installEventFilter(self)
        root.addWidget(self._hero)

        self._days = _frame("section days")
        days = _box(QVBoxLayout(self._days))
        self._day_rows = [_DayRow() for _ in range(DAY_ROWS)]
        for row in self._day_rows:
            days.addWidget(row)
        root.addWidget(self._days)
        # QSS padding gives a label a frame, and Qt then indents its text; keep every text on
        # its box's left edge, so stacked lines share one.
        align_label_text(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a0 is self._hero and a1 is not None and a1.type() == QEvent.Type.Resize:
            self.sky.setGeometry(0, 0, self._hero.width(), SKY_HEIGHT)
        return super().eventFilter(a0, a1)

    def set_view(self, view: CardView) -> None:
        self._glyph.setText(self._icons.get(view.icon_key, self._icons.get(NO_DATA_ICON, "")))
        self._glyph.setProperty("class", f"glyph {view.condition}")
        self._title.setText(view.title)
        self._line.setText(view.line)
        self._line.setProperty("class", f"line {view.line_state}".strip())
        self._temp.setText(view.temp)
        self._temp.setProperty("class", "temp none" if view.temp == NO_DATA else "temp")
        self._feels.setText(view.feels)
        self._feels.setHidden(not view.feels)

        self._hero.setProperty("class", f"section hero {view.hero.state}")
        self._hero_label.setText(view.hero.label)
        self._figure.setText(view.hero.figure)
        self._hero_line.setText(view.hero.line)
        self._alert.setText(view.alert)
        self._alert.setHidden(not view.alert)
        self._bars.set_bars(view.bars)
        for tick, text in zip(self._ticks, view.axis, strict=False):
            tick.setText(text)

        if view.sky is None:
            self.sky.hide()
        else:
            model = self.sky.model
            model.latitude, model.longitude = view.sky.lat, view.sky.lon
            model.weather = Weather(view.sky.wmo, view.sky.wind_kph, view.sky.temp, view.sky.fetched_at)
            self.sky.show()

        for row, day in zip(self._day_rows, view.days, strict=False):
            row.name.setText(day.name)
            row.mini.set_bars(day.bars)
            row.text.setText(day.text)
            row.range.setText(day.range)
        for i, row in enumerate(self._day_rows):
            row.setHidden(i >= len(view.days))
        self._days.setHidden(not view.days)

        refresh_widget_style(self, *self.findChildren(QWidget))

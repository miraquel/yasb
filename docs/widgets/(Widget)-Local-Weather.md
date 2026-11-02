# Local Weather Widget

Answers one question at a glance: **is it about to rain where I am?** The bar shows the condition, the temperature and the next six hours as small bars. Beside them is when rain starts, or, while it rains, when it stops. Left-clicking opens a card with the answer in large type, twelve hourly bars with their chances, the current weather drawn as a pixel sky, and the next two days.

The forecast follows the laptop. Before each fetch the widget asks Windows location (the source Maps uses) where the machine is, and asks [WeatherAPI](https://www.weatherapi.com/) for that spot. When Windows location is off or has no fix, it uses the `location` address from the config instead, and the card says so.

## Options

| Option            | Type    | Default                                                                       | Description |
|-------------------|---------|-------------------------------------------------------------------------------|-------------|
| `label`           | string  | `"<span>{icon}</span> {temp}"`                                                | The bar label. The rain strip and its time always follow it. |
| `label_alt`       | string  | `"{location} {min_temp}–{max_temp}"`                                          | The alternate label (`toggle_label`). The strip and time stay. |
| `class_name`      | string  | `""`                                                                          | Additional CSS class name for the widget. |
| `api_key`         | string  | `"env"`                                                                       | WeatherAPI key. `"env"` reads `YASB_WEATHER_API_KEY` from the environment (`.env`), so the key never sits in `config.yaml`. |
| `location`        | string  | *(required)*                                                                  | The address to forecast when Windows location is unavailable, e.g. `"London"`. |
| `update_interval` | integer | `600`                                                                         | Seconds between forecasts (min `60`, max `86400`). Windows location is checked on every one. A failed fetch retries every minute. |
| `rain`            | dict    | *(see below)*                                                                 | When an hour counts as wet, and how many hours the bar and the card cover. |
| `icons`           | dict    | the [Weather widget's](./(Widget)-Weather) icons                              | Nerd Font glyph per condition: `sunnyDay`, `clearNight`, `cloudyDay`, `cloudyNight`, `rainyDay`, `rainyNight`, `snowyDay`, `snowyNight`, `blizzardDay`, `blizzardNight`, `foggyDay`, `foggyNight`, `thunderstormDay`, `thunderstormNight`, `default` (also shown with no forecast). |
| `menu`            | dict    | *(see below)*                                                                 | Appearance and position of the card. |
| `callbacks`       | dict    | `{on_left: "toggle_card", on_middle: "do_nothing", on_right: "toggle_label"}` | Mouse-click actions. |
| `keybindings`     | list    | `[]`                                                                          | Hotkey bindings. |

### Rain Options

| Option            | Type    | Default | Description |
|-------------------|---------|---------|-------------|
| `wet_threshold`   | integer | `30`    | An hour with this chance of rain or more is wet: a coloured bar, and a time beside the strip. Below it the bar is a flat dot. |
| `heavy_threshold` | integer | `80`    | An hour with this chance or more takes the heavy colour. Must be at least `wet_threshold`. |
| `pill_hours`      | integer | `6`     | Bars on the bar: this hour and the next ones (1–12). |
| `card_hours`      | integer | `12`    | Bars in the card (2–24). |

### Menu Options

| Option               | Type    | Default    | Description |
|----------------------|---------|------------|-------------|
| `blur`               | boolean | `true`     | Blur behind the card. |
| `round_corners`      | boolean | `true`     | Rounded corners (Windows 11). |
| `round_corners_type` | string  | `"normal"` | `normal` or `small`. |
| `border_color`       | string  | `"System"` | `System`, `None` or a hex colour. |
| `alignment`          | string  | `"right"`  | `left`, `right` or `center`. |
| `direction`          | string  | `"down"`   | `up` or `down`. |
| `offset_top`         | integer | `6`        | Vertical offset in pixels. |
| `offset_left`        | integer | `0`        | Horizontal offset in pixels. |

### Label Placeholders

| Placeholder   | Example  | With no forecast |
|---------------|----------|------------------|
| `{icon}`      | the condition's glyph | the `default` icon |
| `{temp}`      | `32°`    | `—` |
| `{feels}`     | `38°`    | `—` |
| `{location}`  | `London` (WeatherAPI's name for the spot) | the last place, or `location` |
| `{min_temp}`  | `24°`    | `—` |
| `{max_temp}`  | `32°`    | `—` |
| `{condition}` | `Cloudy` | `No forecast` |

### What the Bar Shows

- **Rain coming:** the first wet hour, e.g. `15:00`, or `now` when it is this hour.
- **Raining now:** the first hour after now that drops below `wet_threshold`, e.g. `18:00`. With no dry hour in the next 24, no time. "Raining now" means WeatherAPI reports precipitation, or a rain, drizzle, shower or thunder-with-rain condition. "Rain possible" does not count.
- **Dry:** no time.
- **Rain or thunder "possible"** (WeatherAPI's patchy-rain and thundery-outbreak codes): the icon is a cloud, since nothing is falling yet. The bars still show the chance hour by hour.
- **No forecast** (none yet, or the last one is over three hours old): every bar is a grey dot, and no time.

### Location and Privacy

Each refresh tries, in order: a fresh Windows location fix (about 500 m accuracy, up to ten minutes old, a ten-second timeout), then the last fix while under two hours old, then the `location` address. The last fix covers a lookup that failed, not one you switched off: with Windows location off or denied, the widget uses the `location` address straight away. Positions are rounded to two decimals (about 1 km) before they are sent to WeatherAPI. They are kept in memory only, and never written to disk or to the log.

If Windows location is off, turn it on under **Settings → Privacy & security → Location**, including "Let desktop apps access your location".

## Callbacks

| Callback       | Action |
|----------------|--------|
| `toggle_card`  | Open or close the card. |
| `toggle_label` | Switch between `label` and `label_alt`. |
| `do_nothing`   | Nothing. |

## Minimal Configuration

```yaml
weather:
  type: "yasb.local_weather.LocalWeatherWidget"
  options:
    location: "London"
```

## Example Configuration

```yaml
weather:
  type: "yasb.local_weather.LocalWeatherWidget"
  options:
    label: "<span>{icon}</span> {temp}"
    label_alt: "{location} {min_temp}–{max_temp}"
    api_key: "env"
    update_interval: 600
    location: "London"
    rain:
      wet_threshold: 30
      heavy_threshold: 80
      pill_hours: 6
      card_hours: 12
    menu:
      blur: true
      round_corners: true
      alignment: "right"
      direction: "down"
```

## Available Styles

> **Note:** The container carries two state classes: the condition (`sun`, `night`, `cloud`, `rain`, `storm`, or `none` with no forecast), then the rain state (`rain-coming`, `raining`, `dry` or `none`). Colour the icon and the time from those, not from the icon itself.

> **Note:** The bars are painted, so their colours are `-qproperty-` values: `wetcolor`, `heavycolor`, `drycolor`, `nonecolor`, and `labelcolor` for the card's chance labels. `padding` on `.rain-strip` and `.rain-time` sets the gaps on the bar.

```css
/* Bar */
.local-weather-widget .widget-container {}
.local-weather-widget .widget-container.sun {}        /* also night, cloud, rain, storm, none */
.local-weather-widget .widget-container.rain-coming {} /* also raining, dry, none */
.local-weather-widget .icon {}
.local-weather-widget .label {}
.local-weather-widget .label.alt {}
.local-weather-widget .rain-strip {}                  /* painted: -qproperty-*color */
.local-weather-widget .rain-time {}

/* Card */
.local-weather-menu {}
.local-weather-menu .header {}
.local-weather-menu .header .glyph {}                 /* plus the condition class */
.local-weather-menu .header .title {}
.local-weather-menu .header .line {}                  /* .warn: from the config address; .stale: refreshes failing */
.local-weather-menu .header .temp {}                  /* .none with no forecast */
.local-weather-menu .header .feels {}
.local-weather-menu .section.hero {}                  /* plus coming, coming-now, raining, raining-on, dry, none */
.local-weather-menu .hero-label {}
.local-weather-menu .hero-figure {}
.local-weather-menu .hero-line {}
.local-weather-menu .hero-alert {}
.local-weather-menu .hour-bars {}                     /* painted: -qproperty-*color, labelcolor; its font is the labels' */
.local-weather-menu .axis .tick {}
.local-weather-menu .axis .tick.now {}
.local-weather-menu .sky {}                           /* -qproperty-strength, fxopacity, edgefade, leftfade, bottomfade */
.local-weather-menu .section.days {}
.local-weather-menu .day {}
.local-weather-menu .day .name {}
.local-weather-menu .day .mini {}                     /* painted */
.local-weather-menu .day .text {}
.local-weather-menu .day .range {}
```

## Example Style

```css
.local-weather-widget .widget-container {
    background-color: #1e1e2e;
    padding: 0 8px;
    border-radius: 8px;
}
.local-weather-widget .icon { font-size: 18px; margin: 0 4px 1px 0; color: #a6adc8; }
.local-weather-widget .widget-container.sun .icon { color: #f9e2af; }
.local-weather-widget .widget-container.rain .icon { color: #89dceb; }
.local-weather-widget .widget-container.storm .icon { color: #74c7ec; }
.local-weather-widget .widget-container.night .icon { color: #b4befe; }
.local-weather-widget .widget-container.none .icon,
.local-weather-widget .widget-container.none .label { color: #6c7086; }
.local-weather-widget .rain-strip {
    padding-left: 8px;
    -qproperty-wetcolor: #89dceb;
    -qproperty-heavycolor: #74c7ec;
    -qproperty-drycolor: #45475a;
    -qproperty-nonecolor: #6c7086;
}
.local-weather-widget .rain-time { padding-left: 7px; }
.local-weather-widget .widget-container.rain-coming .rain-time { color: #89dceb; }
.local-weather-widget .widget-container.raining .rain-time { color: #a6adc8; }

.local-weather-menu {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 14px;
    min-width: 340px;
    max-width: 340px;
}
.local-weather-menu .header { padding: 14px 18px 12px 18px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.local-weather-menu .header .glyph { font-size: 22px; padding-right: 10px; }
.local-weather-menu .header .title { font-family: 'Segoe UI'; font-size: 14px; font-weight: 700; color: #cdd6f4; }
.local-weather-menu .header .line { font-family: 'Segoe UI'; font-size: 10px; font-weight: 600; color: #7f849c; }
.local-weather-menu .header .line.warn,
.local-weather-menu .header .line.stale { color: #f9e2af; }
.local-weather-menu .section.hero { padding: 18px 18px 16px 18px; }
.local-weather-menu .hero-figure { font-family: 'Segoe UI'; font-size: 34px; font-weight: 700; color: #cdd6f4; }
.local-weather-menu .section.hero.coming .hero-figure,
.local-weather-menu .section.hero.coming-now .hero-figure { color: #89dceb; }
.local-weather-menu .hour-bars {
    padding-top: 14px;
    font-family: 'Segoe UI';
    font-size: 10px;
    font-weight: 700;
    -qproperty-labelcolor: #bac2de;
}
.local-weather-menu .sky { -qproperty-leftfade: 75; -qproperty-bottomfade: 35; }
.local-weather-menu .section.days { padding: 14px 18px 14px 18px; }
```

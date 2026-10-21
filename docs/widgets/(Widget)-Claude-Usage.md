# Claude Usage Widget Options

Shows your Claude (Claude Code) subscription usage on the bar - the 5-hour and 7-day
rolling limit utilization - with a popup menu that displays both windows as progress bars
together with their reset times (a countdown plus the exact reset timestamp). Any per-model
weekly cap your plan has (e.g. a separate Fable limit) shows up as an extra bar automatically;
see [Per-model weekly caps](#per-model-weekly-caps).

The data is read from the same OAuth credentials the Claude Code CLI uses
(`~/.claude/.credentials.json`) and fetched from Anthropic's usage endpoint. No API key or
extra configuration is required as long as you are signed in to Claude Code.

## Requirements

What to have in place before you add the widget:

- **Claude Code, signed in with a Claude subscription** (Pro, Max, Team). Run `claude` in a
  terminal and sign in once; the widget reads the sign-in Claude Code keeps, so there is nothing
  to copy into YASB. Without a sign-in the bar shows `--`. See [Authentication](#authentication).
- **Claude Code used now and then.** Only Claude Code renews its sign-in token. After a long
  break the numbers go stale (the `{stale}` glyph) until you run any Claude Code command.
- **For live sessions and Clawd's moods: nothing extra.** Claude Code records every running
  session in `<config dir>\sessions\<pid>.json`, as *busy* while it works and *waiting* while a
  permission prompt or a question waits for you, and the widget reads those files. Every
  `~/.claude*` folder is watched, so a second account under `CLAUDE_CONFIG_DIR` (for example
  `~/.claude-personal`) is counted too.
- **For live weather behind Clawd (optional):** your latitude and longitude, and internet access
  to Open-Meteo (or met.no, its fallback). No key is needed.
- **For token history (optional): nothing extra.** It reads Claude Code's local transcripts.

## Quick start

1. Add the widget to the `widgets` section of `config.yaml`:

    ```yaml
    claude_usage:
      type: "yasb.claude_usage.ClaudeUsageWidget"
      options:
        label: "Claude {five_hour_value}% {mode}"
        label_alt: "Claude 7d {seven_day_value}% {mode}"
    ```

2. Put it on a bar, for example `widgets: right: ["claude_usage"]` under your bar in `bars`.
3. Save. YASB reloads by itself while `watch_config` is on (the default). The label shows `--`
   for a few seconds until the first reading arrives.

To add Clawd, the live sessions, the hearts, the footer and the sky, turn each one on. The
`{sessions_badge}` placeholder puts the session count on the bar:

```yaml
claude_usage:
  type: "yasb.claude_usage.ClaudeUsageWidget"
  options:
    label: "Claude {five_hour_value}% {mode} <span class='sessions'>{sessions_badge}</span>"
    clawd:
      enabled: true
    sessions:
      enabled: true
    hearts:
      enabled: true
    footer:
      enabled: true
    sky:
      enabled: true
      latitude: 51.5072      # your own coordinates, in decimal degrees
      longitude: -0.1276
```

The [Example Style](#example-style) section has rules for every part of the popup.

## Using the widget

- **Left click** opens the popup: the 5-hour and 7-day windows with their reset times, any
  per-model weekly cap, and the extras you turned on. The pin button in its header keeps it open
  and lets you drag it.
- **Right click** switches the bar text between `label` (5-hour) and `label_alt` (7-day). The
  progress ring, when on, follows it.
- **Middle click** does nothing by default. Set `callbacks.on_middle` to `refresh` (re-fetch
  now) or `toggle_usage_mode` (switch between *used* and *left*).
- **The sessions badge** on the bar: `▶2` means two sessions are working, `?1` means one needs
  you (a permission prompt or a question). It is empty while everything is idle. *Waiting* shows
  a few seconds after a prompt opens, once Claude Code records it.
- **In the popup** the sessions are listed with the ones that need you first (`needs you ·
  permission prompt`). Click Clawd and he does a trick. Clawd and the sky only move while the
  popup is open.

## Options

| Option            | Type    | Default | Description |
|-------------------|---------|---------|-------------|
| `label`           | string  | `'Claude {five_hour}%'` | The format string for the label. Supports the placeholders below. |
| `label_alt`       | string  | `'Claude {seven_day}%'` | The alternative format string, toggled by the `toggle_label` callback. |
| `update_interval` | integer | `60` | How often the label and reset countdown are refreshed, in seconds. Must be between 30 and 3600. |
| `cache_ttl`       | integer | `120` | How long (seconds) a fetched result is cached on disk before the endpoint is queried again (0–3600). The endpoint is rate-limited, so keep this at a sane value. |
| `five_hour_reset_format` | string | `'relative'` | How the 5-hour window's reset line is phrased in the popup: `relative` (`Resets in 4h 11m`) or `absolute` (`Resets on Sat @ 6:00 AM`). |
| `seven_day_reset_format` | string | `'absolute'` | How the 7-day window's reset line is phrased in the popup: `relative` or `absolute`. |
| `reset_show_date` | boolean | `true` | In `absolute` mode, include the month/day (`Resets on Sat, Jun 13 @ 6:00 AM`) so two windows resetting on the same weekday stay distinguishable. |
| `time_format`     | string  | `'12h'` | Clock style for every time the popup renders: `12h` (`6:00 AM`) or `24h` (`18:00`). |
| `reset_datetime_format` | string | `'%m/%d/%Y, %I:%M:%S %p'` | strftime template for the exact reset timestamp under each window. Set `'%Y-%m-%d %H:%M'` to match the `clock` widget. An invalid template falls back to the built-in layout rather than blanking the line. |
| `show_reset_duration` | boolean | `true` | Append the countdown to reset lines phrased absolutely (`Resets on Fri, Sep 18 @ 09:00 · in 4d 8h`), so every window shows both when it lands and how long is left. No effect on relative lines, which are already a countdown. |
| `usage_mode`      | string  | `'used'` | Whether `{*_value}` and the progress bar report the share consumed (`used`) or still available (`remaining`). Flipped at runtime by the `toggle_usage_mode` callback. |
| `mode_label_used` | string  | `'used'` | The word `{mode}` renders while showing consumed. |
| `mode_label_remaining` | string | `'left'` | The word `{mode}` renders while showing remaining. |
| `token_history`   | dict    | `{'enabled': false, ...}` | Optional local token-usage history. See [Token history](#token-history). |
| `status`          | dict    | `{'enabled': false, ...}` | Optional Claude API status indicator. See [API status](#api-status). |
| `progress_bar`    | dict    | `{'enabled': false, ...}` | Optional progress bar on the bar itself. See [Progress bar](#progress-bar). |
| `tooltip`         | boolean | `true` | Whether to show a summary tooltip on hover. |
| `warn_percent`    | integer | `60` | Utilization at which bars, percentages and the ring turn from `low` to `medium` (green to yellow). |
| `crit_percent`    | integer | `85` | Utilization at which they turn `high` (red). Also where Clawd starts sweating. |
| `clawd`           | dict    | `{'enabled': false, 'scale': 1.35}` | Clawd the crab in the popup. See [Clawd, sessions, hearts and footer](#clawd-sessions-hearts-and-footer). |
| `sky`             | dict    | `{'enabled': false, ...}` | The sky behind the 5-hour reading and Clawd: time of day and live weather. See [Clawd, sessions, hearts and footer](#clawd-sessions-hearts-and-footer). |
| `sessions`        | dict    | `{'enabled': false, ...}` | Live Claude Code sessions. See [Clawd, sessions, hearts and footer](#clawd-sessions-hearts-and-footer). |
| `hearts`          | dict    | `{'enabled': false, 'scale': 1.35}` | Pixel hearts in the popup header for what is left of the 5-hour window. |
| `footer`          | dict    | `{'enabled': false, 'show_plan': true, 'stale_after': 0}` | Closing line with plan, account and data freshness. |
| `callbacks`       | dict    | [See below](#callbacks) | Mouse-click callbacks. |
| `menu`            | dict    | [See below](#menu-options) | Popup menu settings. |
| `keybindings`     | list    | `[]` | Optional hotkeys. See [Keybindings](./Keybindings). |

## Callbacks

The `callbacks` option maps mouse buttons (`on_left`, `on_middle`, `on_right`) to actions. All keys are optional, the values shown are the defaults.

```yaml
callbacks:
  on_left: "toggle_menu"
  on_middle: "do_nothing"
  on_right: "toggle_label"
```

Available actions:

- `toggle_label` - Switch between `label` and `label_alt`.
- `toggle_menu` - Open or close the usage menu.
- `toggle_usage_mode` - Flip `{*_value}` and the progress bar between consumed and remaining.
- `refresh` - Fetch the usage again now, bypassing `cache_ttl`.
- `do_nothing` - Do nothing.
- `exec <command>` - Run a command, for example `exec cmd.exe /c start ms-settings:network`.

## Menu Options

The `menu` option accepts the following keys. All keys are optional, the values shown are the defaults.

```yaml
menu:
  icon: ""
  blur: true
  round_corners: true
  round_corners_type: "normal"
  border_color: "System"
  alignment: "right"
  direction: "down"
  offset_top: 6
  offset_left: 0
  pin_icon: "\ue718"
  unpin_icon: "\ue77a"
```

## Placeholders

The label is plain text by default. You can prepend a Nerd Font glyph in a `<span>` if you
want an icon (e.g. `<span>\U000f06a9</span> {five_hour}%`), or embed your own image with an
`<img>` tag (e.g. `<img src='C:/path/to/claude.svg' width='14' height='14'> {five_hour}%`). The
following placeholders can be used in `label` / `label_alt`:

- `{five_hour}` - 5-hour window utilization (percent, `--` when unavailable).
- `{seven_day}` - 7-day window utilization (percent, `--` when unavailable).
- `{five_hour_used}` / `{seven_day_used}` - the same numbers under an explicit name.
- `{five_hour_remaining}` / `{seven_day_remaining}` - the complement, i.e. how much of the
  window is still available. Clamped at zero, since the endpoint can report over 100%.
- `{five_hour_value}` / `{seven_day_value}` - whichever of the two pairs above `usage_mode`
  currently selects. These are the ones the `toggle_usage_mode` callback flips.
- `{mode}` - the word for the current mode (`mode_label_used` / `mode_label_remaining`), so a
  label like `{five_hour_value}% {mode}` reads `30% used` or `70% left` and is never ambiguous.
- `{five_hour_reset}` - time until the 5-hour window resets. Shown as a countdown when under a
  day away (e.g. `4h 27m`), otherwise as a local weekday + time (e.g. `Sat 6:00 AM`).
- `{seven_day_reset}` - time until the 7-day window resets (e.g. `Sat 6:00 AM`).
- `{stale}` - a warning glyph shown only while Claude Code's OAuth token has expired, empty
  otherwise. Place it in its own `<span>` (e.g. `{five_hour}% <span class='stale'>{stale}</span>`).
- `{session_tokens}` `{today_tokens}` `{week_tokens}` `{month_tokens}` `{year_tokens}` - compact
  token totals (e.g. `1.2M`) for each period. Require `token_history.enabled`; `--` otherwise.
- `{status}` - a status dot, coloured by the current Claude API status level via
  `.status.<none|minor|major|critical>` classes. Place it in its own `<span>`. Requires
  `status.enabled`; empty otherwise.
- `{status_text}` - the status description (e.g. `All Systems Operational`).
- `{sessions_badge}` - working and waiting Claude Code sessions in one compact string (e.g.
  `▶2 ?1`), empty when nothing is working or waiting. Its label gets a `.working` / `.waiting` /
  `.idle` class for the most pressing state, so place it in its own `<span>`. Requires
  `sessions.enabled` or `clawd.enabled`.
- `{sessions_total}` `{sessions_working}` `{sessions_waiting}` `{sessions_idle}` - the counts.
- `{hearts}` - the 5-hour hearts as Nerd Font glyphs (full / half / empty heart).

Labels containing `{five_hour...}` or `{hearts}` also get a `.low` / `.medium` / `.high` class
from `warn_percent` / `crit_percent`.

```yaml
claude_usage:
  type: "yasb.claude_usage.ClaudeUsageWidget"
  options:
    label: "Claude {five_hour}% · {five_hour_reset}"
    label_alt: "Claude 7d {seven_day}% · {seven_day_reset}"
    update_interval: 60
    cache_ttl: 120
    callbacks:
      on_left: "toggle_menu"    # open the usage menu
      on_middle: "refresh"      # force an immediate re-fetch, bypassing cache_ttl
      on_right: "toggle_label"  # switch the bar text between 5h and 7d
    menu:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: "System"
      alignment: "right"
      direction: "down"
      offset_top: 6
      offset_left: 0
      icon: "C:/Users/you/.config/yasb/assets/claude.png"
```

## Description of Options

- **label:** The format string for the label. Supports the placeholders listed above.
- **label_alt:** The alternative format string, toggled with the `toggle_label` callback.
- **update_interval:** How often the bar label and reset countdown are refreshed, in seconds (30-3600).
- **cache_ttl:** How long a fetched result is cached on disk before the usage endpoint is queried again. Because the endpoint is rate-limited (HTTP 429), the widget serves the last cached value on any error instead of going blank.
- **five_hour_reset_format / seven_day_reset_format:** How each window's reset line is phrased in the popup. `relative` shows a countdown (`Resets in 4h 11m`); `absolute` shows a local weekday and time (`Resets on Sat @ 6:00 AM`). The exact reset timestamp is always shown on the line below.
- **reset_show_date:** In `absolute` mode, include the month/day in the reset line so the 5-hour and 7-day windows can be told apart when they fall on the same weekday. No effect in `relative` mode.
- **time_format:** `12h` or `24h`, applied to every time the popup renders - the reset line, the `{*_reset}` bar placeholders, and the fallback timestamp.
- **reset_datetime_format:** A strftime template for the exact timestamp line under each window. Note the default pads the month and day (`09/18/2026`); use `%Y-%m-%d %H:%M` for an ISO-style line that matches the `clock` widget.
- **show_reset_duration:** Whether an absolute reset line also carries its countdown. With the default `relative`/`absolute` pairing this is what makes the 7-day and per-model windows show a duration at all - otherwise only the 5-hour window does.
- **tooltip:** Whether to show a summary tooltip on hover.
- **keybindings:** A list of global hotkeys for this widget. See [Keybindings](./Keybindings).
- **callbacks:** Mouse event callbacks. See [Callbacks](#callbacks).

> `toggle_label` and `toggle_usage_mode` are independent: the first chooses *which window*
> (5-hour or 7-day), the second chooses *which way round* the number is read. The popup's
> refresh button does the same job as the `refresh` callback, so binding a mouse button to
> `toggle_usage_mode` instead costs you nothing.
- **menu:** A dictionary specifying the popup menu settings:
  - **blur:** Enable blur effect for the menu.
  - **round_corners:** Enable round corners (not supported on Windows 10).
  - **round_corners_type:** Type of round corners (`normal`, `small`).
  - **border_color:** Border color of the menu.
  - **alignment:** Horizontal alignment of the menu (`left`, `right`, `center`).
  - **direction:** Whether the menu opens `down` or `up`.
  - **offset_top / offset_left:** Pixel offsets for fine positioning.
  - **icon:** Path to an image drawn at 22x22 at the left of the popup header, beside the title and account line. Any
    format Qt can read works (PNG, SVG, JPEG). Leave it empty for a header with no mark.
  - **pin_icon / unpin_icon:** Nerd Font glyphs for the pin button in the popup header. The button keeps the popup open and lets it be dragged when pinned.

## Authentication

The widget reuses Claude Code's existing OAuth session. It reads the access token from
`%USERPROFILE%\.claude\.credentials.json` (or `$CLAUDE_CONFIG_DIR\.credentials.json` when
that environment variable is set) and never logs or stores it elsewhere. If you are not
signed in to Claude Code, the widget shows `--` until you sign in.

Only Claude Code itself renews the OAuth token. If it has expired (e.g. you have not used
Claude Code in a while), the usage endpoint rejects the request and the widget keeps serving
the last cached values; the `{stale}` placeholder shows a warning glyph until the token is
refreshed by running any Claude Code command. The `refresh` action forces a re-fetch but
cannot renew an expired token.

## Refresh

The popup header has a refresh button that forces an immediate re-fetch, bypassing `cache_ttl`.
The same action is available as the `refresh` callback for any mouse button. While the menu is
open, its sections redraw in place when fresh data arrives. A refresh is ignored while a fetch
is already in flight.

## Per-model weekly caps

Some plans give one or more models their own weekly cap on top of the shared 5-hour/7-day
windows (e.g. a separate Fable limit). When the usage endpoint reports one, the popup gains an
extra bar for it - titled with the model's name (`Fable Weekly`) - right after the 7-Day
section, using the same progress bar, reset line and `low`/`medium`/`high` colouring as the
built-in windows. There is no config option for this: it is read directly from the API response
and appears or disappears with your plan, so a model added later needs no widget update.

## Token history

When `token_history.enabled` is `true`, the popup gains a **Tokens** section with a
Session / Today / Week / Month / Year toggle, the selected period's total, and an optional
usage graph. The same totals are available on the bar via the `{*_tokens}` placeholders.

The data comes from Claude Code's own session transcripts (`~/.claude/projects/**/*.jsonl`):
no API key and no network. Only numeric token counts, timestamps, the model name and the
session id are read; message content is never touched. The scan is incremental (a file is
re-parsed only when its size or mtime changes) and runs off the UI thread.

```yaml
    token_history:
      enabled: true
      default_period: "today"   # session | today | week | month | year
      show_graph: true
      show_graph_grid: false
      show_models: false
      week_starts_on: "monday"  # monday | sunday
      count_cache_read: true    # false counts only new input/output/cache-creation
      scan_interval: 120        # seconds between transcript scans (30–3600)
```

- **enabled:** (default `false`) Turn the Tokens section and `{*_tokens}` placeholders on.
- **default_period:** (default `today`) Which period is selected when the menu first opens. One of `session`, `today`, `week`, `month`, `year`.
- **show_graph / show_graph_grid:** (both default `false`) Show a usage graph for the selected period, with an optional grid.
- **show_models:** (default `false`) Show a per-model token breakdown in the Tokens section, following the selected period. Top 5 models, computed from local transcripts.
- **week_starts_on:** (default `monday`) First day of the week for the Week total. One of `monday`, `sunday`.
- **count_cache_read:** (default `true`) Whether cache-read tokens count toward the totals. They dominate for heavy users; set `false` for "new work only".
- **scan_interval:** (default `120`) Seconds between transcript scans (30–3600).

> Session is the most recently active session's whole lifetime, so it can span days and may exceed Today.

## API status

When `status.enabled` is `true`, the widget can show a coloured dot reflecting the public
Claude API status (`status.claude.com`, no authentication). Use the `{status}` placeholder on
the bar, and/or an optional status line in the popup header (`show_in_menu`).

```yaml
    status:
      enabled: true
      show_in_menu: true
      icon: "●"           # any glyph; coloured by .status.<level>
      poll_interval: 300  # seconds between status checks (60–3600)
```

- **enabled:** (default `false`) Turn the `{status}`/`{status_text}` placeholders and the menu status line on.
- **show_in_menu:** (default `true`) Show a dot + description line in the popup header.
- **icon:** (default `●`) The glyph used for the dot. Its colour comes from the `.status.<level>` class.
- **poll_interval:** (default `300`) Seconds between status checks (60–3600).

## Progress bar

An optional circular (or linear) progress indicator next to the label, using the same
progress widget as the `cpu`, `gpu` and `codex_usage` widgets. It tracks **whichever window
the label is currently showing** - the 5-hour window by default, switching to the 7-day
window when `toggle_label` is used - so the ring always agrees with the number beside it.

This is *utilization*, so the ring fills up as the window is consumed. (The Codex widget's
bar is the inverse, because that widget reports remaining rather than used.)

```yaml
    progress_bar:
      enabled: true
      progress_type: "circular"   # circular | linear_horizontal | linear_vertical
      position: "left"            # left | right of the label
      size: 16
      thickness: 2
      radius: 3                   # linear types only
      color: "#fab387"            # string, or a list of stops for a gradient
      background_color: "#313244"
      animation: true
```

- **enabled:** Turn the progress bar on. Off by default.
- **progress_type:** `circular` for a ring, or a linear bar in either orientation.
- **position:** Whether the bar is inserted before or after the label.
- **size / thickness:** Pixel dimensions of the ring or bar.
- **radius:** Corner radius, for the linear types only.
- **color:** A single colour, or a list of colours for a gradient.
- **animation:** Animate value changes rather than jumping.
- **level_colors:** Optional `low` / `medium` / `high` colours. When set, the ring switches
  between them at `warn_percent` / `crit_percent` (a traffic light) instead of keeping `color`.

## Clawd, sessions, hearts and footer

A port of the look of [clawd-usage-winwidget](https://github.com/Enhed/clawd-usage-winwidget)
(MIT). Each part is off by default and can be turned on on its own.

```yaml
    warn_percent: 60
    crit_percent: 85
    clawd:
      enabled: true
      scale: 1.35          # size of one of his pixels; 0.6-4.0
    sky:
      enabled: true
      latitude: -6.1783    # decimal degrees; without both, the sky follows the clock only
      longitude: 106.6319
      weather: true        # live weather from Open-Meteo (met.no if blocked); no key
      weather_interval: 900  # seconds between weather fetches (300-86400)
      preview_phase: auto    # or dawn / day / dusk / night, to hold one time of day
      preview_weather: auto  # or clear / partly / overcast / fog / rain / showers / snow / storm ...
    sessions:
      enabled: true
      show_in_menu: true
      max_rows: 6          # rows listed; the rest collapse into "+N more"
      poll_interval: 2     # seconds between registry scans (1-60)
      dirs: []             # Claude config dirs to watch; empty = every ~/.claude* dir
    hearts:
      enabled: true
    footer:
      enabled: true
      show_plan: true
      stale_after: 0       # seconds; 0 = past cache_ttl + 2 x update_interval
```

- **clawd:** Clawd, the crab from Claude Code's welcome screen, lives beside the 5-hour reading
  with the same block-glyph body and click animations. With no session running he burrows into
  the sand and sleeps; with sessions idle he wanders and whistles (and dozes after ten quiet
  minutes); while one works he runs edge to edge; while one waits for you he hops under a `?`;
  near `crit_percent` he sweats, and at 100% he lies legs-up. He jumps when a session finishes
  its reply, celebrates with confetti when the 5-hour window resets, and does a random trick
  when clicked. He animates only while the popup is open.
- **sky:** A faint sky behind the reading and Clawd that fades into the panel at both sides. It
  follows the real sunrise and sunset for `latitude`/`longitude`, worked out locally: night,
  dawn, day and dusk blend into each other, the sun travels an arc and turns orange near the
  horizon, and at night the moon shows its actual phase (mirrored south of the equator) among
  twinkling stars. With `weather` on, clouds drift with the wind, rain slants with it, snow
  sways and settles underfoot, fog crawls past and storms flash now and then. A reading older
  than three hours is dropped rather than shown. Hovering Clawd adds the temperature, the
  weather, the wind and today's sunrise and sunset to his tooltip. The location is never looked
  up by IP: only the coordinates you set are sent, and only to the weather service. It works
  without Clawd too, and animates only while the popup is open. `preview_phase` and
  `preview_weather` hold one look in place, so you can see it without waiting for the weather.
- **sessions:** Live sessions from Claude Code's own registry (`<config dir>/sessions/<pid>.json`).
  A file only counts while its process is alive and started when the file says it did, so a
  closed session never lingers. Every `~/.claude*` directory is scanned by default, so a
  machine running several accounts side by side counts all of them. The popup lists them,
  waiting ones first, under a summary like `4 open · 1 working`.
- **hearts:** Three hearts in the header, tamagotchi-style: every half heart is about 16.7% of
  the 5-hour window left, and they empty only at 100%. They beat when nearly out.
- **footer:** A closing line with the plan (read from `subscriptionType` in
  `.credentials.json` - never the token) and the account, and on the right when the numbers
  last arrived, which turns into `stale · 10:41` once they stop arriving. With the footer on,
  the account moves out of the header into it. Signed out shows in red.

Clawd and the hearts are painted rather than styled, so their colours come from
`-qproperty-*` on `.claude-usage-menu .clawd` (`bodycolor`, `eyecolor`, `fxcolor`, `sandcolor`,
`sweatcolor`, `dustcolor`, `zzzcolor`, `lovecolor`, `soulcolor`, `askcolor`, `cheercolor`,
`notecolor`) and `.claude-usage-menu .header .hearts` (`heartcolor`, `emptycolor`).

The sky keeps the original's palette, and `.claude-usage-menu .sky` tunes it in whole
percentages: `-qproperty-strength` (the gradient, default `100`), `-qproperty-fxopacity` (sun,
moon, clouds and weather, default `70`) and `-qproperty-edgefade` (how much of each side fades
into the panel, default `10`).

> The bar hides itself when the tracked window has no value yet (e.g. before the first
> successful fetch), so it never shows a misleading empty ring.

## Widget Style
```css
.claude-usage {}
.claude-usage .progress-container {}  /* wrapper around the optional progress bar */
.claude-usage .widget-container {}
.claude-usage .icon {}
.claude-usage .label {}
.claude-usage .stale {}              /* warning glyph while the OAuth token is expired */
.claude-usage .status {}             /* {status} dot on the bar */
.claude-usage .status.none {}        /* green / minor / major / critical / unknown */
.claude-usage .status.minor {}
.claude-usage .status.major {}
.claude-usage .status.critical {}
/* Popup menu */
.claude-usage-menu {}
.claude-usage-menu .header {}            /* header row (mark, title stack, buttons) */
.claude-usage-menu .header .app-icon {}  /* product mark, when menu.icon is set */
.claude-usage-menu .header .title-stack {}  /* title and account, stacked */
.claude-usage-menu .header .text {}      /* "Claude Usage" title */
.claude-usage-menu .header .account {}   /* signed-in account e-mail */
.claude-usage-menu .header .refresh {}        /* refresh button */
.claude-usage-menu .header .refresh:hover {}
.claude-usage-menu .status-row {}             /* status line below the header (show_in_menu) */
.claude-usage-menu .status-row .dot {}        /* coloured via .dot.<level> */
.claude-usage-menu .status-row .status-text {}
.claude-usage-menu .section {}                          /* 5-Hour / 7-Day / per-model weekly bars */
.claude-usage-menu .section .title {}
.claude-usage-menu .section .progress {}               /* progress-bar track */
.claude-usage-menu .section .progress .fill {}         /* filled portion */
.claude-usage-menu .section .progress.low .fill {}     /* < 50%  */
.claude-usage-menu .section .progress.medium .fill {}  /* 50-79% */
.claude-usage-menu .section .progress.high .fill {}    /* >= 80% */
.claude-usage-menu .section .footer .reset {}
.claude-usage-menu .section .footer .percent {}
.claude-usage-menu .section .footer .percent.low {}
.claude-usage-menu .section .footer .percent.medium {}
.claude-usage-menu .section .footer .percent.high {}
.claude-usage-menu .section .date {}     /* absolute reset timestamp */
/* Token history section (token_history.enabled) */
.claude-usage-menu .section.tokens {}
.claude-usage-menu .section .period-toggle {}
.claude-usage-menu .section .period-btn {}
.claude-usage-menu .section .period-btn.active {}
.claude-usage-menu .section .token-total {}
.claude-usage-menu .section.tokens .model-usage {}      /* per-model breakdown container */
.claude-usage-menu .section.tokens .model-usage .title {} /* "Models" header */
.claude-usage-menu .section.tokens .model-rows {}       /* the per-model bar rows */
.claude-usage-menu .section.tokens .model-name {}
.claude-usage-menu .section.tokens .model-total {}
.claude-usage-menu .section.tokens .model-rows .progress.model-0 .fill {}  /* bar accent 0..4 */
.claude-usage-menu .section.tokens .model-rows .progress.model-1 .fill {}
.claude-usage-menu .section.tokens .model-rows .progress.model-2 .fill {}
.claude-usage-menu .section.tokens .model-rows .progress.model-3 .fill {}
.claude-usage-menu .section.tokens .model-rows .progress.model-4 .fill {}
.claude-usage-menu .header .pin-btn {}        /* pin button (use font-family "Segoe Fluent Icons" for the glyphs) */
.claude-usage-menu .header .pin-btn.pinned {} /* while pinned */
.claude-usage-menu .section .graph-container {}
```

## Example Style

A full style covering every element, including the optional status, token-history and
per-model rows. Matches the Windows 11 look the rest of the widgets (e.g. `control_center`)
use: a translucent dark panel (pair with `menu.blur: true`), white/grey text hierarchy, a blue
accent, and thin 1px separators between sections instead of boxed cards. Copy/paste and adjust
colours to taste.

```css
/* Bar */
.claude-usage .icon {
    color: rgba(255, 255, 255, 0.9);
    font-size: 16px;
    margin: 1px 4px 0 0;
}
.claude-usage .label {
    color: rgba(255, 255, 255, 0.9);
    padding: 0 2px;
}
.claude-usage .stale {
    color: #ff6b6b;
    margin-left: 4px;
}
.claude-usage .status { margin-right: 4px; }
.claude-usage .status.none { color: #6ccb5f; }
.claude-usage .status.minor { color: #ffc83d; }
.claude-usage .status.major { color: #ff9d42; }
.claude-usage .status.critical { color: #ff6b6b; }
.claude-usage .status.unknown { color: rgba(255, 255, 255, 0.4); }

/* Popup menu */
.claude-usage-menu {
    background: rgba(32, 32, 32, 0.6);
    min-width: 300px;
}
.claude-usage-menu .header {
    padding: 14px 16px 10px 16px;
}
.claude-usage-menu .header .text {
    color: #ffffff;
    font-size: 15px;
    font-weight: 600;
}
.claude-usage-menu .header .app-icon {
    padding-right: 10px;
}
.claude-usage-menu .header .account {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
}
.claude-usage-menu .header .refresh,
.claude-usage-menu .header .pin-btn {
    color: rgba(255, 255, 255, 0.6);
    font-size: 15px;
    padding: 2px 4px;
    margin-left: 4px;
    border-radius: 4px;
    transition: background-color 0.08s, color 0.08s;
}
.claude-usage-menu .header .pin-btn {
    font-family: "Segoe Fluent Icons";
}
.claude-usage-menu .header .refresh:hover,
.claude-usage-menu .header .pin-btn:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.08);
}
.claude-usage-menu .header .pin-btn.pinned { color: #47AFF5; }

/* Optional status line (status.show_in_menu) */
.claude-usage-menu .status-row {
    padding: 0 16px 12px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.claude-usage-menu .status-row .dot { font-size: 10px; margin-right: 8px; }
.claude-usage-menu .status-row .dot.none { color: #6ccb5f; }
.claude-usage-menu .status-row .dot.minor { color: #ffc83d; }
.claude-usage-menu .status-row .dot.major { color: #ff9d42; }
.claude-usage-menu .status-row .dot.critical { color: #ff6b6b; }
.claude-usage-menu .status-row .dot.unknown { color: rgba(255, 255, 255, 0.4); }
.claude-usage-menu .status-row .status-text { color: rgba(255, 255, 255, 0.6); font-size: 12px; }

/* 5-hour / 7-day sections, and any per-model weekly cap bar (e.g. Fable) - all share these rules.
   A thin bottom border separates sections instead of a boxed background, and the last section
   (Tokens when enabled, otherwise the last usage bar) drops it so it doesn't sit flush against
   the popup's rounded bottom edge. */
.claude-usage-menu .section {
    padding: 14px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.claude-usage-menu .section.tokens { border-bottom: none; }
.claude-usage-menu .section .title {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    font-weight: 600;
    padding-bottom: 8px;
}
.claude-usage-menu .progress {
    background-color: rgba(255, 255, 255, 0.08);
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}
/* The bar rests in the product's own colour, so the popup and the bar button that opened
   it read as one thing, then escalates away from it - identity never looks like a warning. */
.claude-usage-menu .progress .fill {
    background-color: #fab387;
    border-radius: 4px;
}
/* Maroon rather than amber: amber sits next to Claude's peach, and a warning you cannot
   tell from the resting colour is not a warning. */
.claude-usage-menu .progress.medium .fill { background-color: #eba0ac; }
.claude-usage-menu .progress.high .fill { background-color: #f38ba8; }
.claude-usage-menu .reset {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    padding-top: 8px;
}
.claude-usage-menu .percent {
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
    padding-top: 8px;
}
.claude-usage-menu .percent.medium { color: #ffc83d; }
.claude-usage-menu .percent.high { color: #ff6b6b; }
.claude-usage-menu .date {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    padding-top: 2px;
}

/* Token history (token_history.enabled) */
.claude-usage-menu .section .period-toggle { padding-bottom: 10px; }
.claude-usage-menu .section .period-btn {
    color: rgba(255, 255, 255, 0.6);
    background-color: rgba(255, 255, 255, 0.06);
    border: none;
    border-radius: 4px;
    /* No left padding so the first button lines up with the 16px edge; spacing is on the right. */
    padding: 4px 12px 4px 0;
    font-size: 12px;
}
.claude-usage-menu .section .period-btn.active {
    color: #000000;
    background-color: #47AFF5;
    font-weight: 600;
}
.claude-usage-menu .section .token-total {
    color: #ffffff;
    font-size: 20px;
    font-weight: 600;
    padding: 2px 0 8px 0;
}
.claude-usage-menu .section .graph-container { min-height: 60px; }

/* Per-model breakdown (token_history.show_models). The name and total columns are
   given a min-width so the bar column stretches to fill the remaining space. */
.claude-usage-menu .section.tokens .model-usage { padding-bottom: 12px; }
.claude-usage-menu .section.tokens .model-usage .title { color: rgba(255, 255, 255, 0.6); }
.claude-usage-menu .section.tokens .model-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    min-width: 90px;
}
.claude-usage-menu .section.tokens .model-total {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    min-width: 48px;
}
.claude-usage-menu .section.tokens .model-rows .progress {
    min-height: 6px;
    max-height: 6px;
}
.claude-usage-menu .section.tokens .model-rows .progress.model-0 .fill { background-color: #47AFF5; }
.claude-usage-menu .section.tokens .model-rows .progress.model-1 .fill { background-color: #b48ce0; }
.claude-usage-menu .section.tokens .model-rows .progress.model-2 .fill { background-color: #6ccb5f; }
.claude-usage-menu .section.tokens .model-rows .progress.model-3 .fill { background-color: #ffc83d; }
.claude-usage-menu .section.tokens .model-rows .progress.model-4 .fill { background-color: #ff9d42; }
```

## Preview of the Widget
![Claude Usage YASB Widget](assets/9ab87198-c31d-44a7-b36f-7cb2cf8b0530.png)

## Troubleshooting

**The bar shows `--`.**
No sign-in was found. Run `claude` in a terminal and sign in with your Claude subscription (or
`/login` inside it), then wait for the next refresh. If you keep Claude Code's files somewhere
other than `~/.claude`, start YASB with `CLAUDE_CONFIG_DIR` pointing there.

**A warning glyph (`{stale}`) sits next to the numbers.**
Claude Code's sign-in token has expired, and only Claude Code can renew it. Run any Claude Code
command; the widget picks the fresh token up at its next fetch.

**The numbers stop changing for a while.**
The usage endpoint is rate-limited. On an error the widget keeps showing the last cached values
instead of going blank. Keep `cache_ttl` at 120 seconds or more.

**No sessions are listed.**
Turn on `sessions` (or `clawd`, which reads the sessions too). Check that your Claude config
folder has a `sessions` folder with `<pid>.json` files while Claude Code runs. A config folder
whose name does not start with `.claude` in your home folder has to be listed in `sessions.dirs`.
A Claude Code started from inside another Claude Code session (it inherits
`CLAUDE_CODE_CHILD_SESSION`) writes no session file, so it is not counted.

**A prompt is open but the badge shows no `?`.**
Give it a few seconds: Claude Code records *waiting* shortly after the prompt opens, and the
widget reads the files every `sessions.poll_interval` seconds (2 by default).

**Clawd or the sky stands still.**
They only move while the popup is open, which keeps the bar light.

**The sky shows no weather.**
Set both `latitude` and `longitude` and leave `weather` on. The weather comes from
`api.open-meteo.com`, or `api.met.no` when that fails, so a firewall that blocks both leaves the
sky following the clock only.


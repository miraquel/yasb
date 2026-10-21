# Codex Usage Widget

Display the remaining percentage in the rate-limit windows reported by the Codex CLI. The
widget uses Codex's app-server protocol, so it never reads `~/.codex/auth.json`, copies access
tokens, or calls a private web endpoint. Fetching runs in a background thread and the last
normalized result is cached when Codex is temporarily unavailable.

## Requirements

- A recent Codex CLI available in `PATH` (or configured with `codex_path`).
- A ChatGPT-backed Codex login. Run `codex login` once if Codex is not already signed in.
- **For live sessions and the pet's moods: nothing extra.** Codex keeps a lock for every open
  chat in `~/.codex/thread-writer-locks` and its turn history in its own databases, and the
  widget reads them read-only.
- **For the `?` when Codex waits for your approval (optional):** a small Codex hook that ships
  with YASB, added to `~/.codex/config.toml` and trusted once in Codex. It needs a Codex version
  with hooks (on by default in recent versions) and YASB installed in its default folder, or the
  script path changed to match. See [Waiting for approval](#waiting-for-approval-optional).
- **For live weather behind the pet (optional):** your latitude and longitude, and internet
  access to Open-Meteo (or met.no). No key is needed.

The widget reuses the login managed by Codex itself. No additional login is needed on a machine
where the CLI already works. API-key-only authentication may not expose ChatGPT subscription
rate limits.

![Codex Usage widget in the YASB bar](assets/5c5e8e22-f3da-4de7-b811-dbf41e87f5ba.png)

## Quick start

1. Add the widget to the `widgets` section of `config.yaml`:

    ```yaml
    codex_usage:
      type: "yasb.codex_usage.CodexUsageWidget"
      options:
        label: "Codex {primary_value}% {mode}"
        label_alt: "Codex {secondary_window} {secondary_value}% {mode}"
    ```

2. Put it on a bar, for example `widgets: right: ["codex_usage"]` under your bar in `bars`.
3. Save. YASB reloads by itself while `watch_config` is on (the default). The label shows `--`
   until Codex answers the first request.

To add the pet, the live sessions, the hearts, the footer and the sky, turn each one on. The
`{sessions_badge}` placeholder puts the session count on the bar:

```yaml
codex_usage:
  type: "yasb.codex_usage.CodexUsageWidget"
  options:
    label: "Codex {primary_value}% {mode} <span class='sessions'>{sessions_badge}</span>"
    pet:
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

Then, if you want the `?` while Codex asks for approval, add the hook as described in
[Waiting for approval](#waiting-for-approval-optional).

## Using the widget

- **Left click** opens the popup: the rate-limit windows with their reset times, the extras you
  turned on, and tabs for Overview, Resets, Models and Activity. Left click again to close it.
- **Right click** switches the bar text between `label` and `label_alt` (the main window and
  the second one). The progress bar follows it.
- **Middle click** refreshes now, without opening the popup.
- **The sessions badge** on the bar: `▶2` means two chats are working, `?1` means one is waiting
  for your approval (with the hook in place). It is empty while everything is idle.
- **In the popup** the sessions are listed with the ones that wait first (`needs you · <tool>`),
  each with the app that started it. Click the pet and it waves. The pet and the sky only move
  while the popup is open.

## Example Configuration

```yaml
codex_usage:
  type: "yasb.codex_usage.CodexUsageWidget"
  options:
    label: "Codex {primary_remaining}%"
    label_alt: "Codex {secondary_window} {secondary_remaining}%"
    update_interval: 60
    cache_ttl: 120
    timeout: 15
    show_token_usage: true
    stale_icon: "⚠"
    progress_bar:
      enabled: true
      progress_type: "linear_horizontal"
      size: 36
      thickness: 6
      radius: 3
      color: "#4caf50"
      background_color: "#3c3c3c"
      position: "left"
      animation: true
    callbacks:
      on_left: "toggle_menu"
      on_middle: "refresh"
      on_right: "toggle_label"
    menu:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: "System"
      alignment: "right"
      direction: "down"
      offset_top: 6
      offset_left: 0
      icon: "C:/Users/you/.config/yasb/assets/openai.png"
      show_overview: true
      show_models: true
      show_activity: true
      show_resets: true
      show_details: true
      refresh_icon: "\uE72C"
      previous_page_icon: "\uE76B"
      next_page_icon: "\uE76C"
```

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `label` | string | `Codex {primary_remaining}%` | Primary label template. |
| `label_alt` | string | `Codex {secondary_window} {secondary_remaining}%` | Alternate label shown by `toggle_label`. |
| `codex_path` | string | `codex` | Codex executable name or full path. |
| `update_interval` | integer | `60` | Refresh timer in seconds (30-3600). |
| `cache_ttl` | integer | `120` | Fresh-cache lifetime in seconds (0-3600). |
| `timeout` | number | `15` | app-server response timeout in seconds (1-60). |
| `tooltip` | boolean | `true` | Show remaining/used details on hover. |
| `show_token_usage` | boolean | `true` | Aggregate local session token metadata for the model chart and monthly heatmap. |
| `stale_icon` | string | `⚠` | Warning icon used by the `{stale}` placeholder. |
| `usage_mode` | string | `remaining` | Whether `{*_value}` and the progress bar report the share still available (`remaining`) or consumed (`used`). Flipped at runtime by the `toggle_usage_mode` callback. Note the Claude widget defaults to `used`, so set both explicitly if you run them side by side. |
| `mode_label_used` | string | `used` | The word `{mode}` renders while showing consumed. |
| `mode_label_remaining` | string | `left` | The word `{mode}` renders while showing remaining. |
| `warn_percent` | integer | `50` | Share used from which the bars, percentages and ring turn from good to low (1-100). |
| `crit_percent` | integer | `80` | Share used from which they turn critical (1-100). The defaults keep the original split: 50% and 20% left. |
| `pet` | dictionary | `{'enabled': false, 'scale': 1.35}` | The Codex pet in the popup. See [Pet, sessions, hearts and footer](#pet-sessions-hearts-and-footer). |
| `sky` | dictionary | `{'enabled': false, ...}` | The sky behind the main reading and the pet, with the Claude widget's options. See [Pet, sessions, hearts and footer](#pet-sessions-hearts-and-footer). |
| `sessions` | dictionary | `{'enabled': false, ...}` | Live Codex sessions. See [Pet, sessions, hearts and footer](#pet-sessions-hearts-and-footer). |
| `hearts` | dictionary | `{'enabled': false, 'scale': 1.35}` | Pixel hearts in the popup header. See [Pet, sessions, hearts and footer](#pet-sessions-hearts-and-footer). |
| `footer` | dictionary | `{'enabled': false, ...}` | Plan, account and freshness line closing the popup. See [Pet, sessions, hearts and footer](#pet-sessions-hearts-and-footer). |
| `progress_bar` | dictionary | [See below](#example-configuration) | Native bar indicator showing the active window's remaining percentage. |
| `keybindings` | list | `[]` | Optional hotkeys. See [Keybindings](./Keybindings). |
| `callbacks` | dictionary | [See below](#callbacks) | Mouse actions. |
| `menu` | dictionary | [See below](#example-configuration) | Popup position, appearance, section visibility, and Fluent navigation icons. `icon` takes a path to an image drawn at 22x22 at the left of the popup header, beside the title and account line; any format Qt can read works, and an empty value leaves the header unmarked. |

The progress bar supports `circular`, `linear_horizontal`, and `linear_vertical`. `color` may be
a single color or a list of gradient colors. Right-click toggles the active label/window, and
the progress bar follows it. Set `progress_bar.level_colors` (`low`, `medium`, `high`, as on the
Claude widget) to recolour the ring by `warn_percent` / `crit_percent` instead: `low` while under
warn, `medium` from warn, `high` from crit, always from the share used.

## Callbacks

The `callbacks` option maps mouse buttons (`on_left`, `on_middle`, `on_right`) to actions. All keys are optional, the values shown are the defaults.

```yaml
callbacks:
  on_left: "toggle_menu"
  on_middle: "refresh"
  on_right: "toggle_label"
```

Available actions:

- `toggle_label` - Switch between `label` and `label_alt`.
- `toggle_menu` - Open or close the details popup.
- `toggle_usage_mode` - Flip `{*_value}` and the progress bar between remaining and consumed.
- `refresh` - Refresh the usage now, without opening the popup.
- `do_nothing` - Do nothing.
- `exec <command>` - Run a command, for example `exec cmd.exe /c start ms-settings:network`.

## Details Popup

Left-click the widget to open a compact details window. The header and available rate-limit
windows stay visible. Below them a tab strip names every available page, and the area under it
shows one at a time, sized to the page on screen:

- **Overview** - token totals for today, 7 days, 30 days, and one year, plus optional plan,
  credits, updated time, live/cached status, and cached errors;
- **Resets** - available account usage-limit resets and their expiration dates;
- **Models** - the 30-day model breakdown when model data is available;
- **Activity** - the monthly heatmap and its existing month navigation.

Click a tab to switch pages. The active page is retained while the persistent popup is reused.
The tab strip is hidden when only one page is available. Pages without valid token data are
omitted, and disabling every optional page leaves the fixed rate-limit sections working
normally.

> Earlier versions paged with previous/next arrows and a `Models · 3 / 4` counter. The tabs
> replaced both, so `menu.previous_page_icon` and `menu.next_page_icon` are no longer used;
> they remain accepted in config so existing setups keep validating.

The `menu` section switches control the lower area:

- `show_overview` shows token totals in the Overview page;
- `show_details` shows account and freshness details in the Overview page. If token totals are
  disabled but details are enabled, this page is labelled **Details**;
- `show_resets` shows the Resets page when the Codex CLI reports reset-credit metadata;
- `show_models` and `show_activity` control their respective pages.

`show_token_usage: false` remains the global switch for local token scanning. It hides token
totals, Models, and Activity without affecting rate limits or the optional account details.

Left-click again to close it. The middle-click `refresh` callback also refreshes without opening
the window. Accounts without a secondary limit simply omit that section.

![Codex Usage details popup](assets/8edf52ee-eec2-4e8f-9fec-3b84accb5f81.png)

## Refresh Feedback

Clicking the Fluent refresh button starts a rotating animation and displays `Refreshing…` in
the popup header. When the request finishes, the header briefly shows `Refresh successful` or
`Refresh failed`. The button is disabled while a refresh is running to prevent duplicate
requests. The middle-click callback still refreshes silently when the popup is closed.

Token statistics are calculated from `token_count` metadata in the current user's local Codex
session history. The scanner does not parse or retain prompt/response text, never opens
`auth.json`, and uploads nothing. Set `show_token_usage: false` to disable local history scanning
and hide these sections.

The monthly heatmap opens on the current month and can navigate across the current and previous
11 months. Months earlier than the first locally available Codex token record remain selectable
but are marked as unavailable rather than incorrectly displayed as zero usage.

## Placeholders

- `{primary_remaining}` / `{secondary_remaining}` - percentage remaining.
- `{primary_value}` / `{secondary_value}` - whichever of remaining/used `usage_mode` currently
  selects. These are the ones the `toggle_usage_mode` callback flips.
- `{mode}` - the word for the current mode (`mode_label_used` / `mode_label_remaining`), so a
  label like `{primary_value}% {mode}` reads `97% left` or `3% used` and is never ambiguous.
- `{primary_used}` / `{secondary_used}` - percentage already used.
- `{primary_window}` / `{secondary_window}` - duration reported by Codex, such as `5h`, `7d`, or `1w`.
- `{primary_reset}` / `{secondary_reset}` - time until reset.
- `{plan}` - account plan reported by Codex.
- `{credits}` - available credit balance, when present.
- `{stale}` - warning glyph when the last refresh failed and cached data is displayed.
- `{sessions_badge}` - working and waiting Codex sessions in one compact string (e.g. `▶2 ?1`),
  empty when nothing is working or waiting. Its label gets a `.working` / `.waiting` / `.idle`
  class for the most pressing state, so place it in its own `<span>`. Requires
  `sessions.enabled`.
- `{sessions_total}` `{sessions_working}` `{sessions_waiting}` `{sessions_idle}` - the counts.

Window names are deliberately derived from `windowDurationMins` instead of assuming that every
account has a 5-hour and weekly limit. Missing secondary limits render as `--` and are omitted
from the popup.

## Widget Style

```css
.codex-usage {}
.codex-usage .widget-container {}
.codex-usage .label {}
.codex-usage .progress-container {}

/* Popup menu */
.codex-usage-menu {}
.codex-usage-menu .header {}
.codex-usage-menu .header .app-icon {}      /* product mark, when menu.icon is set */
.codex-usage-menu .header .title-stack {}   /* title and account, stacked */
.codex-usage-menu .header .text {}
.codex-usage-menu .header .account {}       /* signed-in account e-mail */
.codex-usage-menu .header .refresh-status {}
.codex-usage-menu .header .refresh-status.busy {}
.codex-usage-menu .header .refresh-status.success {}
.codex-usage-menu .header .refresh-status.error {}
.codex-usage-menu .header .refresh {} /* Segoe Fluent Icons Refresh glyph */
.codex-usage-menu .header .refresh:hover {}
.codex-usage-menu .section {}
.codex-usage-menu .section .title {}
.codex-usage-menu .section .progress {}
.codex-usage-menu .section .progress .fill {}
.codex-usage-menu .section .progress.low .fill {}
.codex-usage-menu .section .progress.critical .fill {}
.codex-usage-menu .section .stats {}
.codex-usage-menu .section .used {}
.codex-usage-menu .section .remaining {}
.codex-usage-menu .section .remaining.good {}
.codex-usage-menu .section .remaining.low {}
.codex-usage-menu .section .remaining.critical {}
.codex-usage-menu .section .timing {}
.codex-usage-menu .section .reset {}
.codex-usage-menu .section .date {}
.codex-usage-menu .pager {}
.codex-usage-menu .page-tabs {}          /* the tab strip */
.codex-usage-menu .page-tab {}           /* one tab per available page */
.codex-usage-menu .page-tab:hover {}
.codex-usage-menu .page-tab.active {}    /* the page currently shown */
.codex-usage-menu .section-scope {}      /* e.g. "Last 30 days" beside a heading */
.codex-usage-menu .page-stack {}
.codex-usage-menu .page {}
.codex-usage-menu .empty-state {}
.codex-usage-menu .overview-tokens {}
.codex-usage-menu .reset-credits-header {}
.codex-usage-menu .reset-credits-count {}
.codex-usage-menu .reset-credit-card {}
.codex-usage-menu .reset-credit-title {}
.codex-usage-menu .reset-credit-expiration {}
.codex-usage-menu .models {}
.codex-usage-menu .section-title {}
.codex-usage-menu .model-row {}
.codex-usage-menu .model-name {}
.codex-usage-menu .model-value {}
.codex-usage-menu .model-bar {}
.codex-usage-menu .model-bar .fill {}
.codex-usage-menu .period-name {}
.codex-usage-menu .period-value {}
.codex-usage-menu .activity {}
.codex-usage-menu .activity-title {}
.codex-usage-menu .month-label {}
.codex-usage-menu .month-nav {}
.codex-usage-menu .month-nav:hover {}
.codex-usage-menu .heatmap .weekday {}
.codex-usage-menu .history-note {}
.codex-usage-menu .heatmap .cell {}
.codex-usage-menu .heatmap .cell.level-1 {}
.codex-usage-menu .heatmap .cell.level-2 {}
.codex-usage-menu .heatmap .cell.level-3 {}
.codex-usage-menu .heatmap .cell.level-4 {}
.codex-usage-menu .heatmap .cell.unavailable {}
.codex-usage-menu .details {}
.codex-usage-menu .details .name {}
.codex-usage-menu .details .value {}
.codex-usage-menu .details .status.live {}
.codex-usage-menu .details .status.stale {}
.codex-usage-menu .details .error {}
```

`menu.refresh_icon` defaults to the matching
**Segoe Fluent Icons** glyph and can be replaced without changing the Widget code. This font is
included with Windows 11; Windows 10 users may need to install it as described in the YASB
installation guide.

## Example Style

This complete default follows the Windows 11 styling used by the Claude Usage widget. It uses
readable Segoe UI sizes, compact Fluent controls, and thin separators instead of boxed cards.
Qt scales these logical pixel sizes with the active Windows display scale. The colors indicate
**remaining** capacity: green is healthy, amber is low, and red is critical.

```css
/* Bar */
.codex-usage .label {
    color: rgba(255, 255, 255, 0.9);
    font-size: 12px;
    font-weight: 500;
    padding-left: 5px;
}
.codex-usage .progress-container { margin-left: 3px; }

/* Popup menu */
.codex-usage-menu {
    background-color: rgba(32, 32, 32, 0.68);
    font-family: "Segoe UI";
    min-width: 340px;
}
.codex-usage-menu .header {
    padding: 9px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.codex-usage-menu .header .text {
    color: #ffffff;
    font-size: 16px;
    font-weight: 600;
}
.codex-usage-menu .header .app-icon {
    padding-right: 10px;
}
.codex-usage-menu .header .account {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
}
.codex-usage-menu .header .refresh-status {
    color: rgba(255, 255, 255, 0.62);
    font-size: 12px;
    padding-right: 6px;
}
.codex-usage-menu .header .refresh-status.busy { color: rgba(255, 255, 255, 0.72); }
.codex-usage-menu .header .refresh-status.success { color: #6ccb5f; }
.codex-usage-menu .header .refresh-status.error { color: #ff6b6b; }
.codex-usage-menu .header .refresh {
    font-family: "Segoe Fluent Icons";
    color: rgba(255, 255, 255, 0.72);
    background-color: transparent;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    margin: 0;
}
.codex-usage-menu .header .refresh:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.1);
}
.codex-usage-menu .section {
    padding: 8px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.codex-usage-menu .section .title {
    color: rgba(255, 255, 255, 0.7);
    font-size: 13px;
    font-weight: 600;
    padding-bottom: 6px;
}
.codex-usage-menu .section .progress {
    background-color: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}
/* The bar rests in the product's own colour, so the popup and the bar button that opened
   it read as one thing, then escalates away from it - identity never looks like a warning. */
.codex-usage-menu .section .progress .fill {
    background-color: #94e2d5;
    border-radius: 4px;
}
.codex-usage-menu .section .progress.good .fill { background-color: #94e2d5; }
.codex-usage-menu .section .progress.low .fill { background-color: #f9e2af; }
.codex-usage-menu .section .progress.critical .fill { background-color: #f38ba8; }
.codex-usage-menu .section .stats { padding-top: 7px; }
.codex-usage-menu .section .used {
    color: rgba(255, 255, 255, 0.62);
    font-size: 12px;
}
.codex-usage-menu .section .remaining {
    color: #ffffff;
    font-size: 14px;
    font-weight: 600;
}
.codex-usage-menu .section .remaining.good { color: #94e2d5; }
.codex-usage-menu .section .remaining.low { color: #ffc83d; }
.codex-usage-menu .section .remaining.critical { color: #ff6b6b; }
.codex-usage-menu .section .timing { padding-top: 6px; }
.codex-usage-menu .section .reset {
    color: rgba(255, 255, 255, 0.68);
    font-size: 12px;
}
.codex-usage-menu .section .date {
    color: rgba(255, 255, 255, 0.48);
    font-size: 12px;
}

/* Tab strip and page area */
.codex-usage-menu .pager { background-color: transparent; }
.codex-usage-menu .page-tabs {
    padding: 8px 0 12px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.codex-usage-menu .page-tab {
    font-family: 'Segoe UI';
    font-size: 11px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.55);
    background-color: transparent;
    border: none;
    border-radius: 7px;
    padding: 4px 10px;
}
.codex-usage-menu .page-tab:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.08);
}
.codex-usage-menu .page-tab.active {
    color: #1b1b1b;
    background-color: #47AFF5;
}
.codex-usage-menu .section-scope {
    color: rgba(255, 255, 255, 0.45);
    font-size: 10px;
}
.codex-usage-menu .month-nav {
    font-family: "Segoe Fluent Icons";
    color: rgba(255, 255, 255, 0.68);
    background-color: transparent;
    border: none;
    border-radius: 4px;
    font-size: 12px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0;
}
.codex-usage-menu .month-nav:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.08);
}
.codex-usage-menu .month-nav:disabled {
    color: rgba(255, 255, 255, 0.22);
}
.codex-usage-menu .page-stack { background-color: transparent; }
.codex-usage-menu .page { padding: 12px 16px; }
.codex-usage-menu .empty-state {
    color: rgba(255, 255, 255, 0.55);
    font-size: 12px;
    padding: 18px 0;
}

/* Overview page */
.codex-usage-menu .overview-tokens { padding-bottom: 12px; }
.codex-usage-menu .section-title,
.codex-usage-menu .activity-title {
    color: rgba(255, 255, 255, 0.68);
    font-size: 12px;
    font-weight: 600;
}
.codex-usage-menu .section-title { padding-bottom: 8px; }
.codex-usage-menu .periods { padding-bottom: 4px; }
.codex-usage-menu .period-name {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
}
.codex-usage-menu .period-value {
    color: #ffffff;
    font-size: 16px;
    font-weight: 600;
}
.codex-usage-menu .details {
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.codex-usage-menu .details .name {
    color: rgba(255, 255, 255, 0.56);
    font-size: 12px;
}
.codex-usage-menu .details .value {
    color: rgba(255, 255, 255, 0.9);
    font-size: 12px;
}
.codex-usage-menu .details .status.live { color: #6ccb5f; }
.codex-usage-menu .details .status.stale { color: #ffc83d; }
.codex-usage-menu .details .error {
    color: #ff6b6b;
    font-size: 11px;
    max-height: 30px;
    padding-top: 5px;
}

/* Usage-limit reset credits page */
.codex-usage-menu .reset-credits-count {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
}
.codex-usage-menu .reset-credit-card {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 5px;
    min-height: 44px;
    max-height: 44px;
    padding: 6px 10px;
}
.codex-usage-menu .reset-credit-title {
    color: rgba(255, 255, 255, 0.9);
    font-size: 12px;
    font-weight: 600;
}
.codex-usage-menu .reset-credit-expiration {
    color: rgba(255, 255, 255, 0.52);
    font-size: 11px;
}

/* Models page */
.codex-usage-menu .model-row {
    min-height: 27px;
    max-height: 27px;
}
.codex-usage-menu .model-name {
    color: rgba(255, 255, 255, 0.82);
    font-size: 12px;
    min-width: 96px;
    max-width: 96px;
}
.codex-usage-menu .model-value {
    color: rgba(255, 255, 255, 0.65);
    font-size: 12px;
    min-width: 52px;
    max-width: 52px;
}
.codex-usage-menu .model-bar {
    background-color: rgba(255, 255, 255, 0.11);
    border-radius: 3px;
    min-height: 7px;
    max-height: 7px;
}
.codex-usage-menu .model-bar .fill { background-color: #7d88e8; border-radius: 3px; }
.codex-usage-menu .row-2 .model-bar .fill { background-color: #b87ae7; }
.codex-usage-menu .row-3 .model-bar .fill { background-color: #e49ada; }
.codex-usage-menu .row-4 .model-bar .fill { background-color: #7eb5e8; }
.codex-usage-menu .row-5 .model-bar .fill { background-color: #7bc7a4; }

/* Activity page */
.codex-usage-menu .activity-header { padding-bottom: 7px; }
.codex-usage-menu .month-label {
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    min-width: 106px;
    max-width: 106px;
}
.codex-usage-menu .heatmap .weekday {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    min-width: 20px;
    max-width: 20px;
    padding-bottom: 2px;
}
.codex-usage-menu .history-note {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    padding-top: 6px;
}
.codex-usage-menu .heatmap .cell {
    background-color: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
}
.codex-usage-menu .heatmap .cell.level-1 { background-color: #244f2b; }
.codex-usage-menu .heatmap .cell.level-2 { background-color: #34713b; }
.codex-usage-menu .heatmap .cell.level-3 { background-color: #50a653; }
.codex-usage-menu .heatmap .cell.level-4 { background-color: #79d677; }
.codex-usage-menu .heatmap .cell.future,
.codex-usage-menu .heatmap .cell.outside { background-color: transparent; }
.codex-usage-menu .heatmap .cell.unavailable {
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.08);
}
```

## Pet, sessions, hearts and footer

The same extras as the Claude widget's Clawd section, for Codex. Each part is off by default and
can be turned on on its own.

```yaml
    warn_percent: 60
    crit_percent: 85
    pet:
      enabled: true
      scale: 1.35          # size of one of its pixels, on Clawd's scale; 0.6-4.0
    sky:
      enabled: true
      latitude: -6.1783    # decimal degrees; without both, the sky follows the clock only
      longitude: 106.6319
      weather: true        # live weather from Open-Meteo (met.no if blocked); no key
    sessions:
      enabled: true
      show_in_menu: true
      max_rows: 6          # rows listed; the rest collapse into "+N more"
      poll_interval: 2     # seconds between reads (1-60)
      idle_minutes: 30     # an idle chat counts while its last turn is this recent (1-1440)
    hearts:
      enabled: true
    footer:
      enabled: true
      show_plan: true
      stale_after: 0       # seconds; 0 = past cache_ttl + 2 x update_interval
```

- **pet:** The default Codex pet - a blue cloud whose face is a little screen showing `>_` -
  redrawn by hand in pixels at Clawd's width, lives beside the main reading. With no Codex
  session open it sleeps, eyes shut and its face dimmed; with sessions idle it blinks, strolls
  across the strip now and then and looks at your cursor; while Codex works it types on its
  laptop; while Codex waits for your approval it hops under a `?` (needs the optional hook
  below). It jumps when a turn finishes, droops with an `x` face for a few seconds when one fails
  or is interrupted, stays drooped once the main window is used up, and waves when clicked. It
  animates only while the popup is open. Its strip is taller than Clawd's (the pet is about
  twice his height), so the hero row grows by about 30 px at the default scale. The pet's moods
  come from the sessions below, which are read even with the list itself turned off.
- **sky:** The Claude widget's sky (see its docs for what it shows), behind the reading and the
  pet, with the same options. Hovering the pet adds the weather to its tooltip.
- **sessions:** Live sessions read from Codex's own files, read-only and with no network: a
  chat counts while a Codex process holds its lock in `~/.codex/thread-writer-locks`, so a
  closed or crashed one never lingers. It is *working* while its newest turn runs, *waiting*
  while Codex asks for your approval (needs the optional hook below), and *idle* otherwise.
  Codex keeps finished chats loaded for hours (Claude Code's Codex plugin and the desktop app
  do), so an idle chat only counts while its last turn is under `idle_minutes` old. Sub-agents
  count towards the chat that started them. The popup lists them, waiting ones first, each with
  the app that started it (`Claude Code`, `Desktop`, `terminal`, `exec`), under a summary like
  `3 open · 1 working`. `~/.codex/auth.json` is never opened.
- **hearts:** Three hearts in the header, tamagotchi-style: every half heart is about 16.7% of
  the main window left (whatever its length; a week on some plans), and they empty only at 100%.
  Hovering says how much is left. Their colours are `-qproperty-heartcolor` and
  `-qproperty-emptycolor` on `.codex-usage-menu .header .hearts`.
- **footer:** A closing line with the plan and the account, and on the right when the numbers
  last arrived (`updated 14:05`), which turns into `stale · 14:05` once they stop arriving or a
  refresh fails. With the footer on, the account moves out of the header and the Overview page
  drops its `Updated` row. Signed out shows as `not signed in` with the `signed-out` class.

### Waiting for approval (optional)

Codex does not record approval prompts anywhere the widget can read, so *waiting* needs a small
Codex hook that YASB ships at `C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1`.
When Codex is about to ask for your approval, it leaves a marker for that session in
`%LOCALAPPDATA%\YASB\codex-waiting`, and removes it when the tool runs or the turn ends. It only
observes: it runs in the background, prints nothing, always exits 0 and never answers the prompt,
so Codex asks you exactly as before. The widget ignores a marker once its turn has ended, its
chat has closed, or Codex has moved on since (a denied request), so a leftover never shows as
waiting.

Add these to `~/.codex/config.toml` (YASB never edits it for you):

```toml
[[hooks.PermissionRequest]]
[[hooks.PermissionRequest.hooks]]
type = "command"
command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
commandWindows = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
async = true

[[hooks.PostToolUse]]
[[hooks.PostToolUse.hooks]]
type = "command"
command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
commandWindows = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
async = true

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
commandWindows = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\YASB\assets\scripts\codex-waiting-hook.ps1"'
async = true
```

Then trust the hooks once. Codex does not run a new hook until you do: the next time you start
`codex` it shows **Hooks need review - 3 hooks are new or changed**. Choose **Trust all and
continue**, or **Review hooks** to look at them first. You can also open the list later with
`/hooks`. Trust is tied to the hook, so Codex asks again if the script changes, for example
after a YASB update.

To check it works: run Codex with approvals on (for example
`codex --ask-for-approval on-request --sandbox read-only`), ask it to create a file, and while it
asks, a file appears in `%LOCALAPPDATA%\YASB\codex-waiting` and the badge shows `?1`. Answering
clears both within a couple of seconds.

Sessions run with approvals off (`--yolo`, `approval_mode = never`) never
ask, so they never show as waiting. Sessions run through Codex's app-server (the desktop app,
Claude Code's Codex plugin) may show *working* instead of *waiting* if Codex does not run hooks
for them.

The pet is painted rather than styled, so its colours come from `-qproperty-*` on
`.codex-usage-menu .codex-pet`: `bodycolor` (default `#5478E6`), `screencolor` (`#181C46`),
`facecolor` (`#8CF0F5`, the `>_` and chest light) and `askcolor` (`#FBBF24`, the `?`). The sky
takes `-qproperty-strength`, `-qproperty-fxopacity` and `-qproperty-edgefade` on
`.codex-usage-menu .sky`, as on the Claude widget.

The sessions section and the footer use the Claude popup's classes, so their rules can be shared:

```css
.codex-usage-menu .hero-top {}                           /* the reading and the pet; also .sky */
.codex-usage-menu .hero-reading {}
.codex-usage-menu .codex-pet {}
.codex-usage-menu .section.sessions {}
.codex-usage-menu .section.sessions .title-row .title {}
.codex-usage-menu .section.sessions .title-row .summary {}
.codex-usage-menu .section.sessions .marker.working {}   /* also .waiting / .idle */
.codex-usage-menu .section.sessions .name {}
.codex-usage-menu .section.sessions .detail.waiting {}   /* also .working / .idle */
.codex-usage-menu .section.sessions .more {}
.codex-usage-menu .header .hearts {}
.codex-usage-menu .meta {}
.codex-usage-menu .meta .account {}                      /* also .signed-out */
.codex-usage-menu .meta .updated {}                      /* also .stale */
```

## Troubleshooting

- `Codex CLI was not found`: install Codex, add it to `PATH`, or set `codex_path` to its full path.
- `--` or a stale warning: run `codex` in a terminal and complete ChatGPT login, then middle-click the widget.
- Shared/public configuration: do not bundle a user's `.codex` directory or credentials. Each user must install and sign in to Codex under their own Windows account.
- No `?` while Codex asks for approval: the hook is missing or not trusted yet (start `codex` and
  choose **Trust all and continue**, or use `/hooks`), the chat runs with approvals off, or YASB
  is installed somewhere other than `C:\Program Files\YASB` (fix the script path in
  `config.toml`). While Codex asks, a file should appear in `%LOCALAPPDATA%\YASB\codex-waiting`;
  if none does, the hook did not run.
- `?1` stays after you closed the Codex window: in recent Codex versions every chat runs in
  Codex's background app-server, and the window is only a view of it. Closing the window leaves
  the chat waiting on its question there, so the badge is right. Reopen it with `codex resume`,
  pick the chat and answer (or press Esc to decline); the `?` clears within a couple of seconds.
- No sessions listed: turn on `sessions` (or `pet`, which reads them too). A chat that has been
  idle longer than `sessions.idle_minutes` (30 by default) is hidden, even though Codex keeps it
  loaded.
- The pet or the sky stands still: they only move while the popup is open.

# Outlook Calendar Widget

Counts down to the next event on your Outlook calendar, and lists the coming days in a popup.

The widget reads the default calendar of **classic Outlook** (`OUTLOOK.EXE`) on this PC, over COM. It shows whatever Outlook shows: an Exchange or Microsoft 365 mailbox, an Outlook.com account, or an IMAP account whose calendar exists only inside Outlook. There is nothing to sign in to and no API key. The new Outlook for Windows has no COM interface and is not supported.

The widget never starts Outlook on its own. While Outlook is closed, the bar keeps counting down from the last events it read, which are saved in `%LOCALAPPDATA%\YASB\outlook_calendar.json`, and marks the reading as stale. While Outlook is closed, the widget checks every 30 seconds for it to come back, so the bar refreshes within about half a minute of Outlook starting. Clicking an event, or the `open_outlook` callback, does open Outlook.

The bar shows the event in progress (`now · Vendor review`) or the next one (`in 25m · Weekly sync`):
- **Counted:** invitations you have not answered, marked as tentative.
- **Not counted:** events shown as **Free**, all-day events and declined events. The popup still lists all-day events at the top of each day.

Click a row to open that event in Outlook. Events with a Microsoft Teams, Zoom or Google Meet link get a **Join** button.

**Privacy.** The cache file `%LOCALAPPDATA%\YASB\outlook_calendar.json` holds event subjects, locations, times and meeting links, which can include passcodes, in plain text. Deleting it is safe.

| Option             | Type    | Default                                       | Description |
|--------------------|---------|-----------------------------------------------|-------------|
| `label`            | string  | `"<span>{icon}</span> {countdown} · {title}"` | The primary label format. |
| `label_alt`        | string  | `"<span>{icon}</span> {time} · {title}"`      | The alternative label format. |
| `empty_text`       | string  | `"No events"`                                 | Shown instead of the label when nothing is coming up in the window. |
| `closed_text`      | string  | `"Outlook closed"`                            | Shown instead of the label when Outlook is closed and nothing has been read yet. |
| `class_name`       | string  | `""`                                          | Additional CSS class name for the widget. |
| `days`             | integer | `7`                                           | How many days, starting today, the widget looks ahead (1-31). |
| `update_interval`  | integer | `300`                                         | Seconds between reads of the calendar (60-3600). Opening the popup also reads it. Countdowns tick every 30 seconds regardless. |
| `soon_minutes`     | integer | `15`                                          | An event starting within this many minutes gets the `soon` class. `0` turns it off (0-240). |
| `max_title_length` | integer | `20`                                          | Cut `{title}` on the bar to this many characters. `0` means no limit (0-200). A theme `max-width` on the label also cuts the text to fit; see below. |
| `time_format`      | string  | `"%H:%M"`                                     | strftime format for times, e.g. `"%I:%M %p"` for 12-hour. It uses Windows strftime, so `%-I`-style flags are rejected when the config loads. |
| `scan_body`        | boolean | `true`                                        | Also look for a meeting link in the event's body, not just its location. See Troubleshooting. |
| `tooltip`          | boolean | `true`                                        | Show the event's details on hover. |
| `icons`            | dict    | `{default: ""}`                              | The widget's icon, used for `{icon}` and in the popup header. |
| `menu`             | dict    | see below                                     | Popup settings. |
| `callbacks`        | dict    | `{on_left: "toggle_card", on_middle: "open_outlook", on_right: "toggle_label"}` | Mouse button actions. |
| `keybindings`      | list    | `[]`                                          | Keyboard shortcuts for the callbacks. |

### Menu options

| Option               | Type    | Default    | Description |
|----------------------|---------|------------|-------------|
| `blur`               | boolean | `true`     | Blur the popup background. |
| `round_corners`      | boolean | `true`     | Round the popup corners (Windows 11). |
| `round_corners_type` | string  | `"normal"` | `normal` or `small`. |
| `border_color`       | string  | `"System"` | `System`, `None` or a hex colour. |
| `alignment`          | string  | `"right"`  | `left`, `right` or `center`. |
| `direction`          | string  | `"down"`   | `up` or `down`. |
| `offset_top`         | integer | `6`        | Vertical offset in pixels. |
| `offset_left`        | integer | `0`        | Horizontal offset in pixels. |
| `min_width`          | integer | `340`      | Minimum popup width in pixels. Long subjects are cut to fit it (200-1000). |
| `max_rows`           | integer | `12`       | How many events the popup lists (1-50). Any events beyond it are summed up in a `+N more` line. |

## Label Placeholders

| Placeholder     | Description                                                     | Example Output |
|-----------------|-----------------------------------------------------------------|----------------|
| `{icon}`        | The configured icon                                             | ``            |
| `{countdown}`   | When the event starts                                           | `now`, `in 25m`, `in 3h 20m`, `tomorrow 10:00`, `Tue 10:00`, `8 Oct 10:00` |
| `{title}`       | The event's subject, cut to `max_title_length`                  | `Weekly sync`  |
| `{time}`        | Its start and end                                               | `14:00–15:00`  |
| `{location}`    | Its location                                                    | `Room 4B`      |
| `{today_count}` | Events still to come or under way today                         | `3`            |

When there is no event to show, the first text label shows `empty_text`, `closed_text` or `Outlook unavailable`, and the rest of the template is left blank.

To keep neighbouring widgets from moving as the text changes, a theme can give the label a fixed slot, for example `.outlook-calendar-widget .label { min-width: 224px; max-width: 224px; }`. When the label has a `max-width`, the widget cuts the text to that width with `…`, so a long title runs to the edge of the slot instead of stopping short. With a fixed slot, set `max_title_length: 0` and let the width decide.

The bar's labels get these classes, so a theme can style each state:

| Class       | When |
|-------------|------|
| `ongoing`   | The event is under way. |
| `soon`      | It starts within `soon_minutes`. |
| `tentative` | It's an invitation you have not answered, or it's shown as Tentative. |
| `stale`     | Outlook is closed, and the events come from the last read. |
| `error`     | Outlook has refused to answer three times in a row, or a read has hung for over a minute. Usually a dialog is open in it. |
| `empty`     | Nothing is coming up. |
| `closed`    | Outlook is closed and nothing has been read yet. |

## Callbacks

| Callback       | Description |
|----------------|-------------|
| `toggle_card`  | Open or close the popup. Opening it also reads the calendar. |
| `toggle_label` | Switch between `label` and `label_alt`. |
| `refresh`      | Read the calendar now. |
| `open_outlook` | Open Outlook's calendar, starting Outlook if needed. |

## Example Configuration

```yaml
outlook_calendar:
  type: "yasb.outlook_calendar.OutlookCalendarWidget"
  options:
    label: "<span>{icon}</span> {countdown} · {title}"
    label_alt: "<span>{icon}</span> {time} · {title}"
    max_title_length: 20
    soon_minutes: 15
    days: 7
    menu:
      alignment: "center"
    callbacks:
      on_left: "toggle_card"
      on_middle: "open_outlook"
      on_right: "toggle_label"
```

## Troubleshooting

- **Always "Outlook closed".** Classic Outlook is not running in your Windows session. Two other setups look the same to the widget:
  - Outlook runs as administrator and yasb does not, or the other way round.
  - You use the new Outlook. Switch the **New Outlook** toggle off in Outlook to go back to classic.
- **Outlook asks whether to allow a program to access email information.** Outlook does this when it considers your antivirus out of date. Set `scan_body: false`, so only the location is searched for meeting links, and update your antivirus.
- **A new invitation is missing.** The calendar is read every `update_interval` seconds. Opening the popup reads it at once.

## Description of Options

- **label**: The format string for the label. Use the placeholders above.
- **label_alt**: The alternative format string, shown after `toggle_label`.
- **empty_text**, **closed_text**: The text shown when there is no event to count down to.
- **days**: The look-ahead window, in days, counting today.
- **update_interval**: How often the calendar is read, in seconds.
- **soon_minutes**: How close an event must be to get the `soon` class.
- **max_title_length**: The maximum length of `{title}`.
- **time_format**: How times are written.
- **scan_body**: Whether to search the event body for meeting links.
- **tooltip**: Whether to show the tooltip.
- **icons**: The widget's icon.
- **menu**: The popup's settings.
- **callbacks**: The mouse button actions.
- **keybindings**: Keyboard shortcuts.

## Example Style

```css
.outlook-calendar-widget .icon {
    font-size: 14px;
    color: #ECEAE4;
    padding-right: 6px;
}
.outlook-calendar-widget .label {
    font-size: 13px;
    color: #ECEAE4;
}
.outlook-calendar-widget .label.soon,
.outlook-calendar-widget .icon.soon,
.outlook-calendar-widget .label.ongoing,
.outlook-calendar-widget .icon.ongoing {
    color: #E0834F;
}
.outlook-calendar-widget .label.tentative {
    font-style: italic;
}
.outlook-calendar-widget .label.empty,
.outlook-calendar-widget .label.closed,
.outlook-calendar-widget .label.error,
.outlook-calendar-widget .label.stale {
    color: rgba(236, 234, 228, 0.5);
}
.outlook-calendar-menu {
    background-color: rgba(30, 30, 32, 0.94);
}
.outlook-calendar-menu .header {
    padding: 12px 16px 10px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.outlook-calendar-menu .header-icon {
    font-size: 15px;
    color: #D4A27F;
    padding-right: 8px;
}
.outlook-calendar-menu .title {
    font-family: "Segoe UI";
    font-size: 14px;
    font-weight: 600;
    color: #ECEAE4;
}
.outlook-calendar-menu .status {
    font-family: "Segoe UI";
    font-size: 11px;
    color: rgba(236, 234, 228, 0.45);
}
.outlook-calendar-menu .status.stale,
.outlook-calendar-menu .status.error {
    color: #D4A27F;
}
.outlook-calendar-menu .day-heading {
    font-family: "Segoe UI";
    font-size: 11px;
    font-weight: 600;
    color: rgba(236, 234, 228, 0.45);
    padding: 12px 16px 4px 16px;
}
.outlook-calendar-menu .event-row {
    padding: 6px 16px;
}
.outlook-calendar-menu .event-row:hover {
    background-color: rgba(255, 255, 255, 0.05);
}
.outlook-calendar-menu .event-row .time {
    font-family: "Bahnschrift";
    font-size: 13px;
    color: #ECEAE4;
    padding-right: 12px;
}
.outlook-calendar-menu .event-row .subject {
    font-family: "Segoe UI";
    font-size: 13px;
    color: #ECEAE4;
}
.outlook-calendar-menu .event-row .location {
    font-family: "Segoe UI";
    font-size: 11px;
    color: rgba(236, 234, 228, 0.45);
}
.outlook-calendar-menu .event-row .when {
    font-family: "Bahnschrift";
    font-size: 12px;
    color: rgba(236, 234, 228, 0.6);
    padding-left: 10px;
}
.outlook-calendar-menu .event-row.soon .when,
.outlook-calendar-menu .event-row.ongoing .when {
    color: #E0834F;
}
.outlook-calendar-menu .event-row.past .time,
.outlook-calendar-menu .event-row.past .subject,
.outlook-calendar-menu .event-row.past .when {
    color: rgba(236, 234, 228, 0.35);
}
.outlook-calendar-menu .event-row .tag {
    font-family: "Segoe UI";
    font-size: 10px;
    color: #D4A27F;
    border: 1px solid rgba(212, 162, 127, 0.6);
    border-radius: 3px;
    padding: 0 4px;
    margin-left: 8px;
}
.outlook-calendar-menu .event-row .join {
    font-family: "Segoe UI";
    font-size: 12px;
    font-weight: 600;
    color: #1E1E20;
    background-color: #E0834F;
    border: none;
    border-radius: 4px;
    padding: 3px 10px;
    margin-left: 10px;
}
.outlook-calendar-menu .event-row .join:hover {
    background-color: #EF5A48;
}
.outlook-calendar-menu .more {
    font-family: "Segoe UI";
    font-size: 11px;
    color: rgba(236, 234, 228, 0.45);
    padding: 6px 16px 10px 16px;
}
.outlook-calendar-menu .placeholder {
    font-family: "Segoe UI";
    font-size: 13px;
    color: rgba(236, 234, 228, 0.5);
    padding: 28px 16px;
}
```

Popup classes:
- **Frame:** `.outlook-calendar-menu`, `.header`, `.header-icon`, `.title`, and `.status` (plus `.stale`, `.error` or `.closed`).
- **Days and rows:** `.day-heading`, and `.event-row` (plus `.all-day`, `.past`, `.ongoing`, `.soon` or `.tentative`).
- **Inside a row:** `.time`, `.subject`, `.location`, `.tag`, `.when`, `.join`.
- **After the rows:** `.more`, the "+N more" line shown when `max_rows` hid events.
- **Empty popup:** `.placeholder` (plus `.empty`, `.closed` or `.error`).

> Qt stylesheets apply the rule with the most classes, whatever its order in the file. The `.outlook-calendar-menu .event-row.past .subject` rule above (four classes) therefore wins over `.outlook-calendar-menu .event-row .subject` (three).

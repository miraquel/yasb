# Outlook Calendar widget — design

Date: 2026-10-01. Status: approved in conversation, pending written-spec review.

## Intent

The user asked for "a feature to track the Outlook calendar and display it in yasb". In the
conversation they chose:

- **Main job:** a countdown to the next event on the bar (`in 25m · Weekly sync`, `now · …`
  while it runs), with a popup listing today's and the coming days' events.
- **Outlook closed:** never launch Outlook. Keep counting down from the last fetched events
  (cached on disk) and mark the reading as stale.
- **Countdown includes:** timed events and unanswered invites (as tentative). It skips
  events marked Free, all-day events and declined events. The popup still lists all-day
  events.
- **Popup clicks:** a row opens that event in Outlook; a row whose event has a Teams, Zoom or
  Google Meet link also gets a Join button.
- **Placement:** the user's centre station, right after `clock`, at a fixed width.
- **Approach:** poll Outlook over COM on a worker thread, with a disk cache (approach A).

Assumptions the user accepted with the design: a 7-day window, a 5-minute poll plus a refresh
whenever a popup opens, no YASB toasts (Outlook already sends reminders), and work on a new
feature branch following the `anime_airing` layout.

Success: the bar answers "what's next and when" in under a second, mid-task, without opening
Outlook, and never moves the centre station when the reading changes (PRODUCT.md layout law).

## Non-goals

YASB reminder toasts; Microsoft Graph or ICS sources; new Outlook (`olk.exe`); calendars
other than the default calendar of the default store; RSVP or editing; past days.

## Findings that fixed the data source

Probed read-only on 2026-10-01:

- Classic Outlook (`Office16\OUTLOOK.EXE`) is installed and running; the new Outlook package
  is also installed but unused. `Outlook.Application` is COM-registered.
- The only account is **IMAP** (`AccountType 1`, gandummas.co.id). Its calendar is local to
  Outlook, so Microsoft Graph and a published ICS feed cannot see it. COM is the only source.
- The default store's calendar holds 12 items, 2 within ±30 days. The one event this week is
  an invite received by mail and not answered (`ResponseStatus 5`, `BusyStatus 1`,
  `MeetingStatus 3`). The calendar is sparse, so "no events" is a common state.
- `Dispatch` took 11 ms; a 7-day `Restrict` plus iteration took 158 ms. Reading `Subject`,
  `Location` and `Body` raised no object-model-guard prompt (Body read in 2 ms).
  `Application.IsTrusted` returned False even so, so it cannot be used to predict a prompt.
- `pywin32 312` and `comtypes 1.4.16` are already dependencies; nothing new is installed.
- Windows locale: `en-ID`, short date customised to `MM/dd/yyyy`, time `HH:mm`.

## Architecture

| Unit | File (under `src/core/`) | Job | Depends on |
|---|---|---|---|
| Event model and logic | `widgets/services/outlook_calendar/agenda.py` | `CalEvent`, `Snapshot`; selection, grouping, formatting, join-link extraction, cache (de)serialisation. Pure. | stdlib |
| COM source | `widgets/services/outlook_calendar/outlook.py` | `fetch(now, days) -> list[CalEvent]` (attach only), `open_event(...)`, `open_calendar()`. | pywin32 |
| Shared service | `widgets/services/outlook_calendar/service.py` | One per process. Polls on a `QThread`, holds the latest `Snapshot`, writes and loads the cache. | agenda, outlook |
| Widget | `widgets/yasb/outlook_calendar.py` | Bar label every 30 s from the snapshot; popup. No COM calls. | service, agenda |
| Config | `validation/widgets/yasb/outlook_calendar.py` | Pydantic model. | base_model |

Docs: `docs/widgets/(Widget)-Outlook-Calendar.md`, plus entries in `README.md` and
`docs/_Sidebar.md`. Tests: `tests/test_outlook_calendar_{agenda,outlook,service,widget}.py`.

COM runs only on worker threads, each calling `pythoncom.CoInitialize()` and
`CoUninitialize()` itself. The UI thread never waits on Outlook.

## Event model

```python
@dataclass(frozen=True)
class CalEvent:
    start: datetime          # naive local time
    end: datetime            # naive local time; all-day events end at 00:00 of the day after
    subject: str
    location: str
    all_day: bool
    busy: int                # OlBusyStatus: 0 free, 1 tentative, 2 busy, 3 out of office, 4 working elsewhere
    response: int            # OlResponseStatus: 0 none, 1 organized, 2 tentative, 3 accepted, 4 declined, 5 not responded
    entry_id: str
    store_id: str
    recurring: bool
    join_url: str            # "" when none

@dataclass(frozen=True)
class Snapshot:
    events: tuple[CalEvent, ...]
    fetched_at: datetime | None   # when these events were read from Outlook; None = never
    status: Literal["live", "stale", "closed", "error"]
```

- `tentative` is `response in (2, 5) or busy == 1`.
- `status`:
  - `live`: the last poll succeeded.
  - `stale`: events come from the cache, either loaded at startup before the first poll or
    kept because Outlook is no longer running.
  - `closed`: Outlook is not running and there is nothing cached.
  - `error`: 3 consecutive polls failed for a reason other than "not running". The last
    events are still shown.

## Fetch (`outlook.fetch`)

1. `win32com.client.GetActiveObject("Outlook.Application")`. A `com_error` with
   `MK_E_UNAVAILABLE` (Outlook not in the Running Object Table) raises `OutlookNotRunning`.
   `Dispatch` is never used here, so a poll cannot launch Outlook.
2. `ns.GetDefaultFolder(9)` (olFolderCalendar); `items.Sort("[Start]")`, then
   `items.IncludeRecurrences = True`, in that order.
3. Window: `today 00:00` to `today 00:00 + days`. The `Restrict` string
   `[Start] < '<end>' AND [End] > '<start>'` is built with the user's locale date and time
   formats (`win32api.GetDateFormat` / `GetTimeFormat`, `LOCALE_USER_DEFAULT`), which is
   what Outlook parses.
4. Walk with `GetFirst` / `GetNext`; never use `Count`, which is meaningless with recurrences
   expanded. Stop at the first item whose start is at or past the window end, or after 500
   items.
5. Drop declined items (`ResponseStatus 4`) and cancelled meetings (`MeetingStatus` 5 or 7).
6. Convert `Start` / `End` to naive local time (`.replace(tzinfo=None)`; pywin32 tags local
   wall times with a tzinfo that must not be converted).
7. `join_url`: `find_join_url(location)`, else `find_join_url(body)` when `scan_body` is on.
   The body is read only for this and never stored.
8. Events are filtered again in Python against the window, so a loose `Restrict` is harmless.

## Bar

`select_event(events, now)` picks one event among **eligible** ones: not all-day,
`busy != 0`, and not declined.

1. **Ongoing** (`start <= now < end`): the one that ends first. Countdown `now`.
2. Otherwise **next** (`start > now`): the earliest start.
3. Otherwise none → `label_empty`.

Countdown (`format_countdown(event, now, time_format)`). The wait is first rounded up to
whole minutes, `m = ceil(seconds / 60)`, and the case is chosen from `m`: 24m10s reads
`in 25m`, and 59m30s becomes 60 and reads `in 1h`.

| Case | Text |
|---|---|
| Ongoing | `now` |
| `m < 60` | `in 25m` |
| Later today | `in 3h 20m`, or `in 2h` when the minutes are 0 |
| Tomorrow | `tomorrow 10:00` |
| Within the next 6 days | `Tue 10:00` |
| Further | `3 Oct 10:00` |

Placeholders: `{icon}`, `{countdown}`, `{title}` (subject shortened to `max_title_length`
with `…`), `{time}` (`14:00–15:00`, or `all day`), `{location}`, `{today_count}` (eligible
events today that have not ended).

Label classes, set on the widget's labels so a theme can style them: `soon` (an upcoming
event starts within `soon_minutes`; 0 turns it off), `ongoing`, `tentative`, `stale`, `empty`, `closed`,
`error`.

Tooltip: full subject, `{time}` with the day, location, `Tentative` when it applies, and on
a stale reading `cached 08:12 · Outlook closed`.

## Popup

- Header: `Calendar` and a status line: `updated 08:12`, `Outlook closed · cached 08:12`,
  or `Outlook unavailable · cached 08:12`. Opening the popup calls
  `service.refresh_now()`; the rows are rebuilt when the new snapshot arrives while it is
  open.
- Day groups, headed `Today`, `Tomorrow`, then `Fri 3 Oct`. Empty days are omitted.
  - All-day events first, one line each, on every day they cover inside the window.
  - Timed rows: time range (Bahnschrift in the example style, with a min-width so rows
    align), subject elided to one line, location as a second smaller line, and a right-hand
    status (`now`, `in 25m`, `ended`). A timed event that began before today is listed
    under Today.
  - Row classes: `past` (ended today), `ongoing`, `soon`, `tentative` (also shows a
    `Tentative` tag).
- Join button when `join_url` is set: opens the URL with `QDesktopServices.openUrl`.
- Clicking a row elsewhere calls `outlook.open_event` on a short-lived worker thread. That
  path uses `Dispatch`, because launching Outlook on an explicit click is the expected
  result. For a recurring item it opens the occurrence
  (`GetRecurrencePattern().GetOccurrence(start)`) and falls back to the series when that
  fails (a moved exception).
- Empty: `Nothing in the next 7 days` (the number follows `days`). Rows are capped at
  `menu.max_rows`.
- Unstyled, the popup reads cleanly under any theme. The docs' Example Style uses the user's
  palette (graphite with chalk text, kraft `#D4A27F` for tentative, clay `#E0834F` for soon),
  with no `var()`s.

Middle click (`open_outlook`): launches Outlook's calendar view through ShellExecute with
`outlook.exe /select outlook:calendar`.

## Config

```python
class OutlookCalendarConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {countdown} · {title}"
    label_alt: str = "<span>{icon}</span> {time} · {title}"
    label_empty: str = "<span>{icon}</span> No events"
    label_closed: str = "<span>{icon}</span> Outlook closed"
    class_name: str = ""
    days: int = Field(default=7, ge=1, le=31)
    update_interval: int = Field(default=300, ge=60, le=3600)
    soon_minutes: int = Field(default=15, ge=0, le=240)
    max_title_length: int = Field(default=20, ge=0, le=200)
    time_format: str = "%H:%M"
    scan_body: bool = True      # turn off if Outlook ever prompts about program access
    tooltip: bool = True
    icons: OutlookCalendarIconsConfig       # default: a Nerd Fonts v3 calendar glyph outside U+F500-U+FD46
    menu: OutlookCalendarMenuConfig         # blur, round_corners, round_corners_type, border_color,
                                            # alignment, direction, offset_top, offset_left,
                                            # min_width=340, max_rows=12
    callbacks: OutlookCalendarCallbacksConfig   # on_left toggle_card, on_middle open_outlook,
                                                # on_right toggle_label
    keybindings: list[KeybindingConfig] = []
```

## Service

- `OutlookCalendarService.get_instance(days, update_interval, scan_body)`: one per process,
  reference-counted like `AnimeAiringService`; `release()` when a widget is destroyed. The
  shortest interval and longest `days` asked for win.
- On creation it loads the cache into a `stale` snapshot, then starts the first poll.
- One `_FetchWorker(QThread)` at a time. `refresh_now()` while a fetch is running is a no-op.
- Results:
  - success → `live`, write the cache, reset the failure count
  - `OutlookNotRunning` → keep the events; `stale` if any, else `closed`
  - any other error → keep the snapshot unchanged; after 3 in a row, `error`
- Emits `snapshot_changed(Snapshot)`. Widgets also re-render every 30 s from the wall clock,
  so sleep and resume need no special handling.
- Cache: `%LOCALAPPDATA%\YASB\outlook_calendar.json`, holding
  `{"version": 1, "fetched_at": ..., "events": [...]}` with subject, location, times,
  ids and join URL only. A missing, corrupt or wrong-version cache is ignored (logged at
  debug), never fatal.
- On shutdown it stops its timer and waits for a running worker.

## Errors and edge cases

| Situation | Behaviour |
|---|---|
| Outlook not running at login | Cached events, `stale`; `Outlook closed` if no cache |
| Outlook closed later | Same as above; the countdown keeps running from the cache |
| Outlook busy (modal dialog, `RPC_E_CALL_REJECTED`) | Snapshot kept; retried next poll; `error` after 3 |
| Outlook elevated, yasb not (or the reverse) | Looks like "not running" (separate Running Object Table); documented |
| User switches to new Outlook | Looks like "not running"; documented as unsupported |
| Antivirus status lapses and Outlook prompts on Body | `scan_body: false` avoids it; documented |
| Corrupt cache | Ignored; first successful poll rewrites it |
| Event crossing midnight | Listed under its start day, or under Today if it started earlier |
| Several ongoing events | The one that ends first takes the bar |

## Testing

unittest modules run by name; no pytest in the venv.

- `test_outlook_calendar_agenda`: eligibility (Free, declined, all-day, tentative allowed);
  ongoing vs next; overlap; nothing left; countdown at the 60-minute, end-of-day and
  tomorrow boundaries, and rounding up; `{title}` shortening; grouping (all-day multi-day,
  crossing midnight, empty days omitted); `find_join_url` for Teams, Zoom (with `pwd`),
  Meet, a Safe Links wrapper, `<...>`-wrapped links and negatives; cache round-trip, corrupt
  cache and wrong version.
- `test_outlook_calendar_outlook`: against a fake COM namespace (duck-typed items): field
  conversion, declined and cancelled dropped, stop at window end, 500 cap, `scan_body` off
  never reads `Body`, not-running path raises `OutlookNotRunning`, and the `Restrict` string
  uses the locale formatter.
- `test_outlook_calendar_service`: cache loaded as `stale` at start; success → `live` and
  cache written; not running keeps the events; 3 failures → `error`.
- `test_outlook_calendar_widget`: label text and classes per state with `_now` pinned;
  popup built into a host `QFrame` (rows, tentative tag, Join button only with a URL, empty
  state).
- Read-only live smoke test of `fetch` against the user's real Outlook.
- `ruff check` and `ruff format --check` (line length 120) through the venv's Python.

## Delivery

1. Branch `feat/outlook-calendar` off `main`. One `feat(outlook_calendar)` commit, matching
   the other fork features, built in an isolated worktree. This spec and the plan live on
   `spec/outlook-calendar`, which is never merged into the feature or `squash`.
2. With the user's OK at that point: re-assemble `squash` from the feature branches
   (patch-id check), build, install, add `outlook_calendar` to `config.yaml` right after
   `clock`, and add its styles to `styles.css` under a `---- Outlook calendar ----`
   comment.
3. Nothing is pushed unless the user asks.

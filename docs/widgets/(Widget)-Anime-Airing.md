# Anime Airing Widget

Counts down to the next episode of the anime you are watching, and sends a Windows notification when an episode airs.

Your list comes from **MyAnimeList**: the widget reads a public list by username, with no API key and no login. MyAnimeList has no broadcast times, so the schedule comes from **AniList**, whose public API looks up shows by their MyAnimeList id and returns the exact moment each episode airs. Neither service needs an account.

The bar shows the soonest episode. The popup lists every show on your list that is still airing, soonest first, with how many aired episodes you have not marked as watched yet. Click a show to open it on MyAnimeList.

> Your MyAnimeList list must be public. A private list, or a username that does not exist, shows **User not found**.

| Option             | Type    | Default                                       | Description |
|--------------------|---------|-----------------------------------------------|-------------|
| `label`            | string  | `"<span>{icon}</span> {title} {countdown}"`   | The primary label format. |
| `label_alt`        | string  | `"<span>{icon}</span> Ep {episode} · {air_time}"` | The alternative label format. |
| `class_name`       | string  | `""`                                          | Additional CSS class name for the widget. |
| `username`         | string  | `""`                                          | Your MyAnimeList username. Required. |
| `statuses`         | list    | `["watching"]`                                | Which parts of your list to follow: any of `watching`, `on_hold`, `plan_to_watch`. |
| `title_language`   | string  | `"romaji"`                                    | `romaji` (the title MyAnimeList shows) or `english`, which falls back to romaji when a show has no English title. |
| `max_title_length` | integer | `20`                                          | Cut `{title}` on the bar to this many characters. `0` means no limit. |
| `update_interval`  | integer | `1800`                                        | Seconds between refreshes of the list and the schedule (300-86400). Countdowns tick every minute regardless. |
| `tooltip`          | boolean | `true`                                        | Show the upcoming episodes on hover. |
| `icons`            | dict    | `{default: ""}`                         | The widget's icon, used for `{icon}` and in the popup header. |
| `menu`             | dict    | see below                                     | Popup settings. |
| `notifications`    | dict    | see below                                     | Reminder settings. |
| `callbacks`        | dict    | `{on_left: "toggle_card", on_middle: "do_nothing", on_right: "toggle_label"}` | Mouse button actions. |
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
| `min_width`          | integer | `340`      | Minimum popup width in pixels. Long titles are cut to fit it. |
| `max_rows`           | integer | `10`       | How many shows the popup lists. |
| `show_covers`        | boolean | `true`     | Show cover art. Covers are cached in `%LOCALAPPDATA%\YASB\anime_airing_covers`. |

### Notification options

| Option           | Type    | Default | Description |
|------------------|---------|---------|-------------|
| `enabled`        | boolean | `true`  | Send a Windows notification when an episode airs. |
| `offset_minutes` | integer | `0`     | Shift the reminder relative to the broadcast. Negative is a heads-up before it airs (`-15`); positive waits for a stream or subtitles to go up (`60`). |
| `catch_up_hours` | integer | `12`    | An episode that aired while the PC was asleep or yasb was closed is still announced when it comes back, if it aired at most this long ago. `0` announces only episodes that air while yasb is running. |

Each episode is announced once, including across restarts. On the very first run, episodes that aired before the widget was installed are not announced. The notification's button opens the show on MyAnimeList. The shows' cover art is used as the notification image.

Broadcast times are the original Japanese TV airing. Streaming sites often publish later, which is what `offset_minutes` is for.

## Label Placeholders

| Placeholder      | Description                                                        | Example Output |
|------------------|--------------------------------------------------------------------|----------------|
| `{icon}`         | The configured icon                                                | ``       |
| `{title}`        | Title of the show airing next, cut to `max_title_length`           | `Mushoku Tensei…` |
| `{episode}`      | Its episode number                                                 | `14`           |
| `{countdown}`    | Time until it airs                                                 | `1d 6h`, `18h 05m`, `45m`, `now` |
| `{air_time}`     | When it airs, in local time                                        | `Today 18:00`, `Tomorrow 18:00`, `Wed 20:00`, `Sat 3 Oct 09:00` |
| `{airing_count}` | How many shows on the followed lists have an episode coming        | `3`            |
| `{unwatched}`    | Aired episodes not yet marked watched, across those shows          | `1`            |

When there is nothing to count down, the first text label shows the state instead - `Loading...`, `Nothing airing`, `User not found`, `Offline`, `Rate limited` or `Set username` - and the rest of the template is left blank.

## Callbacks

| Callback        | Description |
|-----------------|-------------|
| `toggle_card`   | Open or close the popup. |
| `toggle_label`  | Switch between `label` and `label_alt`. |
| `refresh`       | Refetch the list and the schedule now. |
| `open_list`     | Open your Watching list on MyAnimeList. |
| `test_reminder` | Send a notification for the next episode right now, to check that notifications reach you (Focus Assist / Do Not Disturb can hide them). |

## Example Configuration

```yaml
anime_airing:
  type: "yasb.anime_airing.AnimeAiringWidget"
  options:
    label: "<span>{icon}</span> {title} {countdown}"
    label_alt: "<span>{icon}</span> Ep {episode} · {air_time}"
    username: "your_mal_username"
    statuses: ["watching"]
    title_language: "romaji"
    max_title_length: 16
    update_interval: 1800
    notifications:
      enabled: true
      offset_minutes: 0
      catch_up_hours: 12
    callbacks:
      on_left: "toggle_card"
      on_middle: "open_list"
      on_right: "toggle_label"
    menu:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: "System"
      alignment: "center"
      direction: "down"
```

## Notes

- A MyAnimeList entry can match more than one AniList entry when AniList splits a season into parts (for example one MyAnimeList entry for a whole series released in "stages"). The widget follows whichever part airs next and shows AniList's title for it, because AniList numbers the episodes of each part from 1. The unwatched count is left out for those shows, since the two sites' episode numbers do not line up.
- Shows that MyAnimeList already marks as finished airing are not looked up on AniList.
- The last fetched schedule is cached in `%LOCALAPPDATA%\YASB\anime_airing_<username>.json`, so the bar shows a countdown straight away at startup and keeps working offline.
- AniList allows around 30 requests a minute. Each refresh uses two, plus one more per 50 shows.

## Style

The label carries a state class a theme can use: `soon` when the next episode is within the hour, `unwatched` when aired episodes are waiting, and `loading`, `error` or `empty` when there is nothing to count down.

```css
.anime-airing-widget {}
.anime-airing-widget .widget-container {}
.anime-airing-widget .label {}
.anime-airing-widget .label.alt {}
.anime-airing-widget .icon {}
.anime-airing-widget .label.soon {}       /* next episode within an hour */
.anime-airing-widget .label.unwatched {}  /* aired episodes not yet watched */
.anime-airing-widget .label.loading {}
.anime-airing-widget .label.error {}
.anime-airing-widget .label.empty {}      /* nothing on the list is airing */

/* Popup */
.anime-airing-menu {}
.anime-airing-menu .header {}
.anime-airing-menu .header-icon {}
.anime-airing-menu .title {}
.anime-airing-menu .username {}
.anime-airing-menu .hero {}               /* the next episode */
.anime-airing-menu .hero.soon {}
.anime-airing-menu .hero-cover {}
.anime-airing-menu .hero-title {}
.anime-airing-menu .hero-meta {}          /* "Episode 14 · Tomorrow 18:00" */
.anime-airing-menu .hero-countdown {}
.anime-airing-menu .hero-unwatched {}
.anime-airing-menu .rows-container {}
.anime-airing-menu .show-row {}           /* also .active (next up), .soon, .unwatched */
.anime-airing-menu .show-cover {}
.anime-airing-menu .show-title {}
.anime-airing-menu .show-meta {}          /* "Ep 14 · Tomorrow 18:00" */
.anime-airing-menu .show-countdown {}
.anime-airing-menu .show-unwatched {}     /* "1 new" */
.anime-airing-menu .footer {}
.anime-airing-menu .source {}
.anime-airing-menu .status {}             /* "Updated 5m ago"; also .stale after a failed refresh */
.anime-airing-menu .placeholder {}        /* loading, error and empty states */
```

## Example Style

```css
.anime-airing-widget .icon {
  margin: 0 5px 0 0;
}
.anime-airing-widget .label {
  font-family: "Bahnschrift";
  min-width: 150px;
}
.anime-airing-widget .icon.unwatched {
  color: #d4a27f;
}
.anime-airing-widget .label.soon,
.anime-airing-widget .icon.soon {
  color: #e0834f;
}
.anime-airing-widget .label.loading,
.anime-airing-widget .label.error,
.anime-airing-widget .label.empty {
  color: rgba(236, 234, 228, 0.45);
}

.anime-airing-menu {
  background-color: rgba(18, 20, 28, 0.94);
}
.anime-airing-menu .header {
  padding: 14px 18px 4px 18px;
}
.anime-airing-menu .header-icon {
  font-family: "JetBrainsMono NFP";
  font-size: 14px;
  color: rgba(235, 238, 245, 0.6);
  padding-right: 8px;
}
.anime-airing-menu .title {
  font-family: "Segoe UI";
  font-size: 13px;
  font-weight: 600;
  color: rgba(235, 238, 245, 0.6);
}
.anime-airing-menu .username {
  font-family: "Segoe UI";
  font-size: 11px;
  color: rgba(235, 238, 245, 0.4);
}
.anime-airing-menu .hero {
  padding: 12px 18px 16px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.anime-airing-menu .hero-cover {
  margin-right: 14px;
  background-color: rgba(255, 255, 255, 0.05);
}
.anime-airing-menu .hero-title {
  font-family: "Segoe UI";
  font-size: 14px;
  font-weight: 600;
  color: rgba(244, 245, 248, 0.92);
}
.anime-airing-menu .hero-meta {
  font-family: "Segoe UI";
  font-size: 11px;
  color: rgba(235, 238, 245, 0.5);
  margin-top: 2px;
}
.anime-airing-menu .hero-countdown {
  font-family: "Bahnschrift";
  font-size: 28px;
  color: #ffffff;
  margin-top: 4px;
}
.anime-airing-menu .hero.soon .hero-countdown {
  color: #e0834f;
}
.anime-airing-menu .hero-unwatched {
  font-family: "Segoe UI";
  font-size: 11px;
  color: #d4a27f;
}
.anime-airing-menu .rows-container {
  padding: 6px 0;
}
.anime-airing-menu .show-row {
  padding: 6px 18px 6px 15px;
  border-left: 3px solid transparent;
}
.anime-airing-menu .show-row:hover {
  background-color: rgba(255, 255, 255, 0.04);
}
.anime-airing-menu .show-row.active {
  border-left-color: rgba(236, 234, 228, 0.5);
  background-color: rgba(236, 234, 228, 0.05);
}
.anime-airing-menu .show-row.soon {
  border-left-color: #e0834f;
  background-color: rgba(224, 131, 79, 0.1);
}
.anime-airing-menu .show-cover {
  margin-right: 10px;
  background-color: rgba(255, 255, 255, 0.05);
}
.anime-airing-menu .show-title {
  font-family: "Segoe UI";
  font-size: 13px;
  color: rgba(244, 245, 248, 0.85);
}
.anime-airing-menu .show-row.active .show-title {
  color: #ffffff;
}
.anime-airing-menu .show-meta {
  font-family: "Segoe UI";
  font-size: 11px;
  color: rgba(235, 238, 245, 0.45);
}
.anime-airing-menu .show-countdown {
  font-family: "Bahnschrift";
  font-size: 13px;
  min-width: 56px;
  color: rgba(235, 238, 245, 0.75);
  padding-left: 12px;
}
.anime-airing-menu .show-row.soon .show-countdown {
  color: #e0834f;
}
.anime-airing-menu .show-unwatched {
  font-family: "Segoe UI";
  font-size: 10px;
  color: #d4a27f;
}
.anime-airing-menu .footer {
  padding: 10px 18px 12px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}
.anime-airing-menu .source,
.anime-airing-menu .status {
  font-family: "Segoe UI";
  font-size: 11px;
  color: rgba(235, 238, 245, 0.4);
}
.anime-airing-menu .status.stale {
  color: #d4a27f;
}
.anime-airing-menu .placeholder {
  padding: 28px 18px;
  font-family: "Segoe UI";
  font-size: 13px;
  color: rgba(235, 238, 245, 0.45);
}
```

# Traffic Widget Options

Displays your network upload and download speeds in real-time. You can filter by specific network adapters, choose between bits and bytes, align the labels, and set the widget to hide itself when your PC is offline.

| Option          | Type    | Default                                                                 | Description                                                                 |
|-----------------|---------|-------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| `label`         | string  | `'\ueb01 \ueab4 {download_speed} \| \ueab7 {upload_speed}'`                | The format string for the traffic widget. Displays download and upload speeds. |
| `label_alt`     | string  | `'\ueb01 \ueab4 {upload_speed} \| \ueab7 {download_speed}'`                | The alternative format string for the traffic widget. Displays upload and download speeds. |
| `class_name`    | string  | `""`                                                                                  | Additional CSS class name for the widget.                                    |
| `update_interval` | integer | `1000`                                                                 | The interval in milliseconds to update the traffic data. |
| `interface`       | string  | `auto`                                                                  | The network interface to monitor. If not specified, the widget will use the default interface. |
| `hide_if_offline` | boolean | `false`                                                                 | Hide the widget if the network interface is offline.                        |
| `max_label_length` | integer | `0`                                                                    | The maximum length of the label.                                           |
| `max_label_length_align` | string  | `'left'`                                                               | The alignment of the label when it exceeds the maximum length. Can be `left`, `center`, or `right`. |
| `speed_unit`     | string  | `'bits'`                                                                | The unit of speed to display. Can be `bits` or `bytes`. |
| `hide_decimal` | boolean | `False`                                                                 | Hide decimal in the label. If set to `True`, the label will not show decimal places in the speed values. |
| `speed_threshold` | dict   | `{'min_upload': 1000, 'min_download': 1000}` | Minimum speed threshold for upload and download in bits. If the speed is below this threshold, the widget will not display the speed values. |
| `callbacks`     | dict    | [See below](#available-callbacks) | Callbacks for mouse events on the traffic widget. |
| `menu`          | dict    | [See below](#menu-options) | Menu options for the widget. |
| `keybindings`   | list    | `[]`                       | Optional hotkeys. See [Keybindings](./Keybindings). |
| `sparkline`     | dict    | [See below](#sparkline-options) | A tiny live bar graph of download and upload speed, shown after `label`. Off by default. |


## Menu Options
| Option               | Type    | Default    | Description                                                  |
|----------------------|---------|------------|--------------------------------------------------------------|
| `blur`               | bool    | `true`     | Blur background behind the popup.                            |
| `round_corners`      | bool    | `true`     | Enable rounded corners on the popup.                         |
| `round_corners_type` | string  | `"normal"` | Rounding style: `"small"`, `"normal"`.         |
| `border_color`       | string  | `"system"` | Border color can be `None`, `system` or `Hex Color` `"#ff0000"`       |
| `alignment`          | string  | `"left"`   | Horizontal alignment of the menu relative to the widget (e.g., left, right, center)                 |
| `direction`          | string  | `"down"`   | Vertical opening direction: `"up"` or `"down"`.              |
| `offset_top`         | int     | `6`        | Vertical offset in pixels.                                   |
| `offset_left`        | int     | `0`        | Horizontal offset in pixels.                                 |
| `show_interface_name` | bool    | `true`     | Show the name of the network interface in the menu.          |
| `show_internet_info` | bool    | `true`     | Show the internet connection information in the menu. Connected or disconnected status. |

## Sparkline Options
| Option        | Type    | Default | Description                                                                 |
|---------------|---------|---------|-----------------------------------------------------------------------------|
| `enabled`     | bool    | `false` | Show the bar graph right after the widgets of `label`.                      |
| `bars`        | int     | `12`    | How many samples the graph keeps. One sample is taken every `update_interval`, so the default shows the last 12 seconds. |
| `bar_width`   | int     | `2`     | Width of each bar in pixels.                                                |
| `bar_gap`     | int     | `1`     | Space between bars in pixels. `0` makes the bars touch.                     |
| `height`      | int     | `16`    | Height of the graph in pixels, at least `3`.                                |
| `scale_floor` | int     | `65536` | Speed in bytes/s that fills a bar when nothing faster is in view, so a quiet connection never draws full-height bars. |

The graph is `bars * (bar_width + bar_gap) + 2` pixels wide (38 at the defaults). A 1px baseline
splits it: download bars grow up from it, upload bars hang below it, upload getting the smaller
share of the height. Both directions share one logarithmic scale, so a trickle stays visible next
to a burst: full height is the fastest sample currently in view, or `scale_floor` if that is
higher. A speed below `speed_threshold` draws no bar; anything at or above it draws at least 1px.

The graph belongs to `label`. It hides while `toggle_label` shows `label_alt` and comes back when
you toggle again, so a click can swap the graph for numbers. It keeps sampling while hidden.

## Available Callbacks

The `callbacks` option maps mouse buttons (`on_left`, `on_middle`, `on_right`) to actions. All keys are optional, the values shown are the defaults.

```yaml
callbacks:
  on_left: "toggle_label"
  on_middle: "do_nothing"
  on_right: "do_nothing"
```

Available actions:

- `toggle_label`: Toggles the label between the main and alternative formats.
- `toggle_menu`: Toggles the visibility of the menu.
- `reset_data`: Resets all traffic data.
- `update_label`: Refreshes the label now.

## Available Placeholders
- `{download_speed}` - Current download speed
- `{upload_speed}` - Current upload speed
- `{download_compact_value}` - Current download speed as a number of at most three characters, right-aligned with spaces (`  0`, `7.4`, ` 56`, `562`). It switches to the next unit before it would need a fourth digit.
- `{download_compact_unit}` - The unit letter for `{download_compact_value}`: `K`, `M` or `G` (kilo/mega/giga, in bits or bytes per `speed_unit`)
- `{upload_compact_value}` - Current upload speed, as `{download_compact_value}`
- `{upload_compact_unit}` - The unit letter for `{upload_compact_value}`
- `{session_uploaded}` - Data uploaded during the current session
- `{session_downloaded}` - Data downloaded during the current session
- `{today_uploaded}` - Data uploaded today
- `{today_downloaded}` - Data downloaded today
- `{alltime_uploaded}` - Total data uploaded (all time)
- `{alltime_downloaded}` - Total data downloaded (all time)

## Example Configuration
```yaml
traffic:
  type: "yasb.traffic.TrafficWidget"
  options:
    label: "\ueb01 \ueab4 {download_speed} | \ueab7 {upload_speed}"
    label_alt: "Download {download_speed} | Upload {upload_speed}"
    update_interval: 1000
    menu:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: "system"
      alignment: "left"
      direction: "down"
      offset_top: 6
      offset_left: 0
    callbacks:
      on_left: "toggle_menu"
      on_right: "toggle_label"
```

### Sparkline with compact numbers
The icon and the graph by default; click to swap the graph for numbers like `↓ 23M ↑ 175K`, click again to get the graph back. The `dn`, `up` and `unit` classes are just names for styling those spans.
```yaml
traffic:
  type: "yasb.traffic.TrafficWidget"
  options:
    label: "<span></span>"
    label_alt: "<span></span><span class=\"dn\">↓</span>{download_compact_value}<span class=\"unit\">{download_compact_unit}</span><span class=\"up\">↑</span>{upload_compact_value}<span class=\"unit\">{upload_compact_unit}</span>"
    sparkline:
      enabled: true
```

## Description of Options
- **label:** The format string for the traffic widget. Displays download and upload speeds.
- **label_alt:** The alternative format string for the traffic widget. Displays upload and download speeds.
- **class_name:** Additional CSS class name for the widget. This allows for custom styling.
- **update_interval:** The interval in milliseconds to update the traffic data.
- **interface:** The network interface to monitor. If not specified, the widget will use the default interface.
- **hide_if_offline:** Hide the widget if the network interface is offline.
- **max_label_length:** The maximum length of the label.
- **max_label_length_align:** The alignment of the label when it exceeds the maximum length. Can be `left`, `center`, or `right`.
- **speed_unit:** The unit of speed to display. Can be `bits` or `bytes`.
- **hide_decimal:** Hide decimal in the label. If set to `True`, the label will not show decimal places in the speed values.
- **speed_threshold:** A dictionary specifying the minimum speed threshold for upload and download in bits. If the speed is below this threshold, the widget will not display the speed values.
- **keybindings:** A list of global hotkeys for this widget. See [Keybindings](./Keybindings).
- **callbacks:** Mouse event callbacks. See [Callbacks](#available-callbacks).
- **menu:** A dictionary specifying the menu options for the widget. See **Menu Options** above for details.
- **sparkline:** A dictionary for the live bar graph shown after `label`. See **Sparkline Options** above for details.

> [!NOTE]  
> YASB stores traffic data in the `%LOCALAPPDATA%\Yasb` directory, including all-time upload/download statistics and daily totals. Session data is temporary and resets when YASB restarts.


## Available CSS Classes
```css
/* Main widget styling */
.traffic-widget { }
.traffic-widget.your_class {} /* If you are using class_name option */
.traffic-widget .widget-container { }
.traffic-widget .label { }
.traffic-widget .label.offline { } /* offline state */
.traffic-widget .label.alt { }
.traffic-widget .icon { }
.traffic-widget .icon.offline { } /* offline state */
.traffic-widget .traffic-sparkline { } /* the bar graph, when sparkline is enabled */

/* Menu styling */
.traffic-menu { }
.traffic-menu .header { }
.traffic-menu .header .title { }
.traffic-menu .header .reset-button { }
.traffic-menu .interface-info { }
.traffic-menu .internet-info { }
.traffic-menu .internet-info.checking { }
.traffic-menu .internet-info.connected { }
.traffic-menu .internet-info.disconnected { }

/* Section-specific styling */
.traffic-menu .section { }
.traffic-menu .section-title { }
.traffic-menu .section.speeds-section { }
.traffic-menu .section.session-section { }
.traffic-menu .section.today-section { }
.traffic-menu .section.alltime-section { }

/* Speed columns styling */
.traffic-menu .upload-speed,
.traffic-menu .download-speed { }

/* Speed columns values and units styling */
.traffic-menu .upload-speed-value { }
.traffic-menu .download-speed-value { }
.traffic-menu .upload-speed-unit { }   
.traffic-menu .download-speed-unit { }
.traffic-menu .upload-speed-placeholder { } 
.traffic-menu .download-speed-placeholder { }

/* Separator styling between upload and download speeds columns */
.traffic-menu .speed-separator { } 

/* Text labels styling */
.traffic-menu .data-text { }
.traffic-menu .data-text.session-upload-text,
.traffic-menu .data-text.session-download-text,
.traffic-menu .data-text.session-duration-text,
.traffic-menu .data-text.today-upload-text,
.traffic-menu .data-text.today-download-text,
.traffic-menu .data-text.alltime-upload-text,
.traffic-menu .data-text.alltime-download-text { }

/* Value labels styling */
.traffic-menu .data-value { }
.traffic-menu .data-value.session-upload-value,
.traffic-menu .data-value.session-download-value,
.traffic-menu .data-value.session-duration-value,
.traffic-menu .data-value.today-upload-value,
.traffic-menu .data-value.today-download-value,
.traffic-menu .data-value.alltime-upload-value,
.traffic-menu .data-value.alltime-download-value { }
```


### Sparkline colours
The graph is painted, so its colours come from `-qproperty-` values on `.traffic-sparkline`
rather than `color` or `background`. These are the defaults:
```css
.traffic-widget .traffic-sparkline {
    -qproperty-downloadcolor: #89dceb;
    -qproperty-uploadcolor: #cba6f7;
    -qproperty-baselinecolor: #45475a;
}
```
Nothing is painted behind the bars. A `margin` or `padding` on `.traffic-sparkline` adds space
around the graph without stretching it. The names are not case-sensitive, so
`-qproperty-downloadColor` works too. The `-qproperty-` dash follows the same convention as the
[adaptive bar style](Styling#adaptive-bar-style): CSS editors read it as a vendor prefix, and YASB
strips it before Qt sees it.

Qt reads a `qproperty` once, at polish. Changing the value and saving works with `watch_stylesheet`,
but removing the line keeps the old colour until restart, so set it back to a default instead of deleting it.

The compact values are padded with spaces to three characters. In a proportional font a space is
narrower than a digit, so give the labels a monospaced font if the width should not move at all.

## Example styling
```css
.traffic-menu {
    background-color: rgba(24, 25, 27, 0.85);
    min-width: 280px;
}
.traffic-menu .header {
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    background-color: rgba(24, 25, 27, 0.8);
}
.traffic-menu .header .title {
    padding: 8px;
    font-size: 16px;
    font-weight: 600;
    font-family: 'Segoe UI';
    color: #ffffff
}
.traffic-menu .header .reset-button {
    font-size: 11px;
    padding: 4px 8px;
    margin-right: 8px;
    font-family: 'Segoe UI';
    border-radius: 4px;
    font-weight: 600;
    background-color: transparent;
    border: none;
}
.traffic-menu .reset-button:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
}
.traffic-menu .reset-button:pressed {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
}
/* Speed column styles */
.traffic-menu .download-speed,
.traffic-menu .upload-speed {
    background-color: transparent;
    padding: 4px 10px;
    margin-right: 12px;
    margin-left: 12px;
    margin-top: 16px;
    margin-bottom: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}
.traffic-menu .download-speed {
    margin-left: 12px;
    margin-right: 12px;
}
.traffic-menu .speed-separator {
    max-width: 1px;
    background-color: rgba(255, 255, 255, 0.2);
    margin: 32px 0 16px 0;
}
.traffic-menu .upload-speed-value,
.traffic-menu .download-speed-value {
    font-size: 24px;
    font-weight: 900;
    font-family: 'Segoe UI';
    color: #bcc2c5;
}
.traffic-menu .upload-speed-unit,
.traffic-menu .download-speed-unit {
    font-size: 13px;
    font-family: 'Segoe UI';
    font-weight: 600;
    padding-top: 4px;
}
.traffic-menu .upload-speed-placeholder,
.traffic-menu .download-speed-placeholder {
    color: #747474;
    font-size: 11px;
    font-family: 'Segoe UI';
    padding: 0 0 4px 0;
}

/* Section and data styles */
.traffic-menu .section-title {
    font-size: 12px;
    font-weight: 600;
    color: #7c8192;
    margin-bottom: 4px;
    font-family: 'Segoe UI';
}
.traffic-menu .session-section,
.traffic-menu .today-section,
.traffic-menu .alltime-section {
    margin: 8px 8px 0 8px;
    padding: 0 10px 10px 10px;
    background-color: transparent;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.traffic-menu .data-text {
    font-size: 13px;
    color: #afb5cc;
    padding: 2px 0;
    font-family: 'Segoe UI';

}
.traffic-menu .data-value {
    font-weight: 600;
    font-size: 13px;
    font-family: 'Segoe UI';
    padding: 2px 0;
}

/* Interface and Internet info styles */
.traffic-menu .interface-info,
.traffic-menu .internet-info {
    font-size: 12px;
    color: #6f7486;
    padding: 8px 0;
    font-family: 'Segoe UI';
}
.traffic-menu .internet-info {
    background-color: rgba(68, 68, 68, 0.1);
}
.traffic-menu .internet-info.connected {
    background-color: rgba(166, 227, 161, 0.096);
    color: #a6e3a1;
}
.traffic-menu .internet-info.disconnected {
    background-color: rgba(243, 139, 168, 0.1);
    color: #f38ba8;
}
```

## Preview of the Widget
![Traffic YASB Widget](assets/d937ad0d-94feed9b-557f-b331-10e7a654c7d0.png)

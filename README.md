# Kadar

*[Bosanski](README.bs.md)*

Kadar is a screenshot and annotation tool for Linux, in the spirit of
Flameshot, built for Wayland and fractional display scaling (125 %, 150 %,
160 %, 175 % …). Select an area, draw on it, and copy, save, pin or share
it, with every pixel kept as sharp as it was on screen.

The complete application is modelled on Flameshot and was built entirely
with Claude Code (see [Credits](#credits)). It is written from scratch in
Python with GTK 4 and contains no Flameshot code. Its commands, options and
shortcuts deliberately follow Flameshot's, so you can keep your habits and
scripts when you switch. Licensed under GPL-3.0-or-later.

## Why it stays sharp with fractional scaling

Most screenshot tools on Wayland come out blurry once the display is scaled.
Kadar avoids this at every step:

- **Capture at physical resolution.** On Cinnamon, Kadar reads each monitor's
  framebuffer directly from the compositor (`Cinnamon.Eval` →
  `global.stage.capture`). The screenshot portal and `org.cinnamon.Screenshot`
  return the *logical* resolution instead. On a 2560×1440 monitor at 160 %,
  Kadar gets 2560×1440 pixels, not 1600×900.
- **One window and one image per monitor.** A monitor at 160 % and one at 200 %
  are never resampled to match each other.
- **One image pixel per screen pixel.** The overlay and pinned images are drawn
  in device pixels on GTK's fractional-scale surfaces (`wp_fractional_scale_v1`).
  This avoids GTK's downscaled-texture (mipmap) path, which blurs an image
  even when it ends up 1:1 on screen.
- **Pixel-grid placement for pins.** A window at a logical position that falls
  between device pixels (x = 301 at 160 % is pixel 481.6) gets resampled by the
  compositor. Pinned images open at a whole device pixel, and after you move
  one, Kadar shifts it by at most a couple of pixels so it lands on one again.
- **Selections in physical pixels.** The crop is pixel exact, and the size
  label (e.g. `960 × 640`) shows the real size of the image you will get.
- **Vector annotations.** Arrows, text and shapes are redrawn at full
  resolution when the image is exported, so nothing is upscaled or jagged.

## Platform support

| Environment | Capture | Notes |
|---|---|---|
| Cinnamon, Wayland | Compositor framebuffer, per monitor, native resolution | Primary target. Overlay and pins verified pixel exact at 160 % and 200 %. |
| Cinnamon, X11 | Same | Clipboard goes through GTK (`wl-copy` is Wayland only). X11 has no per-monitor fractional scaling. |
| sway, Hyprland, other wlroots | `grim`, per output, native resolution | Pins are not placed or kept on top. |
| GNOME, KDE Plasma | xdg-desktop-portal | May ask for screenshot permission once. With mixed monitor scales, the portal returns one image at the highest scale, so lower-scale monitors are slightly softer. Pins are not placed or kept on top. |

Only Cinnamon on Wayland has been tested on real hardware. The rest is
supported by design.

## Requirements

- Python 3 with PyGObject (`python3-gi`) and pycairo
- GTK 4.14 or newer
- `wl-clipboard` (`wl-copy`), for the clipboard on Wayland
- `gir1.2-xapp-1.0`, for the tray icon (optional)
- `grim`, on wlroots compositors only

All of these are installed by default on Linux Mint.

## Installation

```bash
git clone https://github.com/zelimir86/kadar.git && cd kadar && ./install.sh
```

This links `~/.local/bin/kadar` to this checkout, so code changes apply
immediately. It also installs the `.desktop` entry and the icon into
`~/.local/share`.

To make the **Print** key open Kadar (on Cinnamon this replaces an existing
`Print` custom shortcut, such as Flameshot's):

```bash
./install.sh --print-key
```

To remove it again (your settings in `~/.config/kadar` are kept):

```bash
./install.sh --uninstall
```

## Usage

| Command | What it does |
|---|---|
| `kadar` or `kadar gui` | Select an area and annotate it |
| `kadar full` | Capture all monitors (see `quick_action`) |
| `kadar screen` | Capture the monitor under the pointer (see `quick_action`) |
| `kadar screen -n 0 -p ~/Pictures` | Capture monitor 0 to a file |
| `kadar launcher` | Window to pick the area, a delay and what to do afterwards |
| `kadar config` | Settings |
| `kadar tray` | Tray icon (left click: screenshot, middle click: launcher, right click: menu) |

### Options

These are shared by `gui`, `full` and `screen`:

| Option | Meaning |
|---|---|
| `-p, --path PATH` | Save to this file or folder (a folder uses the file name pattern) |
| `-c, --clipboard` | Copy to the clipboard |
| `-r, --raw` | Write the PNG to stdout |
| `-d, --delay MS` | Wait this many milliseconds before capturing |
| `--pin` | Pin the capture to the desktop |
| `-u, --upload` | Upload to Imgur (needs a client ID, see below) |

Extra options for `gui`:

| Option | Meaning |
|---|---|
| `-s, --accept-on-select` | Accept as soon as the mouse button is released |
| `--region WxH+X+Y` | Start with this region selected (logical desktop coordinates) |
| `--last-region` | Start with the previously selected region |

Extra option for `screen`: `-n, --number N` picks the monitor index. Without
it, Kadar uses the monitor under the pointer.

When `full` or `screen` runs without `-p`, `-c`, `-r`, `--pin` or `-u`, it
does what the **quick_action** setting says: copy (the default), save, or
both.

Examples:

```bash
kadar gui -d 2000                      # select after a 2 s delay
kadar gui --accept-on-select -c        # select once, straight to the clipboard
kadar full -p ~/Pictures/desktop.png   # all monitors to a file
kadar screen -r > monitor.png          # monitor under the pointer to stdout
```

## The capture overlay

When the overlay opens, drag to select an area. Drag the handles to resize
the selection, or drag inside it to move it. The toolbar appears next to the
selection.

### Tools

| Key | Tool | Notes |
|---|---|---|
| P | Pencil | Freehand |
| D | Line | Shift snaps to 45° |
| A | Arrow | Shift snaps to 45° |
| S | Rectangle | Outline. Shift makes a square |
| R | Filled rectangle | Shift makes a square |
| C | Ellipse | Shift makes a circle |
| M | Marker | Translucent highlighter line |
| T | Text | Click to place. Enter adds a new line. Esc or Ctrl+Enter finishes. Full Unicode input |
| B | Pixelate | Block size follows the thickness |
| N | Counter | Numbered circles (1, 2, 3 …), renumbered automatically |
| I | Invert | Inverts the colors in a rectangle |

Press a tool's key again, or press Ctrl+M, to go back to no tool.

### Actions

| Key | Action |
|---|---|
| Enter | Accept: copy to the clipboard by default (see `accept_action`). Without a selection, captures the whole monitor |
| Ctrl+C | Copy to the clipboard |
| Ctrl+S | Save (with a dialog, or straight to the folder) |
| Ctrl+P | Pin to the desktop |
| Ctrl+O | Open with an application |
| Ctrl+U | Upload to Imgur |
| Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) | Undo / redo |
| Ctrl+A | Select the whole monitor |
| Delete | Delete the selected object |
| Space | Toggle the tool settings panel |
| Esc / Ctrl+Q | Cancel |

### Mouse and keyboard details

- **Right click** opens the color wheel. Either release over a color, or click
  once to keep it open and then click a color.
- **Mouse wheel** or **+ / −** changes the thickness, or the font size for
  text.
- **Arrow keys** move the selection by one physical pixel (Alt: 10 px).
  **Shift + arrows** resize it.
- **With no tool selected**, clicking a drawn object selects it. You can then
  drag it, delete it, or change its color and thickness.
- **Space** opens a panel with a color palette, a custom color picker, a hex
  entry, an eyedropper ("Pick") and thickness and font size sliders.
- An optional **magnifier** shows the pixels under the pointer with their
  coordinates and color (Settings → Interface).

Selections stay on one monitor, as with Flameshot on Wayland.

## Pinned images

A pin is a borderless window showing the capture at its original size and
position, kept above other windows (on Cinnamon).

- Drag to move it.
- Mouse wheel zooms. Press 0 to reset the zoom.
- Ctrl + mouse wheel changes the opacity.
- Double click, middle click or Esc closes it.
- Right click opens a menu (copy, save, original size, opacity, close).
- Ctrl+C copies it and Ctrl+S saves it.

## Configuration

Run `kadar config`, or edit `~/.config/kadar/config.json`. On first run,
Kadar imports colors, the save folder, the overlay opacity and a few options
from `~/.config/flameshot/flameshot.ini`, if it exists.

| Key | Default | Meaning |
|---|---|---|
| `ui_color` | `#2fbfdf` | Selection border, handles and toolbar buttons |
| `contrast_ui_color` | `#270ac1` | Active tool button |
| `contrast_opacity` | `190` | Darkening outside the selection (0–255) |
| `draw_color` | `#ff0000` | Current drawing color (remembered) |
| `draw_thickness` | `3` | Current thickness (remembered) |
| `font_size` | `22` | Text size in logical pixels |
| `font_family` | `Sans` | Text font |
| `user_colors` | 11 colors | Colors in the color wheel and palette |
| `save_path` | Pictures folder | Default folder for saving |
| `filename_pattern` | `Screenshot_%Y-%m-%d_%H-%M-%S` | `strftime` pattern for file names |
| `save_format` | `png` | `png`, `jpg`, `webp` or `bmp` |
| `jpeg_quality` | `92` | JPEG quality |
| `save_dialog` | `true` | Ask where to save. If false, save straight to `save_path` |
| `copy_path_after_save` | `false` | Copy the saved file's path to the clipboard |
| `accept_action` | `copy` | What Enter does in the overlay: `copy`, `save` or `copy_save` |
| `quick_action` | `copy` | What `full`/`screen` do without options: `copy`, `save` or `copy_save` |
| `show_notifications` | `true` | Desktop notifications after copying or saving |
| `show_help` | `true` | Help box when the overlay opens |
| `show_magnifier` | `false` | Magnifier while selecting |
| `copy_on_double_click` | `false` | Double click inside the selection copies it |
| `save_last_region` | `false` | Always start with the last selected region |
| `capture_active_monitor` | `false` | Open the overlay only on the monitor under the pointer (Cinnamon) |
| `capture_backend` | `auto` | `auto`, `cinnamon`, `grim` or `portal` |
| `buttons` | all | Which toolbar buttons to show, in order |
| `imgur_client_id` | empty | Imgur API client ID. The upload button is hidden while this is empty |

The settings window can also start the tray icon at login, by writing
`~/.config/autostart/kadar-tray.desktop`.

## Clipboard

On Wayland, Kadar hands the image to `wl-copy`, which keeps serving it after
Kadar exits. This also works from the command line (`kadar full -c`), where
there is no window. Applications receive `image/png`.

Without `wl-copy`, and on X11, Kadar uses the GTK clipboard instead. It then
stays running in the background until another application takes over the
clipboard.

## Uploading

Imgur uploads need your own client ID. Register an application at
<https://api.imgur.com/oauth2/addclient> and paste the ID into Settings →
General → Upload. When an upload finishes, the link is copied to the
clipboard and shown in a notification.

## Troubleshooting

- **"Screenshot failed" notification.** Kadar tried each capture backend
  and all of them failed. Run `kadar full -p /tmp/test.png` in a terminal to
  see the error. On Cinnamon, you can force a backend with `capture_backend`.
- **Blurry results on GNOME/KDE with mixed scales.** This is a limit of the
  portal, which returns one image at the highest scale.
- **Nothing in the clipboard.** Check that `wl-copy` is installed
  (`sudo apt install wl-clipboard`).
- **Debugging captures.** `KADAR_DUMP=/some/dir kadar gui` writes the raw
  capture of every monitor to that folder.

## Project layout

```
bin/kadar           launcher script (resolves symlinks to find the package)
kadar/main.py       command line parsing
kadar/app.py        GTK application, capture commands and post-capture actions
kadar/capture.py    capture backends (Cinnamon, grim, portal) and monitor mapping
kadar/overlay.py    overlay windows, selection, toolbar, side panel, shortcuts
kadar/tools.py      annotation objects (drawn with cairo/Pango)
kadar/icons.py      toolbar icons drawn as vectors
kadar/pin.py        pinned image windows
kadar/output.py     saving, clipboard, notifications, upload
kadar/dialogs.py    launcher, settings and "open with" windows
kadar/tray.py       tray icon (separate GTK 3 process, XApp.StatusIcon)
kadar/config.py     settings and Flameshot import
data/               .desktop entry and icon
install.sh          per-user install / uninstall
LICENSE             GNU GPL version 3
```

## Credits

- **Modelled on Flameshot.** Kadar's whole feature set, workflow, keyboard
  shortcuts and command line are modelled on
  [Flameshot](https://github.com/flameshot-org/flameshot). Kadar is an
  independent implementation and contains no Flameshot source code. It is not
  affiliated with or endorsed by the Flameshot project.
- **Built entirely with Claude Code.** All of Kadar's code, tests and
  documentation were written with [Claude Code](https://claude.com/claude-code),
  Anthropic's AI coding agent, under the direction of Želimir Stevanović.

## License

Copyright (C) 2026 Želimir Stevanović

Kadar is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

Kadar is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
A PARTICULAR PURPOSE. See the [LICENSE](LICENSE) file for the full text.

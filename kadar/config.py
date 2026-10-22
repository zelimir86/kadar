# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Settings stored as JSON in ~/.config/kadar/config.json."""

import configparser
import json
import os

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'kadar')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
STATE_FILE = os.path.join(CONFIG_DIR, 'state.json')
CACHE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'kadar')

# Toolbar buttons in display order.
ALL_BUTTONS = [
    'pencil', 'line', 'arrow', 'rect', 'rect_filled', 'circle', 'marker', 'text',
    'pixelate', 'counter', 'invert', 'move', 'undo', 'redo', 'copy', 'save',
    'pin', 'open_with', 'upload', 'side_panel', 'exit',
]


def _pictures_dir():
    try:
        out = os.popen('xdg-user-dir PICTURES 2>/dev/null').read().strip()
        if out and os.path.isdir(out):
            return out
    except OSError:
        pass
    return os.path.expanduser('~/Pictures')


DEFAULTS = {
    'ui_color': '#2fbfdf',
    'contrast_ui_color': '#270ac1',
    'contrast_opacity': 190,
    'draw_color': '#ff0000',
    'draw_thickness': 3,
    'font_size': 22,
    'font_family': 'Sans',
    'user_colors': ['#ff0000', '#ff8000', '#ffd500', '#00c000', '#00b5d8', '#0050ff',
                    '#8a2be2', '#ff00c8', '#ffffff', '#808080', '#000000'],
    'save_path': '',
    'filename_pattern': 'Screenshot_%Y-%m-%d_%H-%M-%S',
    'save_format': 'png',
    'jpeg_quality': 92,
    'save_dialog': True,
    'copy_path_after_save': False,
    'show_notifications': True,
    'show_help': True,
    'show_magnifier': False,
    'copy_on_double_click': False,
    'save_last_region': False,
    'accept_action': 'copy',          # copy | save | copy_save
    'quick_action': 'copy',           # full/screen without -p/-c: copy | save | copy_save
    'capture_active_monitor': False,
    'capture_backend': 'auto',        # auto | cinnamon | grim | portal
    'buttons': list(ALL_BUTTONS),
    'imgur_client_id': '',
    'tray_autostart': False,
}


def _import_flameshot(cfg):
    path = os.path.expanduser('~/.config/flameshot/flameshot.ini')
    if not os.path.exists(path):
        return
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path)
    except configparser.Error:
        return
    if 'General' not in cp:
        return
    g = cp['General']

    def b(key):
        return g.get(key, '').strip().lower() == 'true'

    mapping = {
        'uiColor': 'ui_color', 'contrastUiColor': 'contrast_ui_color',
        'drawColor': 'draw_color', 'savePath': 'save_path',
    }
    for src, dst in mapping.items():
        if g.get(src):
            cfg[dst] = g[src]
    for src, dst in (('contrastOpacity', 'contrast_opacity'), ('drawThickness', 'draw_thickness')):
        try:
            cfg[dst] = int(g[src])
        except (KeyError, ValueError):
            pass
    for src, dst in (('showHelp', 'show_help'), ('copyPathAfterSave', 'copy_path_after_save'),
                     ('showDesktopNotification', 'show_notifications'),
                     ('showMagnifier', 'show_magnifier'), ('copyOnDoubleClick', 'copy_on_double_click'),
                     ('saveLastRegion', 'save_last_region'), ('captureActiveMonitor', 'capture_active_monitor')):
        if src in g:
            cfg[dst] = b(src)
    if 'savePathFixed' in g:
        cfg['save_dialog'] = not b('savePathFixed')


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    self.update(json.load(f))
            except (OSError, ValueError):
                pass
        else:
            _import_flameshot(self)
            self.save()
        if not self.get('save_path'):
            self['save_path'] = _pictures_dir()

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(dict(self), f, indent=2)
        os.replace(tmp, CONFIG_FILE)

    def set(self, key, value):
        self[key] = value
        self.save()


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

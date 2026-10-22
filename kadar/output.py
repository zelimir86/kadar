# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Saving, clipboard, notifications and upload."""

import io
import json
import os
import shutil
import subprocess
import threading
import time
import base64
import urllib.parse
import urllib.request

import cairo
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from .capture import surface_to_texture
from .config import CACHE_DIR

FORMATS = {'png': 'png', 'jpg': 'jpeg', 'jpeg': 'jpeg', 'bmp': 'bmp', 'webp': 'webp',
           'tif': 'tiff', 'tiff': 'tiff', 'ico': 'ico'}


def default_filename(config):
    name = time.strftime(config.get('filename_pattern') or 'Screenshot_%Y-%m-%d_%H-%M-%S')
    return f"{name}.{config.get('save_format') or 'png'}"


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f'{base}_{i}{ext}'):
        i += 1
    return f'{base}_{i}{ext}'


def resolve_target(path, config):
    """-p accepts a directory or a file name."""
    path = os.path.expanduser(path)
    if os.path.isdir(path) or path.endswith('/'):
        os.makedirs(path, exist_ok=True)
        return unique_path(os.path.join(path, default_filename(config)))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.splitext(path)[1]:
        path += '.png'
    return path


def png_bytes(surface):
    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()


def save_surface(surface, path, config):
    ext = os.path.splitext(path)[1].lower().lstrip('.') or 'png'
    fmt = FORMATS.get(ext, 'png')
    if fmt == 'png':
        surface.write_to_png(path)
        return path
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(png_bytes(surface))
    loader.close()
    pb = loader.get_pixbuf()
    keys, vals = [], []
    if fmt == 'jpeg':
        keys, vals = ['quality'], [str(config.get('jpeg_quality', 92))]
    pb.savev(path, fmt, keys, vals)
    return path


class ClipboardKeeper:
    """Puts captures on the clipboard.

    Prefers wl-copy: Cinnamon ignores GDK's set_selection unless it comes
    straight from an input event, and the CLI commands have no window at all.
    wl-copy also keeps serving the data after Kadar exits. Without it, GDK
    serves the clipboard, so Kadar keeps running until something else takes
    the clipboard over.
    """

    def __init__(self, app):
        self.app = app
        self.held = False
        self.handler = None
        self.clipboard = Gdk.Display.get_default().get_clipboard()

    def set_texture(self, surface):
        if self._wl_copy(png_bytes(surface), 'image/png'):
            return
        # Typed as GdkTexture, not GdkMemoryTexture: GDK's image/png (and
        # other image) serializers are registered for the base type only.
        value = GObject.Value(Gdk.Texture, surface_to_texture(surface))
        self.clipboard.set_content(Gdk.ContentProvider.new_for_value(value))
        self._hold()

    def set_text(self, text):
        if self._wl_copy(text.encode(), 'text/plain;charset=utf-8'):
            return
        self.clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
        self._hold()

    @staticmethod
    def _wl_copy(data, mime):
        if not os.environ.get('WAYLAND_DISPLAY') or not shutil.which('wl-copy'):
            return False
        try:
            p = subprocess.Popen(['wl-copy', '--type', mime], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            p.communicate(data, timeout=10)
            return p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _hold(self):
        if not self.held:
            self.app.hold()
            self.held = True
            self.handler = self.clipboard.connect('changed', self._changed)

    def _changed(self, cb):
        if not cb.is_local() and self.held:
            cb.disconnect(self.handler)
            self.held = False
            self.app.release()


def notify(config, summary, body='', icon=None, force=False):
    if not (config.get('show_notifications', True) or force):
        return
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {}
        if icon and os.path.exists(icon):
            hints['image-path'] = GLib.Variant('s', 'file://' + icon)
        bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                      'org.freedesktop.Notifications', 'Notify',
                      GLib.Variant('(susssasa{sv}i)', ('Kadar', 0, 'kadar', summary, body, [],
                                                       hints, 4000)),
                      None, Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.Error:
        pass


def temp_image(surface):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, time.strftime('kadar_%Y-%m-%d_%H-%M-%S.png'))
    surface.write_to_png(path)
    return path


def upload_imgur(surface, client_id, done):
    """Upload in a thread; done(url_or_None, error_or_None) runs on the main loop."""
    data = base64.b64encode(png_bytes(surface))

    def work():
        try:
            req = urllib.request.Request(
                'https://api.imgur.com/3/image',
                data=urllib.parse.urlencode({'image': data, 'type': 'base64'}).encode(),
                headers={'Authorization': 'Client-ID ' + client_id})
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
            GLib.idle_add(done, res['data']['link'], None)
        except Exception as e:  # report any network/API failure to the user
            GLib.idle_add(done, None, str(e))

    threading.Thread(target=work, daemon=True).start()

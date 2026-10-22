# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Pinned screenshots: small borderless always-on-top image windows."""

import math
import uuid

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gsk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

from . import output  # noqa: E402
from .capture import cinnamon_pin_window, is_cinnamon, surface_to_texture  # noqa: E402
from .tools import hex_to_rgba  # noqa: E402

BORDER = 2          # logical pixels


def aligned(n, scale):
    """Smallest whole logical size >= n that is also a whole number of device pixels.

    On a 160% monitor a 401 px wide window is 641.6 device pixels, and the
    compositor has to resample it; 400 or 405 map exactly.
    """
    n = math.ceil(n - 1e-6)
    for k in range(n, n + 241):
        if abs(k * scale - round(k * scale)) < 1e-6:
            return k
    return n


def aligned_below(n, scale):
    """Largest whole logical offset <= n that is a whole number of device pixels."""
    k = math.floor(n + 1e-6)
    while k > -240 and abs(k * scale - round(k * scale)) >= 1e-6:
        k -= 1
    return k


def draw_device_texture(snap, texture, scale, x, y, w, h, filt):
    """Draw a texture at a rectangle given in device pixels.

    Given in logical units, a texture larger than its logical rectangle counts
    as downscaled, and GSK samples a lower-resolution mipmap of it, which
    blurs it even though it ends up 1:1 on screen.
    """
    snap.save()
    snap.scale(1 / scale, 1 / scale)
    snap.append_scaled_texture(texture, filt, Graphene.Rect().init(x, y, w, h))
    snap.restore()


class PinView(Gtk.Widget):
    def __init__(self, win):
        super().__init__()
        self.win = win

    def do_snapshot(self, snap):
        win = self.win
        s = win.scale
        ox, oy = win.off
        iw, ih = win.image_px()
        # Every edge falls on a device pixel, so at zoom 1 each image pixel is
        # exactly one screen pixel.
        filt = Gsk.ScalingFilter.NEAREST if win.zoom == 1.0 else Gsk.ScalingFilter.LINEAR
        draw_device_texture(snap, win.texture, s, ox, oy, iw, ih, filt)
        b = win.bdev
        cr = snap.append_cairo(Graphene.Rect().init(0, 0, self.get_width(), self.get_height()))
        cr.set_source_rgba(*hex_to_rgba(win.config.get('ui_color', '#2fbfdf')))
        cr.set_line_width(b / s)
        cr.rectangle((ox - b / 2) / s, (oy - b / 2) / s, (iw + b) / s, (ih + b) / s)
        cr.stroke()


class PinWindow(Gtk.ApplicationWindow):
    def __init__(self, app, surface, scale, anchor=None):
        """anchor: (monitor_x, monitor_y, px_x, px_y, comp_scale) — the
        monitor's origin in compositor coordinates, where the image sat on it
        in device pixels, and device pixels per compositor unit."""
        super().__init__(application=app)
        self.app = app
        self.config = app.config
        self.surface = surface
        self.texture = surface_to_texture(surface)
        self.px_w = surface.get_width()
        self.px_h = surface.get_height()
        self.scale = scale
        self.zoom = 1.0
        self.anchor = anchor
        self.position = None
        self.bdev = max(1, round(BORDER * scale))
        self.off = (self.bdev, self.bdev)
        if anchor:
            mx, my, px, py, cs = anchor
            rx = aligned_below((px - self.bdev) / cs, cs)
            ry = aligned_below((py - self.bdev) / cs, cs)
            self.off = (px - round(rx * cs), py - round(ry * cs))
            self.position = (mx + rx, my + ry)
        self.anchor_scale = scale
        self.anchor_off = self.off
        self.title = 'Kadar pin ' + uuid.uuid4().hex[:8]
        self.set_title(self.title)
        self.set_decorated(False)
        self.add_css_class('kadar-pin')
        self._resize()

        view = PinView(self)
        self.set_child(view)

        press = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        press.connect('pressed', self._on_press)
        view.add_controller(press)

        middle = Gtk.GestureClick(button=Gdk.BUTTON_MIDDLE)
        middle.connect('pressed', lambda *a: self.close())
        view.add_controller(middle)

        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect('pressed', self._on_menu)
        view.add_controller(right)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL
                                           | Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect('scroll', self._on_scroll)
        view.add_controller(scroll)

        key = Gtk.EventControllerKey()
        key.connect('key-pressed', self._on_key)
        self.add_controller(key)

        group = Gio.SimpleActionGroup()
        for name, cb in (('copy', self.copy), ('save', self.save), ('close', lambda: self.close()),
                         ('reset', self.reset_zoom), ('opacity_up', lambda: self.change_opacity(0.1)),
                         ('opacity_down', lambda: self.change_opacity(-0.1))):
            act = Gio.SimpleAction.new(name, None)
            act.connect('activate', lambda _a, _p, cb=cb: cb())
            group.add_action(act)
        self.insert_action_group('pin', group)

        menu = Gio.Menu()
        menu.append('Copy to clipboard', 'pin.copy')
        menu.append('Save as…', 'pin.save')
        sec = Gio.Menu()
        sec.append('Original size', 'pin.reset')
        sec.append('More opaque', 'pin.opacity_up')
        sec.append('More transparent', 'pin.opacity_down')
        menu.append_section(None, sec)
        last = Gio.Menu()
        last.append('Close', 'pin.close')
        menu.append_section(None, last)
        self.popover = Gtk.PopoverMenu.new_from_model(menu)
        self.popover.set_parent(view)
        self.popover.set_has_arrow(False)
        self.connect('destroy', lambda *_: self.popover.unparent())

        self.connect('map', self._on_map)

    def image_px(self):
        return round(self.px_w * self.zoom), round(self.px_h * self.zoom)

    def _resize(self):
        iw, ih = self.image_px()
        ox, oy = self.off
        w = aligned((ox + iw + self.bdev) / self.scale, self.scale)
        h = aligned((oy + ih + self.bdev) / self.scale, self.scale)
        self.set_default_size(w, h)
        self.set_size_request(w, h)
        self.queue_draw()

    def _on_map(self, *_):
        surface = self.get_surface()
        surface.connect('notify::scale', self._on_scale)
        self._on_scale(surface)
        if is_cinnamon():
            GLib.timeout_add(120, self._place)

    def _on_scale(self, surface, *_):
        scale = surface.get_scale()
        if abs(scale - self.scale) > 1e-6:
            # Moved to a monitor with another scale: re-fit to its pixel grid.
            # The window may first map on another monitor before it is placed.
            self.scale = scale
            self.bdev = max(1, round(BORDER * scale))
            if abs(scale - self.anchor_scale) < 1e-6:
                self.off = self.anchor_off
            else:
                self.off = (self.bdev, self.bdev)
            self._resize()

    def _place(self):
        x = y = None
        if self.position:
            x, y = self.position
        cinnamon_pin_window(self.title, x, y)
        return False

    def _on_press(self, gesture, n_press, x, y):
        if n_press == 2:
            self.close()
            return
        surface = self.get_surface()
        if surface is not None:
            surface.begin_move(gesture.get_device(), gesture.get_current_button(), x, y,
                               gesture.get_current_event_time())

    def _on_menu(self, gesture, n_press, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _on_scroll(self, ctrl, dx, dy):
        state = ctrl.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            self.change_opacity(-0.1 if dy > 0 else 0.1)
        else:
            self.zoom = min(8.0, max(0.1, self.zoom * (0.9 if dy > 0 else 1.1)))
            self._resize()
        return True

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif state & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy()
        elif state & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.save()
        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.reset_zoom()
        else:
            return False
        return True

    def reset_zoom(self):
        self.zoom = 1.0
        self._resize()

    def change_opacity(self, delta):
        self.set_opacity(min(1.0, max(0.15, self.get_opacity() + delta)))

    def copy(self):
        self.app.clipboard.set_texture(self.surface)
        output.notify(self.config, 'Capture copied to clipboard')

    def save(self):
        self.app.save_with_dialog(self.surface, parent=self)

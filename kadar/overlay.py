# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""The interactive capture overlay: one fullscreen window per monitor."""

import copy
import json
import math
import time

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gsk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango, PangoCairo  # noqa: E402

from . import output  # noqa: E402
from .config import load_state, save_state  # noqa: E402
from .icons import Icon  # noqa: E402
from .pin import draw_device_texture  # noqa: E402
from .tools import (TOOL_CLASSES, TOOL_NAMES, DrawContext, Text, hex_to_rgba,  # noqa: E402
                    luminance, rgba_to_hex, _layout)

HANDLES = ('nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w')
HANDLE_HIT = 11
DRAG_MODES = ('create', 'resize', 'move_sel', 'draw', 'move_ann')

TOOL_KEYS = {
    Gdk.KEY_p: 'pencil', Gdk.KEY_d: 'line', Gdk.KEY_a: 'arrow', Gdk.KEY_s: 'rect',
    Gdk.KEY_r: 'rect_filled', Gdk.KEY_c: 'circle', Gdk.KEY_m: 'marker', Gdk.KEY_t: 'text',
    Gdk.KEY_b: 'pixelate', Gdk.KEY_n: 'counter', Gdk.KEY_i: 'invert',
}
TOOL_SHORTCUTS = {v: chr(Gdk.keyval_to_unicode(k)).upper() for k, v in TOOL_KEYS.items()}

ACTIONS = {
    'move': ('Move / select objects', 'Ctrl+M'), 'undo': ('Undo', 'Ctrl+Z'),
    'redo': ('Redo', 'Ctrl+Shift+Z'), 'copy': ('Copy to clipboard', 'Ctrl+C'),
    'save': ('Save', 'Ctrl+S'), 'pin': ('Pin to desktop', 'Ctrl+P'),
    'open_with': ('Open with application', 'Ctrl+O'), 'upload': ('Upload to Imgur', 'Ctrl+U'),
    'side_panel': ('Tool settings', 'Space'), 'exit': ('Exit', 'Esc'),
}

HELP_LINES = [
    ('Drag', 'select an area'),
    ('Enter', 'capture the whole screen / accept'),
    ('Right click', 'color picker'),
    ('Mouse wheel', 'thickness'),
    ('Space', 'tool settings'),
    ('Esc', 'cancel'),
]


def R(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


# =========================================================================== Canvas

class Canvas(Gtk.Widget):
    def __init__(self, session, shot):
        super().__init__()
        self.session = session
        self.shot = shot
        self.sel = None              # [x, y, w, h] in physical image pixels
        self.ctx = DrawContext(shot)
        self.annotations = self.ctx.annotations
        self.undo_stack = []
        self.redo_stack = []
        self.selected = None         # annotation picked with the move tool
        self.current = None          # annotation being drawn
        self.editing = None          # Text being typed
        self.mode = None
        self.drag = {}
        self.pointer = None
        self.wheel = None            # color wheel centre while it is open
        self.wheel_hover = None
        self.wheel_sticky = False
        self.size_preview_until = 0

        self.set_focusable(True)
        self.set_cursor_from_name('crosshair')
        self.connect('realize', self._on_realize)

        d1 = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        d1.connect('drag-begin', self._on_drag_begin)
        d1.connect('drag-update', self._on_drag_update)
        d1.connect('drag-end', self._on_drag_end)
        self.add_controller(d1)

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect('pressed', self._on_click)
        self.add_controller(click)

        d3 = Gtk.GestureDrag(button=Gdk.BUTTON_SECONDARY)
        d3.connect('drag-begin', self._on_wheel_begin)
        d3.connect('drag-update', self._on_wheel_update)
        d3.connect('drag-end', self._on_wheel_end)
        self.add_controller(d3)

        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('enter', self._on_enter)
        motion.connect('leave', self._on_leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL
                                           | Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect('scroll', self._on_scroll)
        self.add_controller(scroll)

    def _on_realize(self, *_):
        # GTK reuses render nodes across scale changes, but the background is
        # drawn in device pixels, so it has to be redrawn for the new scale.
        self.get_native().get_surface().connect('notify::scale', lambda *a: self.queue_draw())

    # ----------------------------------------------------------------- geometry

    def to_px(self, x, y):
        px = min(max(round(x * self.shot.sx), 0), self.shot.px_w)
        py = min(max(round(y * self.shot.sy), 0), self.shot.px_h)
        return px, py

    def sel_logical(self):
        x, y, w, h = self.sel
        sx, sy = self.shot.sx, self.shot.sy
        return x / sx, y / sy, w / sx, h / sy

    def handle_points(self):
        x, y, w, h = self.sel_logical()
        return {
            'nw': (x, y), 'n': (x + w / 2, y), 'ne': (x + w, y), 'e': (x + w, y + h / 2),
            'se': (x + w, y + h), 's': (x + w / 2, y + h), 'sw': (x, y + h), 'w': (x, y + h / 2),
        }

    def handle_at(self, x, y):
        if not self.sel:
            return None
        best, best_d = None, HANDLE_HIT
        for name, (hx, hy) in self.handle_points().items():
            d = math.hypot(x - hx, y - hy)
            if d <= best_d:
                best, best_d = name, d
        return best

    def in_sel(self, x, y):
        if not self.sel:
            return False
        lx, ly, lw, lh = self.sel_logical()
        return lx <= x <= lx + lw and ly <= y <= ly + lh

    def annotation_at(self, x, y):
        for a in reversed(self.annotations):
            if a.hit(x, y):
                return a
        return None

    def select_all(self):
        self.session.claim(self)
        self.sel = [0, 0, self.shot.px_w, self.shot.px_h]
        self.session.sync_ui()
        self.queue_draw()

    def nudge(self, dx, dy, resize=False):
        if not self.sel:
            return
        x, y, w, h = self.sel
        if resize:
            w = max(1, min(w + dx, self.shot.px_w - x))
            h = max(1, min(h + dy, self.shot.px_h - y))
        else:
            x = min(max(x + dx, 0), self.shot.px_w - w)
            y = min(max(y + dy, 0), self.shot.px_h - h)
        self.sel = [x, y, w, h]
        self.session.sync_ui()
        self.queue_draw()

    # ----------------------------------------------------------------- annotations

    def push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.annotations))
        self.redo_stack.clear()

    def _set_annotations(self, lst):
        self.annotations = lst
        self.ctx.annotations = lst
        self.selected = None

    def undo(self):
        self.finish_text()
        if self.undo_stack:
            self.redo_stack.append(self.annotations)
            self._set_annotations(self.undo_stack.pop())
            self.queue_draw()

    def redo(self):
        self.finish_text()
        if self.redo_stack:
            self.undo_stack.append(self.annotations)
            self._set_annotations(self.redo_stack.pop())
            self.queue_draw()

    def delete_selected(self):
        if self.selected in self.annotations:
            self.push_undo()
            self.annotations.remove(self.selected)
            self.selected = None
            self.queue_draw()
            return True
        return False

    def clear(self):
        self.finish_text()
        self.sel = None
        self.selected = None
        self.current = None
        self.mode = None
        if self.annotations:
            self.push_undo()
            self.annotations.clear()
        self.queue_draw()

    def restyle_target(self):
        """The object that color/size changes apply to right now."""
        if self.editing:
            return self.editing
        return self.selected

    def start_text(self, x, y):
        s = self.session
        t = Text(s.color, s.font_size, x, y - s.font_size * 0.6, s.config.get('font_family', 'Sans'))
        self.push_undo()
        self.annotations.append(t)
        self.editing = t
        self.ctx.editing = t
        s.begin_text(self)
        self.queue_draw()

    def finish_text(self):
        t = self.editing
        if not t:
            return
        self.editing = None
        self.ctx.editing = None
        if t.is_empty():
            if t in self.annotations:
                self.annotations.remove(t)
            if self.undo_stack:
                self.undo_stack.pop()
        self.session.end_text(self)
        self.queue_draw()

    # ----------------------------------------------------------------- render

    def render(self):
        """Selection (or whole monitor) with annotations, at physical resolution."""
        self.finish_text()
        if self.sel:
            x, y, w, h = self.sel
        else:
            x, y, w, h = 0, 0, self.shot.px_w, self.shot.px_h
        out = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        cr = cairo.Context(out)
        cr.set_source_surface(self.shot.surface, -x, -y)
        cr.paint()
        cr.translate(-x, -y)
        cr.scale(self.shot.sx, self.shot.sy)
        for a in self.annotations:
            cr.save()
            a.draw(cr, self.ctx)
            cr.restore()
        out.flush()
        return out

    def sel_global_logical(self):
        """Selection rectangle in global compositor coordinates."""
        if self.sel:
            lx, ly, lw, lh = self.sel_logical()
        else:
            lx, ly, lw, lh = 0, 0, self.shot.width, self.shot.height
        return self.shot.x + lx, self.shot.y + ly, lw, lh

    # ----------------------------------------------------------------- input: primary button

    def _state(self, gesture):
        return gesture.get_current_event_state() or Gdk.ModifierType(0)

    def _on_click(self, gesture, n_press, x, y):
        if n_press == 2 and not self.session.tool and self.in_sel(x, y) \
                and self.session.config.get('copy_on_double_click'):
            self.session.action('copy')

    def _on_drag_begin(self, gesture, x, y):
        s = self.session
        self.grab_focus()
        s.hover = self
        state = self._state(gesture)
        self.drag = {'start': (x, y), 'moved': False, 'shift': bool(state & Gdk.ModifierType.SHIFT_MASK)}

        if self.wheel is not None:
            self._pick_from_wheel(x, y)
            self.mode = 'none'
            return
        if s.picking_color:
            self._pick_pixel(x, y)
            self.mode = 'none'
            return
        if self.editing:
            if self.editing.hit(x, y):
                self.mode = 'none'
                return
            self.finish_text()
            if s.tool == 'text':
                self.mode = 'none'
                return

        if not self.sel or s.owner is not self:
            self._begin_create(x, y)
            return
        h = self.handle_at(x, y)
        if h:
            self.mode = 'resize'
            self.drag['handle'] = h
            self.drag['orig'] = list(self.sel)
            s.sync_ui()
            return
        if s.tool:
            self.selected = None
            if s.tool == 'text':
                self.start_text(x, y)
                self.mode = 'none'
                return
            cls = TOOL_CLASSES[s.tool]
            ann = cls(s.color, s.thickness, x, y)
            if s.tool == 'counter':
                self.push_undo()
                self.annotations.append(ann)
                self.mode = 'none'
                self.queue_draw()
                return
            self.current = ann
            self.mode = 'draw'
            s.sync_ui()
            return
        ann = self.annotation_at(x, y)
        if ann:
            self.selected = ann
            self.push_undo()
            self.mode = 'move_ann'
            self.drag['last'] = (x, y)
            s.sync_panel()
            self.queue_draw()
            return
        self.selected = None
        if self.in_sel(x, y):
            self.mode = 'move_sel'
            self.drag['orig'] = list(self.sel)
            s.sync_ui()
            return
        self._begin_create(x, y)

    def _begin_create(self, x, y):
        self.session.claim(self)
        self.selected = None
        self.mode = 'create'
        px, py = self.to_px(x, y)
        self.drag['anchor'] = (px, py)
        self.sel = [px, py, 0, 0]
        self.session.sync_ui()
        self.queue_draw()

    def _on_drag_update(self, gesture, dx, dy):
        sx0, sy0 = self.drag.get('start', (0, 0))
        x, y = sx0 + dx, sy0 + dy
        self.pointer = (x, y)
        if abs(dx) > 1 or abs(dy) > 1:
            self.drag['moved'] = True
        shift = bool(self._state(gesture) & Gdk.ModifierType.SHIFT_MASK)
        m = self.mode
        if m == 'create':
            ax, ay = self.drag['anchor']
            px, py = self.to_px(x, y)
            if shift:
                d = max(abs(px - ax), abs(py - ay))
                px = min(max(ax + (d if px >= ax else -d), 0), self.shot.px_w)
                py = min(max(ay + (d if py >= ay else -d), 0), self.shot.px_h)
            self.sel = [min(ax, px), min(ay, py), abs(px - ax), abs(py - ay)]
        elif m == 'resize':
            ox, oy, ow, oh = self.drag['orig']
            l, t, r, b = ox, oy, ox + ow, oy + oh
            ddx = round(dx * self.shot.sx)
            ddy = round(dy * self.shot.sy)
            hnd = self.drag['handle']
            if 'w' in hnd:
                l += ddx
            if 'e' in hnd:
                r += ddx
            if 'n' in hnd:
                t += ddy
            if 's' in hnd:
                b += ddy
            l, r = sorted((min(max(l, 0), self.shot.px_w), min(max(r, 0), self.shot.px_w)))
            t, b = sorted((min(max(t, 0), self.shot.px_h), min(max(b, 0), self.shot.px_h)))
            self.sel = [l, t, r - l, b - t]
        elif m == 'move_sel':
            ox, oy, ow, oh = self.drag['orig']
            nx = min(max(ox + round(dx * self.shot.sx), 0), self.shot.px_w - ow)
            ny = min(max(oy + round(dy * self.shot.sy), 0), self.shot.px_h - oh)
            self.sel = [nx, ny, ow, oh]
        elif m == 'draw' and self.current:
            self.current.update(x, y, shift)
        elif m == 'move_ann' and self.selected:
            lx, ly = self.drag['last']
            self.selected.translate(x - lx, y - ly)
            self.drag['last'] = (x, y)
        self.queue_draw()

    def _on_drag_end(self, gesture, dx, dy):
        m = self.mode
        self.mode = None
        s = self.session
        if m == 'create':
            if not self.sel or self.sel[2] < 3 or self.sel[3] < 3:
                self.sel = None
            elif s.opts.accept_on_select:
                s.sync_ui()
                s.action('accept')
                return
        elif m == 'draw' and self.current:
            ann = self.current
            self.current = None
            if not ann.is_empty():
                self.push_undo()
                self.annotations.append(ann)
        elif m == 'move_ann':
            if not self.drag.get('moved') and self.undo_stack:
                self.undo_stack.pop()
        s.sync_ui()
        self._update_cursor()
        self.queue_draw()

    def _pick_pixel(self, x, y):
        px, py = self.to_px(x, y)
        px = min(px, self.shot.px_w - 1)
        py = min(py, self.shot.px_h - 1)
        surf = self.shot.surface
        data = surf.get_data()
        o = py * surf.get_stride() + px * 4
        b, g, r = data[o], data[o + 1], data[o + 2]
        self.session.picking_color = False
        self.session.set_color((r / 255, g / 255, b / 255, 1.0))

    # ----------------------------------------------------------------- color wheel

    def wheel_geometry(self):
        colors = self.session.config.get('user_colors') or []
        n = max(1, len(colors))
        radius = max(52, n * 8)
        cx, cy = self.wheel
        cx = min(max(cx, radius + 20), self.get_width() - radius - 20)
        cy = min(max(cy, radius + 20), self.get_height() - radius - 20)
        pts = []
        for i, c in enumerate(colors):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang), c))
        return cx, cy, radius, pts

    def _wheel_hit(self, x, y):
        _, _, _, pts = self.wheel_geometry()
        for i, (px, py, _) in enumerate(pts):
            if math.hypot(x - px, y - py) <= 17:
                return i
        return None

    def _on_wheel_begin(self, gesture, x, y):
        if self.wheel is not None:
            self.wheel = None
            self.wheel_sticky = False
            self.queue_draw()
            return
        self.wheel = (x, y)
        self.wheel_hover = None
        self.wheel_sticky = False
        self.drag['wheel_start'] = (x, y)
        self.set_cursor_from_name('default')
        self.queue_draw()

    def _on_wheel_update(self, gesture, dx, dy):
        if self.wheel is None:
            return
        x0, y0 = self.drag.get('wheel_start', self.wheel)
        self.wheel_hover = self._wheel_hit(x0 + dx, y0 + dy)
        self.queue_draw()

    def _on_wheel_end(self, gesture, dx, dy):
        if self.wheel is None:
            return
        if self.wheel_hover is not None:
            self._choose_wheel(self.wheel_hover)
        else:
            self.wheel_sticky = True   # quick click: leave it open until next click
        self.queue_draw()

    def _pick_from_wheel(self, x, y):
        i = self._wheel_hit(x, y)
        if i is not None:
            self._choose_wheel(i)
        else:
            self.wheel = None
            self._update_cursor()
            self.queue_draw()

    def _choose_wheel(self, i):
        colors = self.session.config.get('user_colors') or []
        self.wheel = None
        self.wheel_hover = None
        if 0 <= i < len(colors):
            self.session.set_color(hex_to_rgba(colors[i]))
        self._update_cursor()
        self.queue_draw()

    # ----------------------------------------------------------------- hover / scroll

    def _on_enter(self, ctrl, x, y):
        self.session.hover = self
        self.pointer = (x, y)
        self.queue_draw()

    def _on_leave(self, ctrl):
        self.pointer = None
        self.queue_draw()

    def _on_motion(self, ctrl, x, y):
        self.session.hover = self
        self.pointer = (x, y)
        if self.wheel is not None and self.wheel_sticky:
            self.wheel_hover = self._wheel_hit(x, y)
        if self.mode is None:
            self._update_cursor()
        if self.session.config.get('show_magnifier') or self.wheel is not None \
                or time.monotonic() < self.size_preview_until or not self.sel:
            self.queue_draw()

    def _update_cursor(self):
        p = self.pointer
        s = self.session
        if self.wheel is not None:
            name = 'default'
        elif s.picking_color:
            name = 'crosshair'
        elif not p or not self.sel or s.owner is not self:
            name = 'crosshair'
        else:
            x, y = p
            h = self.handle_at(x, y)
            if h:
                name = h + '-resize'
            elif s.tool == 'text':
                name = 'text'
            elif s.tool:
                name = 'crosshair'
            elif self.annotation_at(x, y):
                name = 'pointer'
            elif self.in_sel(x, y):
                name = 'move'
            else:
                name = 'crosshair'
        self.set_cursor_from_name(name)

    def _on_scroll(self, ctrl, dx, dy):
        step = -1 if dy > 0 else 1
        self.session.change_size(step)
        self.size_preview_until = time.monotonic() + 0.9
        GLib.timeout_add(950, self._redraw_once)
        self.queue_draw()
        return True

    def _redraw_once(self):
        self.queue_draw()
        return False

    # ----------------------------------------------------------------- drawing

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        if w <= 0 or h <= 0:
            return
        s = self.session
        cfg = s.config
        full = R(0, 0, w, h)
        # In device pixels: drawn into the logical rect GSK would treat the
        # texture as downscaled and sample a blurry mipmap.
        # Use the scale GTK actually renders at: for scales such as 175% the
        # compositor's exact factor (2560/1463) and the protocol's 1.75 differ.
        native = self.get_native()
        surface = native.get_surface() if native else None
        scale = surface.get_scale() if surface else self.shot.sx
        # The portal backend can hand a lower-scale monitor more pixels than it
        # has (GNOME shoots every monitor at the highest scale): fit it then.
        dw = round(self.shot.width * scale)
        dh = round(self.shot.height * scale)
        exact = (dw, dh) == (self.shot.px_w, self.shot.px_h)
        draw_device_texture(snap, self.shot.texture, scale, 0, 0, dw, dh,
                            Gsk.ScalingFilter.NEAREST if exact else Gsk.ScalingFilter.LINEAR)

        if self.annotations or self.current:
            cr = snap.append_cairo(full)
            for a in self.annotations:
                cr.save()
                a.draw(cr, self.ctx)
                cr.restore()
            if self.current:
                self.current.draw(cr, self.ctx)

        dim = rgba(0, 0, 0, cfg.get('contrast_opacity', 190) / 255)
        if self.sel and self.sel[2] > 0 and self.sel[3] > 0:
            lx, ly, lw, lh = self.sel_logical()
            snap.append_color(dim, R(0, 0, w, ly))
            snap.append_color(dim, R(0, ly + lh, w, h - ly - lh))
            snap.append_color(dim, R(0, ly, lx, lh))
            snap.append_color(dim, R(lx + lw, ly, w - lx - lw, lh))
        else:
            snap.append_color(dim, full)

        cr = snap.append_cairo(full)
        ui = hex_to_rgba(cfg.get('ui_color', '#2fbfdf'))
        if self.sel:
            self._draw_selection(cr, ui)
        if self.selected and self.selected in self.annotations:
            x0, y0, x1, y1 = self.selected.bounds()
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(1.2)
            cr.set_dash([5, 4])
            cr.rectangle(x0 - 5, y0 - 5, x1 - x0 + 10, y1 - y0 + 10)
            cr.stroke()
            cr.set_dash([])
        if not s.any_selection() and cfg.get('show_help', True) and self.mode is None:
            self._draw_help(cr, w, h)
        if self.pointer and time.monotonic() < self.size_preview_until:
            self._draw_size_preview(cr)
        if self.wheel is not None:
            self._draw_wheel(cr)
        if s.picking_color and self.pointer:
            self._draw_pick_hint(cr)

        if cfg.get('show_magnifier') and self.pointer and self.wheel is None \
                and (not self.sel or self.mode in ('create', 'resize')):
            self._draw_magnifier(snap, w, h)

    def _draw_selection(self, cr, ui):
        lx, ly, lw, lh = self.sel_logical()
        scale = self.shot.sx
        bw = max(1, round(scale * 1.2)) / scale
        cr.set_source_rgba(*ui)
        cr.set_line_width(bw)
        cr.rectangle(lx - bw / 2, ly - bw / 2, lw + bw, lh + bw)
        cr.stroke()
        busy = self.mode in ('draw', 'move_ann')
        if not busy and self.session.owner is self:
            for hx, hy in self.handle_points().values():
                cr.arc(hx, hy, 4.5, 0, 2 * math.pi)
                cr.set_source_rgba(*ui)
                cr.fill_preserve()
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.set_line_width(1)
                cr.stroke()
        # Size label in physical pixels: that is the size of the saved image.
        label = f'{self.sel[2]} × {self.sel[3]}'
        layout = _layout(cr, 'Sans', 12)
        layout.set_text(label, -1)
        _, ext = layout.get_pixel_extents()
        pw, ph = ext.width + 12, ext.height + 6
        tx = lx
        ty = ly - ph - 6 if ly - ph - 6 >= 2 else ly + 6
        if ly - ph - 6 < 2:
            tx = lx + 6
        tx = min(tx, self.get_width() - pw - 2)
        _rounded_rect(cr, tx, ty, pw, ph, 4)
        cr.set_source_rgba(0, 0, 0, 0.72)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(tx + 6, ty + 3)
        PangoCairo.show_layout(cr, layout)

    def _draw_help(self, cr, w, h):
        title = _layout(cr, 'Sans Bold', 17)
        title.set_text('Kadar', -1)
        rows = []
        for key, desc in HELP_LINES:
            k = _layout(cr, 'Sans Bold', 13.5)
            k.set_text(key, -1)
            d = _layout(cr, 'Sans', 13.5)
            d.set_text(desc, -1)
            rows.append((k, d))
        kw = max(k.get_pixel_extents()[1].width for k, _ in rows)
        dw = max(d.get_pixel_extents()[1].width for _, d in rows)
        lh = rows[0][0].get_pixel_extents()[1].height + 6
        th = title.get_pixel_extents()[1].height
        bw = kw + dw + 24 + 48
        bh = th + 14 + lh * len(rows) + 36
        bx, by = (w - bw) / 2, (h - bh) / 2
        _rounded_rect(cr, bx, by, bw, bh, 12)
        cr.set_source_rgba(0.08, 0.08, 0.09, 0.82)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(bx + 24, by + 18)
        PangoCairo.show_layout(cr, title)
        y = by + 18 + th + 12
        for k, d in rows:
            cr.set_source_rgba(*hex_to_rgba(self.session.config.get('ui_color', '#2fbfdf')))
            cr.move_to(bx + 24, y)
            PangoCairo.show_layout(cr, k)
            cr.set_source_rgba(0.92, 0.92, 0.92, 1)
            cr.move_to(bx + 24 + kw + 24, y)
            PangoCairo.show_layout(cr, d)
            y += lh

    def _draw_size_preview(self, cr):
        s = self.session
        x, y = self.pointer
        tool = s.tool
        if tool == 'text' or isinstance(self.restyle_target(), Text):
            label = f'{s.font_size:g} px font'
            r = 4
        else:
            r = max(1, s.thickness / 2)
            label = f'{s.thickness:g} px'
        cr.set_source_rgba(*s.color[:3], 0.85)
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(1)
        cr.arc(x, y, r + 1, 0, 2 * math.pi)
        cr.stroke()
        layout = _layout(cr, 'Sans Bold', 12)
        layout.set_text(label, -1)
        _, ext = layout.get_pixel_extents()
        tx, ty = x + r + 10, y - ext.height / 2
        _rounded_rect(cr, tx - 5, ty - 3, ext.width + 10, ext.height + 6, 4)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, layout)

    def _draw_wheel(self, cr):
        cx, cy, radius, pts = self.wheel_geometry()
        cr.arc(cx, cy, radius + 26, 0, 2 * math.pi)
        cr.set_source_rgba(0.08, 0.08, 0.09, 0.75)
        cr.fill()
        cr.arc(cx, cy, 18, 0, 2 * math.pi)
        cr.set_source_rgba(*self.session.color)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(2)
        cr.stroke()
        for i, (px, py, c) in enumerate(pts):
            r = 16 if i == self.wheel_hover else 12
            cr.arc(px, py, r, 0, 2 * math.pi)
            cr.set_source_rgba(*hex_to_rgba(c))
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.95 if i == self.wheel_hover else 0.5)
            cr.set_line_width(2 if i == self.wheel_hover else 1)
            cr.stroke()

    def _draw_pick_hint(self, cr):
        x, y = self.pointer
        layout = _layout(cr, 'Sans', 12)
        layout.set_text('Click to pick a color', -1)
        _, ext = layout.get_pixel_extents()
        _rounded_rect(cr, x + 14, y + 14, ext.width + 12, ext.height + 6, 4)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(x + 20, y + 17)
        PangoCairo.show_layout(cr, layout)

    def _draw_magnifier(self, snap, w, h):
        x, y = self.pointer
        sx, sy = self.shot.sx, self.shot.sy
        size = 132
        zoom = 9                                   # device pixels per image pixel
        m = zoom / sx                              # logical units per image pixel
        px = min(int(x * sx), self.shot.px_w - 1)
        py = min(int(y * sy), self.shot.px_h - 1)
        mx = x + 24 if x + 24 + size < w else x - 24 - size
        my = y + 24 if y + 24 + size + 22 < h else y - 24 - size - 22
        box = R(mx, my, size, size)
        snap.push_rounded_clip(Gsk.RoundedRect().init_from_rect(box, 10))
        snap.append_color(rgba(0, 0, 0, 1), box)
        ox = mx + size / 2 - (px + 0.5) * m
        oy = my + size / 2 - (py + 0.5) * m
        snap.append_scaled_texture(self.shot.texture, Gsk.ScalingFilter.NEAREST,
                                   R(ox, oy, self.shot.px_w * m, self.shot.px_h * m))
        snap.pop()
        cr = snap.append_cairo(R(mx - 4, my - 4, size + 8, size + 34))
        _rounded_rect(cr, mx, my, size, size, 10)
        cr.set_source_rgba(*hex_to_rgba(self.session.config.get('ui_color', '#2fbfdf')))
        cr.set_line_width(2)
        cr.stroke()
        cr.rectangle(mx + size / 2 - m / 2, my + size / 2 - m / 2, m, m)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(1)
        cr.stroke()
        data = self.shot.surface.get_data()
        o = py * self.shot.surface.get_stride() + px * 4
        hexc = '#%02x%02x%02x' % (data[o + 2], data[o + 1], data[o])
        layout = _layout(cr, 'Monospace', 11)
        layout.set_text(f'{px}, {py}  {hexc}', -1)
        _, ext = layout.get_pixel_extents()
        _rounded_rect(cr, mx, my + size + 4, size, ext.height + 6, 4)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(mx + (size - ext.width) / 2, my + size + 7)
        PangoCairo.show_layout(cr, layout)


# =========================================================================== Toolbar

class Toolbar(Gtk.Box):
    def __init__(self, session):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class('kadar-toolbar')
        self.session = session
        self.tool_buttons = {}
        self.items = []
        self.rows = 1
        for name in session.config.get('buttons') or []:
            if name == 'upload' and not session.config.get('imgur_client_id'):
                continue
            if name in TOOL_CLASSES or name == 'text':
                btn = Gtk.ToggleButton()
                tip = f'{TOOL_NAMES[name]} ({TOOL_SHORTCUTS.get(name, "")})'
                btn.connect('toggled', self._on_tool_toggled, name)
                self.tool_buttons[name] = btn
            elif name in ACTIONS:
                btn = Gtk.Button()
                label, key = ACTIONS[name]
                tip = f'{label} ({key})'
                btn.connect('clicked', lambda b, n=name: session.action(n))
            else:
                continue
            btn.set_child(Icon(name))
            btn.set_tooltip_text(tip)
            btn.set_focus_on_click(False)
            btn.set_can_focus(False)
            btn.add_css_class('kadar-btn')
            if name in ('exit',):
                btn.add_css_class('kadar-exit')
            self.items.append(btn)
        self._updating = False
        self.set_rows(1)

    def set_rows(self, rows):
        self.rows = rows
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box = child
            sub = box.get_first_child()
            while sub:
                n2 = sub.get_next_sibling()
                box.remove(sub)
                sub = n2
            self.remove(box)
            child = nxt
        per_row = math.ceil(len(self.items) / rows)
        for r in range(rows):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
            row.set_halign(Gtk.Align.CENTER)
            for btn in self.items[r * per_row:(r + 1) * per_row]:
                row.append(btn)
            self.append(row)

    def _on_tool_toggled(self, btn, name):
        if self._updating:
            return
        self.session.set_tool(name if btn.get_active() else None)

    def sync(self, tool):
        self._updating = True
        for name, btn in self.tool_buttons.items():
            btn.set_active(name == tool)
        self._updating = False


# =========================================================================== Side panel

class Swatch(Gtk.Widget):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.set_size_request(20, 20)
        self.set_can_target(False)

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        cr = snap.append_cairo(R(0, 0, w, h))
        cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 2 * math.pi)
        cr.set_source_rgba(*self.color)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.set_line_width(1)
        cr.stroke()


class SidePanel(Gtk.Box):
    def __init__(self, session, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.session = session
        self.window = window
        self.add_css_class('kadar-panel')
        self.set_size_request(250, -1)
        self._updating = False

        self.tool_label = Gtk.Label(xalign=0)
        self.tool_label.add_css_class('kadar-panel-title')
        self.append(self.tool_label)

        self.append(self._caption('Color'))
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                           min_children_per_line=6, column_spacing=4, row_spacing=4)
        for c in session.config.get('user_colors') or []:
            b = Gtk.Button()
            b.add_css_class('kadar-swatch')
            b.set_child(Swatch(hex_to_rgba(c)))
            b.set_tooltip_text(c)
            b.set_can_focus(False)
            b.connect('clicked', lambda _b, c=c: session.set_color(hex_to_rgba(c)))
            grid.append(b)
        self.append(grid)

        row = Gtk.Box(spacing=6)
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        self.color_btn.connect('notify::rgba', self._on_color_btn)
        self.color_btn.set_can_focus(False)
        row.append(self.color_btn)
        self.hex_entry = Gtk.Entry(max_length=9, width_chars=8, hexpand=True)
        self.hex_entry.connect('activate', self._on_hex)
        row.append(self.hex_entry)
        pick = Gtk.Button(label='Pick')
        pick.set_tooltip_text('Pick a color from the screenshot')
        pick.set_can_focus(False)
        pick.connect('clicked', lambda _b: session.start_color_pick())
        row.append(pick)
        self.append(row)

        self.append(self._caption('Thickness'))
        self.thick = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 60, 1)
        self.thick.set_draw_value(True)
        self.thick.set_can_focus(False)
        self.thick.connect('value-changed', self._on_thick)
        self.append(self.thick)

        self.append(self._caption('Font size'))
        self.font = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 8, 160, 1)
        self.font.set_draw_value(True)
        self.font.set_can_focus(False)
        self.font.connect('value-changed', self._on_font)
        self.append(self.font)

        hint = Gtk.Label(label='Mouse wheel changes the size.\nRight click opens the color wheel.',
                         xalign=0, wrap=True)
        hint.add_css_class('kadar-panel-hint')
        self.append(hint)

    def _caption(self, text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class('kadar-panel-caption')
        return lbl

    def sync(self):
        s = self.session
        self._updating = True
        name = TOOL_NAMES.get(s.tool) if s.tool else 'No tool (move / select)'
        self.tool_label.set_text(name)
        c = s.color
        self.color_btn.set_rgba(rgba(*c[:3], 1))
        if not self.hex_entry.has_focus():
            self.hex_entry.set_text(rgba_to_hex(c))
        self.thick.set_value(s.thickness)
        self.font.set_value(s.font_size)
        self._updating = False

    def _on_color_btn(self, btn, _p):
        if self._updating:
            return
        c = btn.get_rgba()
        self.session.set_color((c.red, c.green, c.blue, 1.0))

    def _on_hex(self, entry):
        try:
            self.session.set_color(hex_to_rgba(entry.get_text().strip()))
        except ValueError:
            pass
        self.window.canvas.grab_focus()

    def _on_thick(self, scale):
        if not self._updating:
            self.session.set_thickness(int(scale.get_value()))

    def _on_font(self, scale):
        if not self._updating:
            self.session.set_font_size(int(scale.get_value()))


# =========================================================================== Window

class CaptureWindow(Gtk.ApplicationWindow):
    def __init__(self, session, shot):
        super().__init__(application=session.app)
        self.session = session
        self.shot = shot
        self.add_css_class('kadar-overlay')
        self.set_decorated(False)
        self.set_title(f'Kadar capture {shot.index}')
        self.set_default_size(shot.width, shot.height)

        self.overlay = Gtk.Overlay()
        self.canvas = Canvas(session, shot)
        self.overlay.set_child(self.canvas)

        self.toolbar = Toolbar(session)
        self.toolbar.set_halign(Gtk.Align.START)
        self.toolbar.set_valign(Gtk.Align.START)
        self.toolbar.set_visible(False)
        self.overlay.add_overlay(self.toolbar)

        self.panel = SidePanel(session, self)
        self.panel.set_halign(Gtk.Align.START)
        self.panel.set_valign(Gtk.Align.CENTER)
        self.panel.set_margin_start(24)
        self.panel.set_visible(False)
        self.overlay.add_overlay(self.panel)
        self.set_child(self.overlay)

        self.keyctl = Gtk.EventControllerKey()
        self.keyctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.keyctl.connect('key-pressed', self._on_key)
        self.add_controller(self.keyctl)
        self.im = Gtk.IMMulticontext()
        self.im.connect('commit', lambda _im, text: session.on_text_commit(text))
        self.connect('close-request', self._on_close_request)

        if shot.gdk_monitor is not None:
            self.fullscreen_on_monitor(shot.gdk_monitor)
        else:
            self.fullscreen()

    def _on_key(self, ctrl, keyval, keycode, state):
        return self.session.on_key(self, keyval, state)

    def _on_close_request(self, *_):
        if not self.session.closing:
            self.session.action('exit')
        return False

    def place_toolbar(self):
        c = self.canvas
        if not c.sel:
            return
        W, H = self.shot.width, self.shot.height
        tb = self.toolbar
        for rows in (1, 2, 3):
            if tb.rows != rows:
                tb.set_rows(rows)
            nat_w = tb.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            if nat_w <= W - 16:
                break
        nat_h = tb.measure(Gtk.Orientation.VERTICAL, nat_w)[1]
        lx, ly, lw, lh = c.sel_logical()
        gap = 12
        if ly + lh + gap + nat_h <= H - 6:
            y = ly + lh + gap
        elif ly - gap - nat_h >= 6:
            y = ly - gap - nat_h
        else:
            y = max(6, ly + lh - nat_h - gap)
        x = min(max(lx + lw / 2 - nat_w / 2, 6), W - nat_w - 6)
        y = min(y, H - nat_h - 6)
        tb.set_margin_start(max(0, int(x)))
        tb.set_margin_top(max(0, int(y)))


# =========================================================================== Session

class CaptureSession:
    def __init__(self, app, shots, opts, pointer=None):
        self.app = app
        self.config = app.config
        self.shots = shots
        self.opts = opts
        self.pointer = pointer
        cfg = self.config
        self.tool = None
        self.color = hex_to_rgba(cfg.get('draw_color', '#ff0000'))
        self.thickness = int(cfg.get('draw_thickness', 3))
        self.font_size = int(cfg.get('font_size', 22))
        self.windows = []
        self.owner = None
        self.hover = None
        self.side_panel = False
        self.picking_color = False
        self.closing = False
        self.text_canvas = None

    # ----------------------------------------------------------------- lifecycle

    def start(self):
        self.app.hold()
        shots = self.shots
        if self.config.get('capture_active_monitor') and self.pointer:
            shots = [s for s in shots if s.contains_comp(*self.pointer)] or shots
        for shot in shots:
            self.windows.append(CaptureWindow(self, shot))
        # Present the monitor under the pointer last so it gets keyboard focus.
        order = sorted(self.windows, key=lambda w: self.pointer is not None
                       and w.shot.contains_comp(*self.pointer))
        for w in order:
            w.present()
        focus = order[-1]
        self.hover = focus.canvas
        focus.canvas.grab_focus()
        self._apply_initial_region()
        self.sync_ui()

    def _apply_initial_region(self):
        rect = None
        if self.opts.region:
            rect = self.opts.region
        elif self.opts.last_region or self.config.get('save_last_region'):
            st = load_state().get('last_region')
            if st:
                rect = tuple(st)
        if not rect:
            return
        gx, gy, gw, gh = rect
        for w in self.windows:
            sh = w.shot
            if sh.contains(gx, gy):
                c = w.canvas
                self.claim(c)
                x0, y0 = c.to_px(gx - sh.x, gy - sh.y)
                x1, y1 = c.to_px(gx - sh.x + gw, gy - sh.y + gh)
                if x1 - x0 >= 1 and y1 - y0 >= 1:
                    c.sel = [x0, y0, x1 - x0, y1 - y0]
                c.queue_draw()
                return

    def close_overlays(self):
        self.closing = True
        for w in self.windows:
            w.destroy()
        self.windows = []

    def done(self):
        if not getattr(self, '_released', False):
            self._released = True
            self.app.release()

    # ----------------------------------------------------------------- state

    def canvases(self):
        return [w.canvas for w in self.windows]

    def any_selection(self):
        return any(c.sel for c in self.canvases())

    def target(self):
        if self.owner and self.owner.sel:
            return self.owner
        return self.hover or (self.canvases()[0] if self.windows else None)

    def claim(self, canvas):
        if self.owner is not canvas:
            for c in self.canvases():
                if c is not canvas and (c.sel or c.annotations):
                    c.clear()
            self.owner = canvas

    def set_tool(self, tool):
        for c in self.canvases():
            c.finish_text()
            c.selected = None
            c.queue_draw()
        self.tool = tool
        self.picking_color = False
        self.sync_ui()

    def set_color(self, color):
        self.color = tuple(color)
        self.config['draw_color'] = rgba_to_hex(color)
        t = self.target()
        if t and t.restyle_target():
            ann = t.restyle_target()
            if ann is not t.editing:
                t.push_undo()
            ann.color = tuple(color)
            t.queue_draw()
        self.sync_panel()
        for c in self.canvases():
            c.queue_draw()

    def set_thickness(self, value):
        self.thickness = max(1, min(100, int(value)))
        self.config['draw_thickness'] = self.thickness
        t = self.target()
        ann = t.restyle_target() if t else None
        if ann and not isinstance(ann, Text):
            ann.thickness = self.thickness
            t.queue_draw()
        self.sync_panel()

    def set_font_size(self, value):
        self.font_size = max(6, min(300, int(value)))
        self.config['font_size'] = self.font_size
        t = self.target()
        ann = t.restyle_target() if t else None
        if isinstance(ann, Text):
            ann.thickness = self.font_size
            t.queue_draw()
        self.sync_panel()

    def change_size(self, step):
        t = self.target()
        ann = t.restyle_target() if t else None
        if self.tool == 'text' or isinstance(ann, Text):
            self.set_font_size(self.font_size + step * 2)
        else:
            self.set_thickness(self.thickness + step)

    def start_color_pick(self):
        self.picking_color = True
        for c in self.canvases():
            c.set_cursor_from_name('crosshair')
            c.queue_draw()

    def toggle_side_panel(self):
        self.side_panel = not self.side_panel
        self.sync_ui()

    # ----------------------------------------------------------------- UI sync

    def sync_panel(self):
        for w in self.windows:
            if w.panel.get_visible():
                w.panel.sync()

    def sync_ui(self):
        if self.closing:
            return
        tgt = self.target()
        for w in self.windows:
            c = w.canvas
            show_tb = (c is self.owner and c.sel is not None and c.mode not in DRAG_MODES
                       and c.sel[2] > 0 and c.sel[3] > 0)
            # Show before placing: a hidden widget measures as 0x0.
            w.toolbar.set_visible(show_tb)
            if show_tb:
                w.place_toolbar()
            w.toolbar.sync(self.tool)
            show_panel = self.side_panel and c is tgt
            w.panel.set_visible(show_panel)
            if show_panel:
                w.panel.sync()
            c.queue_draw()

    # ----------------------------------------------------------------- text input

    def begin_text(self, canvas):
        self.text_canvas = canvas
        for w in self.windows:
            w.keyctl.set_im_context(w.im)
            w.im.set_client_widget(w.canvas)
            w.im.focus_in()

    def end_text(self, canvas):
        if self.text_canvas is canvas:
            self.text_canvas = None
            for w in self.windows:
                w.im.focus_out()
                w.im.reset()
                w.keyctl.set_im_context(None)

    def on_text_commit(self, text):
        c = self.text_canvas
        if c and c.editing:
            c.editing.text += text
            c.queue_draw()

    # ----------------------------------------------------------------- keyboard

    def on_key(self, window, keyval, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)

        focus = window.get_focus()
        if isinstance(focus, (Gtk.Text, Gtk.Editable)) and keyval != Gdk.KEY_Escape:
            return False

        c = self.text_canvas
        if c and c.editing:
            t = c.editing
            if keyval == Gdk.KEY_Escape:
                c.finish_text()
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                if ctrl:
                    c.finish_text()
                else:
                    t.text += '\n'
                c.queue_draw()
                return True
            if keyval == Gdk.KEY_BackSpace:
                t.text = t.text[:-1]
                c.queue_draw()
                return True
            if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
                c.undo()
                return True
            if ctrl or alt:
                return True
            ch = Gdk.keyval_to_unicode(keyval)
            if ch and ch >= 32:
                t.text += chr(ch)
                c.queue_draw()
            return True

        tgt = self.target()
        if keyval == Gdk.KEY_Escape:
            if self.picking_color:
                self.picking_color = False
                self.sync_ui()
                return True
            if tgt and tgt.wheel is not None:
                tgt.wheel = None
                tgt.queue_draw()
                return True
            self.action('exit')
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.action('accept')
            return True
        if keyval == Gdk.KEY_space:
            self.toggle_side_panel()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
            if tgt:
                tgt.delete_selected()
            return True

        if ctrl:
            k = Gdk.keyval_to_lower(keyval)
            if k == Gdk.KEY_z and shift or k == Gdk.KEY_y:
                tgt and tgt.redo()
            elif k == Gdk.KEY_z:
                tgt and tgt.undo()
            elif k == Gdk.KEY_c:
                self.action('copy')
            elif k == Gdk.KEY_s:
                self.action('save')
            elif k == Gdk.KEY_p:
                self.action('pin')
            elif k == Gdk.KEY_o:
                self.action('open_with')
            elif k == Gdk.KEY_u:
                self.action('upload')
            elif k == Gdk.KEY_q:
                self.action('exit')
            elif k == Gdk.KEY_m:
                self.set_tool(None)
            elif k == Gdk.KEY_a:
                (self.hover or tgt).select_all()
            else:
                return False
            return True

        arrows = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if keyval in arrows and tgt and tgt.sel:
            dx, dy = arrows[keyval]
            step = 10 if alt else 1
            tgt.nudge(dx * step, dy * step, resize=shift)
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_equal):
            self.change_size(1)
            return True
        if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.change_size(-1)
            return True
        k = Gdk.keyval_to_lower(keyval)
        if k in TOOL_KEYS and not alt:
            tool = TOOL_KEYS[k]
            self.set_tool(None if self.tool == tool else tool)
            return True
        return False

    # ----------------------------------------------------------------- actions

    def action(self, name):
        tgt = self.target()
        if name == 'undo':
            tgt and tgt.undo()
            return
        if name == 'redo':
            tgt and tgt.redo()
            return
        if name == 'move':
            self.set_tool(None)
            return
        if name == 'side_panel':
            self.toggle_side_panel()
            return
        if name == 'exit':
            self.close_overlays()
            self.done()
            return
        if not tgt:
            return
        if name == 'accept':
            o = self.opts
            explicit = [a for a, on in (('raw', o.raw), ('path', bool(o.path)),
                                        ('copy', o.clipboard), ('pin', o.pin), ('upload', o.upload)) if on]
            if not explicit:
                acc = self.config.get('accept_action', 'copy')
                explicit = {'copy': ['copy'], 'save': ['save'], 'copy_save': ['copy', 'save']}.get(acc, ['copy'])
            self.finish(explicit)
            return
        if name in ('copy', 'save', 'pin', 'open_with', 'upload'):
            self.finish([name])

    def finish(self, actions):
        tgt = self.target()
        surface = tgt.render()
        geo = tgt.sel_global_logical()
        scale = tgt.shot.sx
        if tgt.sel:
            st = load_state()
            st['last_region'] = list(geo)
            save_state(st)
        try:
            self.config.save()          # remember color / thickness
        except OSError:
            pass
        # Set the clipboard while our surface still has keyboard focus.
        if 'copy' in actions:
            self.app.clipboard.set_texture(surface)
        self.close_overlays()
        sel = tgt.sel or [0, 0]
        anchor = (tgt.shot.comp[0], tgt.shot.comp[1], sel[0], sel[1], tgt.shot.comp_scale)
        self.app.handle_result(surface, actions, self.opts, anchor, scale)
        self.done()

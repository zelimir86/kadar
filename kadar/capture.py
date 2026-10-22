# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Screen capture backends.

Every backend returns one Shot per monitor, holding that monitor's pixels at
its *physical* resolution plus its logical geometry. Keeping monitors apart is
what makes mixed and fractional scales work: a 1600x900 logical monitor at
160% is shown and saved from its own 2560x1440 image, never resampled.
"""

import io
import json
import os
import random
import shutil
import subprocess
import tempfile

import cairo
from gi.repository import Gdk, Gio, GLib


class CaptureError(Exception):
    pass


def surface_to_texture(surface):
    surface.flush()
    if surface.get_format() == cairo.FORMAT_ARGB32:
        fmt = Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED
    else:
        fmt = Gdk.MemoryFormat.B8G8R8X8
    data = GLib.Bytes.new(bytes(surface.get_data()))
    return Gdk.MemoryTexture.new(surface.get_width(), surface.get_height(), fmt,
                                 data, surface.get_stride())


class Shot:
    """One monitor: geometry + pixels.

    x/y/width/height are GTK logical coordinates (what the overlay window
    measures in). comp is the same rectangle in the compositor's coordinates
    (pointer position, window placement). They are equal on Wayland; on X11
    the compositor counts X pixels while GTK divides them by its scale.
    """

    def __init__(self, index, x, y, width, height, surface, connector=''):
        self.index = index
        self.surface = surface
        self.connector = connector
        self.px_w = surface.get_width()
        self.px_h = surface.get_height()
        self.comp = (x, y, width, height)
        self.set_logical(x, y, width, height)
        self.gdk_monitor = None
        self._texture = None

    def set_logical(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height
        self.sx = self.px_w / width
        self.sy = self.px_h / height

    @property
    def comp_scale(self):
        """Image pixels per compositor unit."""
        return self.px_w / self.comp[2]

    @property
    def texture(self):
        if self._texture is None:
            self._texture = surface_to_texture(self.surface)
        return self._texture

    def contains(self, gx, gy):
        """gx, gy in GTK logical coordinates."""
        return self.x <= gx < self.x + self.width and self.y <= gy < self.y + self.height

    def contains_comp(self, cx, cy):
        """cx, cy in compositor coordinates (e.g. the Cinnamon pointer)."""
        x, y, w, h = self.comp
        return x <= cx < x + w and y <= cy < y + h

    def __repr__(self):
        return (f'<Shot {self.index} {self.connector} {self.width}x{self.height}+{self.x}+{self.y} '
                f'px={self.px_w}x{self.px_h} scale={self.sx:.3f}>')


# --------------------------------------------------------------------------- Cinnamon

def cinnamon_eval(js, timeout_ms=10000):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    res = bus.call_sync('org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', 'Eval',
                        GLib.Variant('(s)', (js,)), GLib.VariantType('(bs)'),
                        Gio.DBusCallFlags.NONE, timeout_ms, None)
    ok, out = res.unpack()
    if not ok:
        raise CaptureError('Cinnamon.Eval failed: ' + out)
    return json.loads(out) if out else None


def is_cinnamon():
    return 'cinnamon' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower()


_CINNAMON_CAPTURE_JS = r"""
(function (dir) {
  const cairo = imports.gi.cairo;
  const Gdk = imports.gi.Gdk;
  const GLib = imports.gi.GLib;
  const d = global.display;
  const ptr = global.get_pointer();
  const out = { pointer: [ptr[0], ptr[1]], monitors: [] };
  for (let i = 0; i < d.get_n_monitors(); i++) {
    const g = d.get_monitor_geometry(i);
    const res = global.stage.capture(false, new cairo.RectangleInt({ x: g.x, y: g.y, width: g.width, height: g.height }));
    const caps = (res && res[0]) ? res[1] : [];
    let best = null;
    for (const c of caps)
      if (!best || c.rect.width * c.rect.height > best.rect.width * best.rect.height)
        best = c;
    const m = { index: i, x: g.x, y: g.y, width: g.width, height: g.height,
                scale: d.get_monitor_scale(i), file: null, rect: null };
    if (best) {
      // Raw pixels: PNG encoding here would stall the compositor for ~1 s.
      const pb = Gdk.pixbuf_get_from_surface(best.image, 0, 0,
                                             best.image.getWidth(), best.image.getHeight());
      m.file = dir + '/monitor' + i + '.raw';
      m.rect = [best.rect.x, best.rect.y, best.rect.width, best.rect.height];
      m.px = [pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()];
      GLib.file_set_contents(m.file, pb.get_pixels());
    }
    out.monitors.push(m);
  }
  return JSON.stringify(out);
})(%s)
"""


def _raw_to_surface(path, width, height, stride, channels):
    with open(path, 'rb') as f:
        data = GLib.Bytes.new(f.read())
    fmt = Gdk.MemoryFormat.R8G8B8A8 if channels == 4 else Gdk.MemoryFormat.R8G8B8
    tex = Gdk.MemoryTexture.new(width, height, fmt, data, stride)
    dl = Gdk.TextureDownloader.new(tex)
    dl.set_format(Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED)
    out, out_stride = dl.download_bytes()
    buf = bytearray(out.get_data())
    return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, width, height, out_stride)


def capture_cinnamon():
    """Read each stage view straight from Cinnamon's compositor.

    org.cinnamon.Screenshot (and the portal on top of it) downsamples to the
    logical size, so this goes through Cinnamon.Eval instead, which yields the
    framebuffer of every monitor at its native resolution.
    """
    tmp = tempfile.mkdtemp(prefix='kadar-', dir=os.environ.get('XDG_RUNTIME_DIR'))
    try:
        info = json.loads(cinnamon_eval(_CINNAMON_CAPTURE_JS % json.dumps(tmp)))
        shots = []
        for m in info['monitors']:
            if not m['file']:
                continue
            surf = _raw_to_surface(m['file'], *m['px'])
            rx, ry, rw, rh = m['rect']
            if (rx, ry, rw, rh) != (m['x'], m['y'], m['width'], m['height']):
                surf = _crop_logical(surf, rw, rh, m['x'] - rx, m['y'] - ry, m['width'], m['height'])
            shots.append(Shot(m['index'], m['x'], m['y'], m['width'], m['height'], surf))
        return shots, tuple(info['pointer'])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _crop_logical(surf, logical_w, logical_h, x, y, w, h):
    sx = surf.get_width() / logical_w
    sy = surf.get_height() / logical_h
    out = cairo.ImageSurface(surf.get_format(), round(w * sx), round(h * sy))
    cr = cairo.Context(out)
    cr.set_source_surface(surf, -round(x * sx), -round(y * sy))
    cr.paint()
    return out


def cinnamon_pointer():
    try:
        return tuple(json.loads(cinnamon_eval(
            'JSON.stringify(global.get_pointer().slice(0, 2))')))
    except Exception:
        return None


def cinnamon_place_window(title, x=None, y=None, above=False):
    """Move/raise one of our windows by title (Wayland gives clients no way to)."""
    js = r'''
(function (title, x, y, above) {
  for (const a of global.get_window_actors()) {
    const w = a.get_meta_window();
    if (w && w.get_title() === title) {
      if (x !== null) w.move_frame(true, x, y);
      if (above) w.make_above();
      return true;
    }
  }
  return false;
})(%s, %s, %s, %s)''' % (json.dumps(title), json.dumps(x), json.dumps(y), json.dumps(bool(above)))
    try:
        return cinnamon_eval(js, 2000)
    except Exception:
        return False


def cinnamon_pin_window(title, x=None, y=None):
    """Place a pin window, keep it above, and keep it on the device-pixel grid.

    On a 160% monitor a window at logical x=301 starts at device pixel 481.6,
    and the compositor resamples it. After every move (grab-op-end) the window
    is nudged to the nearest position that lands on a whole device pixel.
    """
    js = r"""
(function (title, x, y) {
  for (const a of global.get_window_actors()) {
    const w = a.get_meta_window();
    if (!w || w.get_title() !== title)
      continue;
    const d = global.display;
    const snap = () => {
      const r = w.get_frame_rect();
      const mon = w.get_monitor();
      const m = d.get_monitor_geometry(mon);
      const s = d.get_monitor_scale(mon);
      const fix = (v, o) => {
        const k = v - o;
        for (let i = 0; i < 240; i++)
          for (const c of [k - i, k + i])
            if (Math.abs(c * s - Math.round(c * s)) < 1e-3)
              return o + c;
        return v;
      };
      const nx = fix(r.x, m.x), ny = fix(r.y, m.y);
      if (nx !== r.x || ny !== r.y)
        w.move_frame(true, nx, ny);
    };
    if (x !== null)
      w.move_frame(true, x, y);
    w.make_above();
    const id = d.connect('grab-op-end', (...args) => { if (args.includes(w)) snap(); });
    w.connect('unmanaged', () => d.disconnect(id));
    snap();
    return true;
  }
  return false;
})(%s, %s, %s)""" % (json.dumps(title), json.dumps(x), json.dumps(y))
    try:
        return cinnamon_eval(js, 2000)
    except Exception:
        return False


# --------------------------------------------------------------------------- generic

def gdk_monitors():
    display = Gdk.Display.get_default()
    mons = display.get_monitors()
    return [mons.get_item(i) for i in range(mons.get_n_items())]


def capture_grim():
    if not shutil.which('grim'):
        raise CaptureError('grim not installed')
    shots = []
    for i, mon in enumerate(gdk_monitors()):
        g = mon.get_geometry()
        conn = mon.get_connector()
        r = subprocess.run(['grim', '-o', conn, '-t', 'png', '-l', '0', '-'],
                           capture_output=True, timeout=10)
        if r.returncode != 0:
            raise CaptureError('grim: ' + r.stderr.decode(errors='replace').strip())
        surf = cairo.ImageSurface.create_from_png(io.BytesIO(r.stdout))
        shots.append(Shot(i, g.x, g.y, g.width, g.height, surf, conn))
    return shots, None


def capture_portal():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = 'kadar%d' % random.randint(0, 1 << 30)
    sender = bus.get_unique_name()[1:].replace('.', '_')
    req_path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
    result = {}
    loop = GLib.MainLoop()

    def on_response(conn, sender_name, path, iface, signal, params, *args):
        result['code'], result['res'] = params.unpack()
        loop.quit()

    sub = bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                               'Response', req_path, None, Gio.DBusSignalFlags.NONE, on_response)
    try:
        bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
                      'org.freedesktop.portal.Screenshot', 'Screenshot',
                      GLib.Variant('(sa{sv})', ('', {'handle_token': GLib.Variant('s', token),
                                                     'interactive': GLib.Variant('b', False)})),
                      GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 30000, None)
        GLib.timeout_add_seconds(30, loop.quit)
        loop.run()
    finally:
        bus.signal_unsubscribe(sub)
    if result.get('code') != 0:
        raise CaptureError('Screenshot portal was cancelled or failed')
    path = Gio.File.new_for_uri(result['res']['uri']).get_path()
    full = cairo.ImageSurface.create_from_png(path)
    try:
        os.unlink(path)
    except OSError:
        pass
    mons = gdk_monitors()
    geos = [m.get_geometry() for m in mons]
    bx = min(g.x for g in geos)
    by = min(g.y for g in geos)
    bw = max(g.x + g.width for g in geos) - bx
    bh = max(g.y + g.height for g in geos) - by
    shots = []
    for i, (mon, g) in enumerate(zip(mons, geos)):
        surf = _crop_logical(full, bw, bh, g.x - bx, g.y - by, g.width, g.height)
        shots.append(Shot(i, g.x, g.y, g.width, g.height, surf, mon.get_connector()))
    return shots, None


def capture(backend='auto'):
    """Returns (shots, pointer) where pointer is a global logical (x, y) or None."""
    order = [backend] if backend != 'auto' else []
    if not order:
        if is_cinnamon():
            order.append('cinnamon')
        if os.environ.get('WAYLAND_DISPLAY') and shutil.which('grim'):
            order.append('grim')
        order.append('portal')
    errors = []
    for name in order:
        try:
            shots, pointer = {'cinnamon': capture_cinnamon, 'grim': capture_grim,
                              'portal': capture_portal}[name]()
            if shots:
                _attach_gdk_monitors(shots)
                return shots, pointer
        except Exception as e:  # try the next backend
            errors.append(f'{name}: {e}')
    raise CaptureError('; '.join(errors) or 'no capture backend')


def _attach_gdk_monitors(shots):
    """Pair each shot with its GdkMonitor and switch it to GTK's coordinates."""
    mons = gdk_monitors()
    used = set()

    def matches(m, shot):
        g = m.get_geometry()
        f = m.get_scale_factor()
        rect = (g.x, g.y, g.width, g.height)
        # Equal on Wayland; on X11 GTK's geometry is X pixels / scale factor.
        return rect == shot.comp or tuple(v * f for v in rect) == shot.comp

    for shot in shots:
        for i, m in enumerate(mons):
            if i not in used and matches(m, shot):
                shot.gdk_monitor = m
                used.add(i)
                break
    for shot in shots:
        if shot.gdk_monitor is None:
            for i, m in enumerate(mons):
                if i not in used:
                    shot.gdk_monitor = m
                    used.add(i)
                    break
    for shot in shots:
        m = shot.gdk_monitor
        if m is not None:
            shot.connector = shot.connector or m.get_connector() or ''
            g = m.get_geometry()
            if (g.x, g.y, g.width, g.height) != (shot.x, shot.y, shot.width, shot.height):
                shot.set_logical(g.x, g.y, g.width, g.height)


def compose(shots):
    """All monitors in one image, at the highest scale among them."""
    scale = max(s.sx for s in shots)
    bx = min(s.x for s in shots)
    by = min(s.y for s in shots)
    bw = max(s.x + s.width for s in shots) - bx
    bh = max(s.y + s.height for s in shots) - by
    out = cairo.ImageSurface(cairo.FORMAT_RGB24, round(bw * scale), round(bh * scale))
    cr = cairo.Context(out)
    for s in shots:
        cr.save()
        cr.translate(round((s.x - bx) * scale), round((s.y - by) * scale))
        k = scale / s.sx
        if abs(k - 1) > 1e-6:
            cr.scale(k, k)
        cr.set_source_surface(s.surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
    return out

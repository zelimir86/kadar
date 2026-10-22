# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Annotation objects.

Geometry is kept in the monitor's logical coordinates and thickness in logical
pixels, so an annotation looks the same on the overlay and in the saved image.
Export draws the same objects onto the physical-resolution image through a
cairo transform, which keeps every edge sharp at any fractional scale.
"""

import math

import cairo
import gi

gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo  # noqa: E402

TOOL_NAMES = {
    'pencil': 'Pencil', 'line': 'Line', 'arrow': 'Arrow', 'rect': 'Rectangle',
    'rect_filled': 'Filled rectangle', 'circle': 'Ellipse', 'marker': 'Marker',
    'text': 'Text', 'pixelate': 'Pixelate', 'counter': 'Counter', 'invert': 'Invert',
}


def hex_to_rgba(value):
    v = value.lstrip('#')
    if len(v) == 3:
        v = ''.join(c * 2 for c in v)
    r, g, b = int(v[0:2], 16) / 255, int(v[2:4], 16) / 255, int(v[4:6], 16) / 255
    a = int(v[6:8], 16) / 255 if len(v) >= 8 else 1.0
    return (r, g, b, a)


def rgba_to_hex(c):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(x * 255))) for x in c[:3])


def luminance(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _norm(p1, p2):
    return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))


class DrawContext:
    """What annotations need from their canvas while drawing."""

    def __init__(self, shot):
        self.shot = shot
        self.surface = shot.surface
        self.sx = shot.sx
        self.sy = shot.sy
        self.annotations = []
        self.editing = None
        self.cache = {}

    def counter_number(self, ann):
        n = 0
        for a in self.annotations:
            if isinstance(a, Counter):
                n += 1
            if a is ann:
                return n
        return n + 1


class Annotation:
    kind = ''

    def __init__(self, color, thickness):
        self.color = tuple(color)
        self.thickness = thickness

    def draw(self, cr, ctx):
        raise NotImplementedError

    def bounds(self):
        raise NotImplementedError

    def translate(self, dx, dy):
        raise NotImplementedError

    def tolerance(self):
        return max(6, self.thickness / 2 + 4)

    def hit(self, x, y):
        x0, y0, x1, y1 = self.bounds()
        t = self.tolerance()
        return x0 - t <= x <= x1 + t and y0 - t <= y <= y1 + t

    def is_empty(self):
        x0, y0, x1, y1 = self.bounds()
        return x1 - x0 < 1 and y1 - y0 < 1

    def update(self, x, y, shift=False):
        pass

    def _source(self, cr):
        cr.set_source_rgba(*self.color)


class TwoPoint(Annotation):
    square = False   # shift constrains to a square/circle
    snap = False     # shift snaps the angle to 45 degrees

    def __init__(self, color, thickness, x, y):
        super().__init__(color, thickness)
        self.p1 = (x, y)
        self.p2 = (x, y)

    def update(self, x, y, shift=False):
        if shift and self.square:
            dx, dy = x - self.p1[0], y - self.p1[1]
            d = max(abs(dx), abs(dy))
            x = self.p1[0] + math.copysign(d, dx or 1)
            y = self.p1[1] + math.copysign(d, dy or 1)
        elif shift and self.snap:
            dx, dy = x - self.p1[0], y - self.p1[1]
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            dist = math.hypot(dx, dy)
            x = self.p1[0] + dist * math.cos(ang)
            y = self.p1[1] + dist * math.sin(ang)
        self.p2 = (x, y)

    def bounds(self):
        return _norm(self.p1, self.p2)

    def translate(self, dx, dy):
        self.p1 = (self.p1[0] + dx, self.p1[1] + dy)
        self.p2 = (self.p2[0] + dx, self.p2[1] + dy)

    def length(self):
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    def is_empty(self):
        return self.length() < 2


def _seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Line(TwoPoint):
    kind = 'line'
    snap = True

    def draw(self, cr, ctx):
        self._source(cr)
        cr.set_line_width(self.thickness)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(*self.p1)
        cr.line_to(*self.p2)
        cr.stroke()

    def hit(self, x, y):
        return _seg_dist(x, y, self.p1, self.p2) <= self.tolerance()


class Marker(Line):
    kind = 'marker'

    def width(self):
        return max(10, self.thickness * 3 + 4)

    def tolerance(self):
        return self.width() / 2 + 3

    def draw(self, cr, ctx):
        r, g, b, _ = self.color
        cr.set_source_rgba(r, g, b, 0.45)
        cr.set_line_width(self.width())
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(*self.p1)
        cr.line_to(*self.p2)
        cr.stroke()

    def bounds(self):
        x0, y0, x1, y1 = super().bounds()
        w = self.width() / 2
        return (x0 - w, y0 - w, x1 + w, y1 + w)


class Arrow(Line):
    kind = 'arrow'

    def draw(self, cr, ctx):
        x1, y1 = self.p1
        x2, y2 = self.p2
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1:
            return
        t = self.thickness
        head_len = min(max(12, t * 4 + 6), L)
        head_w = head_len * 0.75
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        bx, by = x2 - ux * head_len, y2 - uy * head_len
        self._source(cr)
        cr.set_line_width(t)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        # Stop the shaft inside the head so its round cap never pokes out.
        sx, sy = x2 - ux * head_len * 0.6, y2 - uy * head_len * 0.6
        if L > head_len * 0.6:
            cr.move_to(x1, y1)
            cr.line_to(sx, sy)
            cr.stroke()
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.move_to(x2, y2)
        cr.line_to(bx - uy * head_w / 2, by + ux * head_w / 2)
        cr.line_to(bx + uy * head_w / 2, by - ux * head_w / 2)
        cr.close_path()
        cr.fill()

    def bounds(self):
        x0, y0, x1, y1 = super().bounds()
        h = max(12, self.thickness * 4 + 6) * 0.4
        return (x0 - h, y0 - h, x1 + h, y1 + h)


class Rect(TwoPoint):
    kind = 'rect'
    square = True

    def draw(self, cr, ctx):
        x0, y0, x1, y1 = self.bounds()
        self._source(cr)
        cr.set_line_width(self.thickness)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.stroke()

    def hit(self, x, y):
        x0, y0, x1, y1 = self.bounds()
        t = self.tolerance()
        inside_outer = x0 - t <= x <= x1 + t and y0 - t <= y <= y1 + t
        inside_inner = x0 + t < x < x1 - t and y0 + t < y < y1 - t
        return inside_outer and not inside_inner


class RectFilled(Rect):
    kind = 'rect_filled'

    def draw(self, cr, ctx):
        x0, y0, x1, y1 = self.bounds()
        self._source(cr)
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.fill()

    def hit(self, x, y):
        return Annotation.hit(self, x, y)


class Ellipse(TwoPoint):
    kind = 'circle'
    square = True

    def draw(self, cr, ctx):
        x0, y0, x1, y1 = self.bounds()
        w, h = x1 - x0, y1 - y0
        if w < 0.5 or h < 0.5:
            return
        cr.save()
        cr.translate(x0 + w / 2, y0 + h / 2)
        cr.scale(w / 2, h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        self._source(cr)
        cr.set_line_width(self.thickness)
        cr.stroke()

    def hit(self, x, y):
        x0, y0, x1, y1 = self.bounds()
        a, b = (x1 - x0) / 2, (y1 - y0) / 2
        if a < 1 or b < 1:
            return Annotation.hit(self, x, y)
        cx, cy = x0 + a, y0 + b
        # Distance from the outline, approximated in normalised space.
        d = math.hypot((x - cx) / a, (y - cy) / b)
        return abs(d - 1) * min(a, b) <= self.tolerance()


class Pixelate(TwoPoint):
    kind = 'pixelate'

    def block(self):
        return max(4, self.thickness * 2 + 2)

    def hit(self, x, y):
        return Annotation.hit(self, x, y)

    def draw(self, cr, ctx):
        x0, y0, x1, y1 = self.bounds()
        surf = ctx.surface
        px0 = max(0, math.floor(x0 * ctx.sx))
        py0 = max(0, math.floor(y0 * ctx.sy))
        px1 = min(surf.get_width(), math.ceil(x1 * ctx.sx))
        py1 = min(surf.get_height(), math.ceil(y1 * ctx.sy))
        w, h = px1 - px0, py1 - py0
        if w < 1 or h < 1:
            return
        block = max(2, round(self.block() * ctx.sx))
        key = ('pix', px0, py0, w, h, block)
        small = ctx.cache.get(key)
        if small is None:
            sw, sh = math.ceil(w / block), math.ceil(h / block)
            small = cairo.ImageSurface(cairo.FORMAT_RGB24, sw, sh)
            c2 = cairo.Context(small)
            c2.scale(1 / block, 1 / block)
            c2.set_source_surface(surf, -px0, -py0)
            c2.get_source().set_filter(cairo.FILTER_GOOD)
            c2.get_source().set_extend(cairo.EXTEND_PAD)
            c2.paint()
            if len(ctx.cache) > 32:
                ctx.cache.clear()
            ctx.cache[key] = small
        cr.save()
        cr.scale(1 / ctx.sx, 1 / ctx.sy)
        cr.rectangle(px0, py0, w, h)
        cr.clip()
        cr.translate(px0, py0)
        cr.scale(block, block)
        cr.set_source_surface(small, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()


class Invert(TwoPoint):
    kind = 'invert'

    def hit(self, x, y):
        return Annotation.hit(self, x, y)

    def draw(self, cr, ctx):
        x0, y0, x1, y1 = self.bounds()
        if x1 - x0 < 0.5 or y1 - y0 < 0.5:
            return
        cr.save()
        cr.scale(1 / ctx.sx, 1 / ctx.sy)
        cr.rectangle(x0 * ctx.sx, y0 * ctx.sy, (x1 - x0) * ctx.sx, (y1 - y0) * ctx.sy)
        cr.clip()
        cr.push_group()
        cr.set_source_surface(ctx.surface, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_DIFFERENCE)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.pop_group_to_source()
        cr.paint()
        cr.restore()


class Pencil(Annotation):
    kind = 'pencil'

    def __init__(self, color, thickness, x, y):
        super().__init__(color, thickness)
        self.points = [(x, y)]

    def update(self, x, y, shift=False):
        lx, ly = self.points[-1]
        if (x - lx) ** 2 + (y - ly) ** 2 >= 0.25:
            self.points.append((x, y))

    def bounds(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        t = self.thickness / 2
        return (min(xs) - t, min(ys) - t, max(xs) + t, max(ys) + t)

    def is_empty(self):
        return False

    def translate(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]

    def hit(self, x, y):
        pts = self.points
        if len(pts) == 1:
            return math.hypot(x - pts[0][0], y - pts[0][1]) <= self.tolerance()
        return any(_seg_dist(x, y, a, b) <= self.tolerance() for a, b in zip(pts, pts[1:]))

    def draw(self, cr, ctx):
        pts = self.points
        self._source(cr)
        cr.set_line_width(self.thickness)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*pts[0])
        if len(pts) == 1:
            cr.line_to(pts[0][0] + 0.01, pts[0][1])
        elif len(pts) == 2:
            cr.line_to(*pts[1])
        else:
            # Quadratic smoothing through segment midpoints.
            for i in range(1, len(pts) - 1):
                mx = (pts[i][0] + pts[i + 1][0]) / 2
                my = (pts[i][1] + pts[i + 1][1]) / 2
                x0, y0 = cr.get_current_point()
                cx, cy = pts[i]
                cr.curve_to(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0),
                            mx + 2 / 3 * (cx - mx), my + 2 / 3 * (cy - my), mx, my)
            cr.line_to(*pts[-1])
        cr.stroke()


class Counter(Annotation):
    kind = 'counter'

    def __init__(self, color, thickness, x, y):
        super().__init__(color, thickness)
        self.center = (x, y)

    def radius(self):
        return max(10, 7 + self.thickness * 2)

    def bounds(self):
        r = self.radius()
        x, y = self.center
        return (x - r, y - r, x + r, y + r)

    def is_empty(self):
        return False

    def translate(self, dx, dy):
        self.center = (self.center[0] + dx, self.center[1] + dy)

    def draw(self, cr, ctx):
        x, y = self.center
        r = self.radius()
        self._source(cr)
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.fill()
        fg = (0, 0, 0) if luminance(self.color) > 0.55 else (1, 1, 1)
        cr.set_source_rgb(*fg)
        layout = _layout(cr, 'Sans Bold', r * 1.15)
        layout.set_text(str(ctx.counter_number(self)), -1)
        ink, logical = layout.get_extents()
        w = ink.width / Pango.SCALE
        h = ink.height / Pango.SCALE
        cr.move_to(x - w / 2 - ink.x / Pango.SCALE, y - h / 2 - ink.y / Pango.SCALE)
        PangoCairo.show_layout(cr, layout)


_measure_cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def _layout(cr, family, size_px):
    fo = cairo.FontOptions()
    fo.set_hint_style(cairo.HINT_STYLE_NONE)
    fo.set_hint_metrics(cairo.HINT_METRICS_OFF)
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    cr.set_font_options(fo)
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription.from_string(family)
    desc.set_absolute_size(max(1, size_px) * Pango.SCALE)
    layout.set_font_description(desc)
    return layout


class Text(Annotation):
    kind = 'text'

    def __init__(self, color, font_size, x, y, family='Sans'):
        super().__init__(color, font_size)
        self.pos = (x, y)
        self.text = ''
        self.family = family

    @property
    def font_size(self):
        return self.thickness

    def _make_layout(self, cr):
        layout = _layout(cr, self.family, self.font_size)
        layout.set_text(self.text or ' ', -1)
        return layout

    def bounds(self):
        layout = self._make_layout(_measure_cr)
        _, logical = layout.get_pixel_extents()
        x, y = self.pos
        return (x, y, x + max(logical.width, self.font_size * 0.3), y + logical.height)

    def tolerance(self):
        return 4

    def is_empty(self):
        return not self.text.strip()

    def translate(self, dx, dy):
        self.pos = (self.pos[0] + dx, self.pos[1] + dy)

    def draw(self, cr, ctx):
        layout = self._make_layout(cr)
        x, y = self.pos
        if self.text:
            self._source(cr)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, layout)
        if ctx.editing is self:
            idx = len(self.text.encode('utf-8'))
            strong, _ = layout.get_cursor_pos(idx)
            cx = x + strong.x / Pango.SCALE
            cy = y + strong.y / Pango.SCALE
            ch = strong.height / Pango.SCALE
            cr.set_source_rgba(*self.color[:3], 1)
            cr.set_line_width(max(1.5, self.font_size / 14))
            cr.move_to(cx + 1, cy)
            cr.line_to(cx + 1, cy + ch)
            cr.stroke()
            x0, y0, x1, y1 = self.bounds()
            cr.set_source_rgba(1, 1, 1, 0.6)
            cr.set_line_width(1)
            cr.set_dash([4, 3])
            cr.rectangle(x0 - 4, y0 - 2, x1 - x0 + 8, y1 - y0 + 4)
            cr.stroke()
            cr.set_dash([])


TOOL_CLASSES = {
    'pencil': Pencil, 'line': Line, 'arrow': Arrow, 'rect': Rect, 'rect_filled': RectFilled,
    'circle': Ellipse, 'marker': Marker, 'pixelate': Pixelate, 'counter': Counter,
    'invert': Invert,
}

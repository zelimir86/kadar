# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Toolbar icons drawn as vectors with cairo.

Drawing them at paint time keeps them crisp at any scale (1.6, 1.75, ...),
unlike bitmap icons that GTK would have to resample.
"""

import math

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Graphene, Gtk  # noqa: E402


def _stroke(cr, w=2.0):
    cr.set_line_width(w)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()


def _pencil(cr):
    cr.move_to(5, 19)
    cr.line_to(6, 15)
    cr.line_to(16, 5)
    cr.line_to(19, 8)
    cr.line_to(9, 18)
    cr.close_path()
    _stroke(cr, 1.8)
    cr.move_to(14, 7)
    cr.line_to(17, 10)
    _stroke(cr, 1.6)


def _line(cr):
    cr.move_to(5, 19)
    cr.line_to(19, 5)
    _stroke(cr, 2.2)


def _arrow(cr):
    cr.move_to(5, 19)
    cr.line_to(16, 8)
    _stroke(cr, 2.2)
    cr.move_to(19, 5)
    cr.line_to(11, 7)
    cr.line_to(17, 13)
    cr.close_path()
    cr.fill()


def _rect(cr):
    cr.rectangle(4.5, 6.5, 15, 11)
    _stroke(cr, 2)


def _rect_filled(cr):
    cr.rectangle(4, 6, 16, 12)
    cr.fill()


def _circle(cr):
    cr.arc(12, 12, 7.5, 0, 2 * math.pi)
    _stroke(cr, 2)


def _marker(cr):
    cr.save()
    cr.push_group()
    cr.move_to(5, 17)
    cr.line_to(19, 17)
    cr.set_line_width(5)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.stroke()
    cr.pop_group_to_source()
    cr.paint_with_alpha(0.45)
    cr.restore()
    cr.move_to(9, 13)
    cr.line_to(16, 4)
    cr.line_to(19, 6.5)
    cr.line_to(12, 15)
    cr.close_path()
    _stroke(cr, 1.6)


def _text(cr):
    cr.move_to(6, 6)
    cr.line_to(18, 6)
    cr.move_to(12, 6)
    cr.line_to(12, 19)
    cr.move_to(9.5, 19)
    cr.line_to(14.5, 19)
    _stroke(cr, 2.2)


def _pixelate(cr):
    for r in range(4):
        for c in range(4):
            if (r + c) % 2 == 0:
                cr.rectangle(4 + c * 4, 4 + r * 4, 4, 4)
    cr.fill()
    cr.rectangle(4.5, 4.5, 15, 15)
    _stroke(cr, 1)


def _counter(cr):
    cr.arc(12, 12, 8.5, 0, 2 * math.pi)
    _stroke(cr, 1.8)
    cr.move_to(10, 9)
    cr.line_to(12.5, 7.5)
    cr.line_to(12.5, 16.5)
    _stroke(cr, 2)


def _invert(cr):
    cr.arc(12, 12, 8, 0, 2 * math.pi)
    _stroke(cr, 1.8)
    cr.arc(12, 12, 8, -math.pi / 2, math.pi / 2)
    cr.close_path()
    cr.fill()


def _move(cr):
    cr.move_to(12, 3.5)
    cr.line_to(12, 20.5)
    cr.move_to(3.5, 12)
    cr.line_to(20.5, 12)
    _stroke(cr, 1.8)
    for ang in (0, 90, 180, 270):
        cr.save()
        cr.translate(12, 12)
        cr.rotate(math.radians(ang))
        cr.move_to(0, -10)
        cr.line_to(-3, -6.5)
        cr.line_to(3, -6.5)
        cr.close_path()
        cr.fill()
        cr.restore()


def _undo(cr, mirror=False):
    if mirror:
        cr.translate(24, 0)
        cr.scale(-1, 1)
    cr.move_to(8, 9)
    cr.line_to(15, 9)
    cr.curve_to(22, 9, 22, 19, 15, 19)
    cr.line_to(9, 19)
    _stroke(cr, 2)
    cr.move_to(4, 9)
    cr.line_to(9, 4.5)
    cr.line_to(9, 13.5)
    cr.close_path()
    cr.fill()


def _redo(cr):
    _undo(cr, mirror=True)


def _copy(cr):
    cr.rectangle(8.5, 8.5, 11, 11)
    _stroke(cr, 1.8)
    cr.move_to(15.5, 5.5)
    cr.line_to(15.5, 4.5)
    cr.line_to(4.5, 4.5)
    cr.line_to(4.5, 15.5)
    cr.line_to(5.5, 15.5)
    _stroke(cr, 1.8)


def _save(cr):
    cr.move_to(12, 4)
    cr.line_to(12, 14)
    cr.move_to(7.5, 10)
    cr.line_to(12, 14.5)
    cr.line_to(16.5, 10)
    _stroke(cr, 2)
    cr.move_to(4.5, 15)
    cr.line_to(4.5, 19.5)
    cr.line_to(19.5, 19.5)
    cr.line_to(19.5, 15)
    _stroke(cr, 2)


def _pin(cr):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.radians(45))
    cr.rectangle(-3, -9, 6, 8)
    _stroke(cr, 1.8)
    cr.move_to(-6, -1)
    cr.line_to(6, -1)
    _stroke(cr, 2)
    cr.move_to(0, -1)
    cr.line_to(0, 9)
    _stroke(cr, 1.8)
    cr.restore()


def _open_with(cr):
    cr.move_to(11, 5.5)
    cr.line_to(5.5, 5.5)
    cr.line_to(5.5, 18.5)
    cr.line_to(18.5, 18.5)
    cr.line_to(18.5, 13)
    _stroke(cr, 1.8)
    cr.move_to(11, 13)
    cr.line_to(19, 5)
    cr.move_to(13.5, 5)
    cr.line_to(19, 5)
    cr.line_to(19, 10.5)
    _stroke(cr, 1.8)


def _upload(cr):
    cr.move_to(12, 15)
    cr.line_to(12, 5)
    cr.move_to(7.5, 9)
    cr.line_to(12, 4.5)
    cr.line_to(16.5, 9)
    _stroke(cr, 2)
    cr.move_to(4.5, 15)
    cr.line_to(4.5, 19.5)
    cr.line_to(19.5, 19.5)
    cr.line_to(19.5, 15)
    _stroke(cr, 2)


def _side_panel(cr):
    for y, x in ((7, 9), (12, 15), (17, 7)):
        cr.move_to(4, y)
        cr.line_to(20, y)
        _stroke(cr, 1.6)
        cr.arc(x, y, 2.3, 0, 2 * math.pi)
        cr.fill()


def _exit(cr):
    cr.move_to(6.5, 6.5)
    cr.line_to(17.5, 17.5)
    cr.move_to(17.5, 6.5)
    cr.line_to(6.5, 17.5)
    _stroke(cr, 2.2)


def _accept(cr):
    cr.move_to(5, 12.5)
    cr.line_to(10, 17.5)
    cr.line_to(19, 7)
    _stroke(cr, 2.4)


ICONS = {
    'pencil': _pencil, 'line': _line, 'arrow': _arrow, 'rect': _rect, 'rect_filled': _rect_filled,
    'circle': _circle, 'marker': _marker, 'text': _text, 'pixelate': _pixelate,
    'counter': _counter, 'invert': _invert, 'move': _move, 'undo': _undo, 'redo': _redo,
    'copy': _copy, 'save': _save, 'pin': _pin, 'open_with': _open_with, 'upload': _upload,
    'side_panel': _side_panel, 'exit': _exit, 'accept': _accept,
}


class Icon(Gtk.Widget):
    def __init__(self, name, size=20):
        super().__init__()
        self.name = name
        self.size = size
        self.set_size_request(size, size)
        self.set_can_target(False)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        cr = snapshot.append_cairo(Graphene.Rect().init(0, 0, w, h))
        c = self.get_color()
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
        s = min(w, h) / 24
        cr.translate((w - 24 * s) / 2, (h - 24 * s) / 2)
        cr.scale(s, s)
        ICONS[self.name](cr)

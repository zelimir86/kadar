# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Tray icon. Runs in its own GTK 3 process because XApp.StatusIcon menus are
GTK 3 widgets; every action starts a fresh `kadar <command>` process."""

import os
import subprocess
import sys

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('XApp', '1.0')
from gi.repository import Gtk, XApp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def spawn(*args):
    env = dict(os.environ)
    env['PYTHONPATH'] = ROOT + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    subprocess.Popen([sys.executable, '-m', 'kadar', *args], env=env, start_new_session=True)


def run_tray():
    icon = XApp.StatusIcon()
    icon.set_name('kadar')
    icon.set_icon_name('kadar')
    icon.set_tooltip_text('Kadar – take a screenshot')

    menu = Gtk.Menu()
    for label, args in (('Take screenshot', ('gui',)), ('Launcher…', ('launcher',)),
                        ('Capture full screen', ('full', '-c')),
                        ('Capture monitor under pointer', ('screen', '-c')),
                        (None, None), ('Settings', ('config',)), (None, None), ('Quit', None)):
        if label is None:
            menu.append(Gtk.SeparatorMenuItem())
            continue
        item = Gtk.MenuItem(label=label)
        if args:
            item.connect('activate', lambda _i, a=args: spawn(*a))
        else:
            item.connect('activate', lambda _i: Gtk.main_quit())
        menu.append(item)
    menu.show_all()
    icon.set_secondary_menu(menu)

    def on_activate(_icon, button, _time):
        if button == 1:
            spawn('gui')
        elif button == 2:
            spawn('launcher')

    icon.connect('activate', on_activate)
    Gtk.main()
    return 0

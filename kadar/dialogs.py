# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Launcher, settings and "open with" windows."""

import os

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .config import ALL_BUTTONS  # noqa: E402
from .overlay import ACTIONS, rgba  # noqa: E402
from .tools import TOOL_NAMES, hex_to_rgba, rgba_to_hex  # noqa: E402


class Opts:
    """Options for one capture (the CLI flags, or what the launcher picked)."""

    def __init__(self, **kw):
        self.path = None
        self.clipboard = False
        self.raw = False
        self.pin = False
        self.upload = False
        self.accept_on_select = False
        self.region = None
        self.last_region = False
        self.number = None
        self.delay = 0
        self.__dict__.update(kw)


# --------------------------------------------------------------------------- Open with

class OpenWithWindow(Gtk.ApplicationWindow):
    def __init__(self, app, path):
        super().__init__(application=app, title='Open screenshot with')
        self.path = path
        self.set_default_size(380, 460)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        lst.add_css_class('boxed-list')
        seen = set()
        default = Gio.AppInfo.get_default_for_type('image/png', False)
        apps = ([default] if default else []) + Gio.AppInfo.get_recommended_for_type('image/png') \
            + Gio.AppInfo.get_all_for_type('image/png')
        self.apps = []
        for info in apps:
            if info is None or info.get_id() in seen:
                continue
            seen.add(info.get_id())
            self.apps.append(info)
            row = Gtk.Box(spacing=10)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            row.set_margin_start(6)
            icon = info.get_icon()
            img = Gtk.Image.new_from_gicon(icon) if icon else Gtk.Image.new_from_icon_name('application-x-executable')
            img.set_pixel_size(28)
            row.append(img)
            row.append(Gtk.Label(label=info.get_display_name(), xalign=0))
            lst.append(row)
        lst.connect('row-activated', self._on_row)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(lst)
        box.append(sw)
        hint = Gtk.Label(label=f'File: {path}', xalign=0, wrap=True, selectable=True)
        hint.add_css_class('dim-label')
        box.append(hint)
        self.set_child(box)
        key = Gtk.EventControllerKey()
        key.connect('key-pressed', lambda c, k, *a: k == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(key)

    def _on_row(self, lst, row):
        info = self.apps[row.get_index()]
        try:
            info.launch([Gio.File.new_for_path(self.path)], None)
        except GLib.Error as e:
            print('kadar: launch failed:', e.message)
        self.close()


# --------------------------------------------------------------------------- Launcher

class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app, shots_info):
        super().__init__(application=app, title='Kadar')
        self.app = app
        self.set_resizable(False)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(grid, f'set_margin_{m}')(18)

        grid.attach(Gtk.Label(label='Area', xalign=1), 0, 0, 1, 1)
        names = ['Rectangular region', 'Full screen (all monitors)']
        self.monitors = shots_info
        for i, m in enumerate(shots_info):
            names.append(f'Monitor {i}: {m}')
        self.area = Gtk.DropDown.new_from_strings(names)
        grid.attach(self.area, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label='Delay', xalign=1), 0, 1, 1, 1)
        self.delay = Gtk.SpinButton.new_with_range(0, 60, 0.5)
        self.delay.set_digits(1)
        dbox = Gtk.Box(spacing=6)
        dbox.append(self.delay)
        dbox.append(Gtk.Label(label='seconds'))
        grid.attach(dbox, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label='Then', xalign=1, valign=Gtk.Align.START), 0, 2, 1, 1)
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.copy = Gtk.CheckButton(label='Copy to clipboard', active=True)
        self.save = Gtk.CheckButton(label='Save to file')
        self.pin = Gtk.CheckButton(label='Pin to desktop')
        for w in (self.copy, self.save, self.pin):
            opts.append(w)
        grid.attach(opts, 1, 2, 1, 1)

        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cfg = Gtk.Button(label='Settings')
        cfg.connect('clicked', lambda *_: ConfigWindow(app).present())
        take = Gtk.Button(label='Take screenshot')
        take.add_css_class('suggested-action')
        take.connect('clicked', self._on_take)
        btns.append(cfg)
        btns.append(take)
        grid.attach(btns, 0, 3, 2, 1)
        self.set_child(grid)
        self.set_default_widget(take)

    def _on_take(self, *_):
        sel = self.area.get_selected()
        opts = Opts(clipboard=self.copy.get_active(), pin=self.pin.get_active(),
                    delay=int(self.delay.get_value() * 1000))
        if self.save.get_active():
            opts.path = self.app.config.get('save_path')
        if not (opts.clipboard or opts.path or opts.pin):
            opts.clipboard = True
        mode = 'gui' if sel == 0 else 'full' if sel == 1 else 'screen'
        if mode == 'screen':
            opts.number = sel - 2
        self.close()
        # Let the compositor remove this window before the capture runs.
        opts.delay = max(opts.delay, 250)
        self.app.run_capture(mode, opts)


# --------------------------------------------------------------------------- Settings

class ConfigWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Kadar settings')
        self.app = app
        self.cfg = app.config
        self.set_default_size(560, 620)
        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER)
        header = Gtk.HeaderBar()
        header.set_title_widget(switcher)
        self.set_titlebar(header)
        stack.add_titled(self._scroll(self._general()), 'general', 'General')
        stack.add_titled(self._scroll(self._interface()), 'interface', 'Interface')
        stack.add_titled(self._scroll(self._shortcuts()), 'shortcuts', 'Shortcuts')
        self.set_child(stack)

    # helpers ------------------------------------------------------------

    def _scroll(self, child):
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        child.set_margin_top(16)
        child.set_margin_bottom(16)
        child.set_margin_start(20)
        child.set_margin_end(20)
        sw.set_child(child)
        return sw

    def _section(self, box, text):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f'<b>{GLib.markup_escape_text(text)}</b>')
        lbl.set_margin_top(10)
        box.append(lbl)

    def _check(self, box, key, label, tip=None):
        cb = Gtk.CheckButton(label=label, active=bool(self.cfg.get(key)))
        if tip:
            cb.set_tooltip_text(tip)
        cb.connect('toggled', lambda w: self.cfg.set(key, w.get_active()))
        box.append(cb)
        return cb

    def _row(self, box, label, widget):
        row = Gtk.Box(spacing=12)
        lbl = Gtk.Label(label=label, xalign=0, hexpand=True)
        row.append(lbl)
        row.append(widget)
        box.append(row)

    def _entry(self, key, width=28):
        e = Gtk.Entry(text=str(self.cfg.get(key) or ''), width_chars=width)
        e.connect('changed', lambda w: self.cfg.set(key, w.get_text()))
        return e

    def _color(self, key):
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        c = hex_to_rgba(self.cfg.get(key))
        btn.set_rgba(rgba(*c))
        btn.connect('notify::rgba', lambda b, _p: self.cfg.set(
            key, rgba_to_hex((b.get_rgba().red, b.get_rgba().green, b.get_rgba().blue))))
        return btn

    # pages --------------------------------------------------------------

    def _general(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._section(box, 'Saving')
        path_row = Gtk.Box(spacing=6)
        self.path_entry = self._entry('save_path', 24)
        browse = Gtk.Button(icon_name='folder-open-symbolic')
        browse.connect('clicked', self._browse)
        path_row.append(self.path_entry)
        path_row.append(browse)
        self._row(box, 'Save folder', path_row)
        self._row(box, 'File name pattern (strftime)', self._entry('filename_pattern', 24))
        fmt = Gtk.DropDown.new_from_strings(['png', 'jpg', 'webp', 'bmp'])
        fmts = ['png', 'jpg', 'webp', 'bmp']
        cur = self.cfg.get('save_format', 'png')
        fmt.set_selected(fmts.index(cur) if cur in fmts else 0)
        fmt.connect('notify::selected', lambda d, _p: self.cfg.set('save_format', fmts[d.get_selected()]))
        self._row(box, 'File format', fmt)
        q = Gtk.SpinButton.new_with_range(10, 100, 1)
        q.set_value(self.cfg.get('jpeg_quality', 92))
        q.connect('value-changed', lambda s: self.cfg.set('jpeg_quality', int(s.get_value())))
        self._row(box, 'JPEG quality', q)
        self._check(box, 'save_dialog', 'Ask where to save (otherwise save straight to the folder)')
        self._check(box, 'copy_path_after_save', 'Copy the file path to the clipboard after saving')

        self._section(box, 'Behaviour')
        acc = ['copy', 'save', 'copy_save']
        dd = Gtk.DropDown.new_from_strings(['Copy to clipboard', 'Save', 'Copy and save'])
        a = self.cfg.get('accept_action', 'copy')
        dd.set_selected(acc.index(a) if a in acc else 0)
        dd.connect('notify::selected', lambda d, _p: self.cfg.set('accept_action', acc[d.get_selected()]))
        self._row(box, 'Enter key does', dd)
        qd = Gtk.DropDown.new_from_strings(['Copy to clipboard', 'Save', 'Copy and save'])
        q = self.cfg.get('quick_action', 'copy')
        qd.set_selected(acc.index(q) if q in acc else 0)
        qd.connect('notify::selected', lambda d, _p: self.cfg.set('quick_action', acc[d.get_selected()]))
        self._row(box, '"kadar full" / "kadar screen" without options do', qd)
        self._check(box, 'show_notifications', 'Show desktop notifications')
        self._check(box, 'copy_on_double_click', 'Double click on the selection copies it')
        self._check(box, 'save_last_region', 'Start with the last selected region')
        self._check(box, 'capture_active_monitor', 'Only open the capture on the monitor under the pointer')
        backends = ['auto', 'cinnamon', 'grim', 'portal']
        bd = Gtk.DropDown.new_from_strings(backends)
        b = self.cfg.get('capture_backend', 'auto')
        bd.set_selected(backends.index(b) if b in backends else 0)
        bd.connect('notify::selected', lambda d, _p: self.cfg.set('capture_backend', backends[d.get_selected()]))
        self._row(box, 'Capture backend', bd)

        self._section(box, 'Tray and startup')
        cb = Gtk.CheckButton(label='Start the tray icon when I log in',
                             active=os.path.exists(_autostart_path()))
        cb.connect('toggled', lambda w: _set_autostart(w.get_active()))
        box.append(cb)

        self._section(box, 'Upload')
        self._row(box, 'Imgur client ID (empty hides the button)', self._entry('imgur_client_id', 20))
        return box

    def _browse(self, *_):
        dlg = Gtk.FileDialog(title='Save folder')
        if self.cfg.get('save_path'):
            dlg.set_initial_folder(Gio.File.new_for_path(self.cfg['save_path']))

        def done(d, res):
            try:
                f = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.path_entry.set_text(f.get_path())
        dlg.select_folder(self, None, done)

    def _interface(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._section(box, 'Colors')
        self._row(box, 'Main UI color', self._color('ui_color'))
        self._row(box, 'Active tool color', self._color('contrast_ui_color'))
        op = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        op.set_value(self.cfg.get('contrast_opacity', 190))
        op.set_size_request(220, -1)
        op.connect('value-changed', lambda s: self.cfg.set('contrast_opacity', int(s.get_value())))
        self._row(box, 'Darkening outside the selection', op)
        self._section(box, 'Overlay')
        self._check(box, 'show_help', 'Show the help box when the capture opens')
        self._check(box, 'show_magnifier', 'Show a magnifier while selecting')
        self._row(box, 'Text font', self._entry('font_family', 16))
        self._section(box, 'Toolbar buttons')
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                           min_children_per_line=2)
        enabled = set(self.cfg.get('buttons') or [])

        def toggle(w, name):
            cur = [b for b in ALL_BUTTONS if b in set(self.cfg.get('buttons') or [])]
            if w.get_active() and name not in cur:
                cur.append(name)
            elif not w.get_active() and name in cur:
                cur.remove(name)
            self.cfg.set('buttons', [b for b in ALL_BUTTONS if b in cur])

        for name in ALL_BUTTONS:
            label = TOOL_NAMES.get(name) or ACTIONS.get(name, (name,))[0]
            cb = Gtk.CheckButton(label=label, active=name in enabled)
            cb.connect('toggled', toggle, name)
            flow.append(cb)
        box.append(flow)
        return box

    def _shortcuts(self):
        from .overlay import TOOL_SHORTCUTS
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        rows = [(TOOL_NAMES[t], k) for t, k in TOOL_SHORTCUTS.items()]
        rows += [(label, key) for label, key in ACTIONS.values()]
        rows += [
            ('Accept (Enter action from General)', 'Enter'),
            ('Select the whole monitor', 'Ctrl+A'),
            ('Delete the selected object', 'Delete'),
            ('Move selection by 1 px (10 px with Alt)', 'Arrows'),
            ('Resize selection by 1 px', 'Shift+Arrows'),
            ('Thickness / font size', 'Mouse wheel, + / -'),
            ('Color wheel', 'Right click'),
            ('Straight / square / circle', 'Hold Shift while drawing'),
            ('Finish text', 'Esc or Ctrl+Enter'),
        ]
        grid = Gtk.Grid(column_spacing=24, row_spacing=6)
        for i, (label, key) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
            k = Gtk.Label(xalign=0)
            k.set_markup(f'<tt>{GLib.markup_escape_text(key)}</tt>')
            grid.attach(k, 1, i, 1, 1)
        box.append(grid)
        return box


def _autostart_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, 'autostart', 'kadar-tray.desktop')


def _set_autostart(enabled):
    path = _autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('[Desktop Entry]\nType=Application\nName=Kadar tray\nExec=kadar tray\n'
                    'Icon=kadar\nX-GNOME-Autostart-enabled=true\nNoDisplay=false\n')
    elif os.path.exists(path):
        os.unlink(path)

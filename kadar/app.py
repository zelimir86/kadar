# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""GTK4 application: runs one capture command and stays alive while needed
(clipboard ownership, pinned images, dialogs)."""

import os
import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import output  # noqa: E402
from .capture import CaptureError, capture, compose, gdk_monitors  # noqa: E402
from .config import Config  # noqa: E402
from .dialogs import ConfigWindow, LauncherWindow, OpenWithWindow  # noqa: E402
from .overlay import CaptureSession  # noqa: E402
from .pin import PinWindow  # noqa: E402
from .tools import hex_to_rgba, luminance  # noqa: E402

APP_ID = 'io.github.zelimir86.Kadar'


def _css(cfg):
    ui = cfg.get('ui_color', '#2fbfdf')
    hi = cfg.get('contrast_ui_color', '#270ac1')
    ui_fg = '#101010' if luminance(hex_to_rgba(ui)) > 0.6 else '#ffffff'
    hi_fg = '#101010' if luminance(hex_to_rgba(hi)) > 0.6 else '#ffffff'
    return f'''
window.kadar-overlay {{ background: #000; }}
window.kadar-pin {{ background: transparent; }}
.kadar-toolbar {{
  background-color: rgba(18, 18, 20, 0.88);
  border-radius: 14px;
  padding: 5px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.45);
}}
.kadar-toolbar button.kadar-btn {{
  min-width: 32px; min-height: 32px; padding: 0; margin: 0;
  border-radius: 999px; border: none; outline: none;
  background: {ui}; background-image: none; box-shadow: none;
  color: {ui_fg};
}}
.kadar-toolbar button.kadar-btn:hover {{ filter: brightness(1.18); }}
.kadar-toolbar button.kadar-btn:checked {{
  background: {hi}; color: {hi_fg};
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.9);
}}
.kadar-toolbar button.kadar-exit:hover {{ background: #d9344a; color: #fff; }}
.kadar-panel {{
  background-color: rgba(24, 24, 27, 0.95);
  border-radius: 14px;
  padding: 16px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5);
  color: #eeeeee;
}}
.kadar-panel-title {{ font-weight: bold; font-size: 1.1em; }}
.kadar-panel-caption {{ color: #a8a8b0; font-size: 0.9em; margin-top: 4px; }}
.kadar-panel-hint {{ color: #8a8a92; font-size: 0.85em; margin-top: 6px; }}
.kadar-panel button.kadar-swatch {{
  min-width: 26px; min-height: 26px; padding: 2px; border-radius: 999px;
  background: transparent; background-image: none; border: none; box-shadow: none;
}}
.kadar-panel button.kadar-swatch:hover {{ background: rgba(255, 255, 255, 0.15); }}
'''


class KadarApp(Gtk.Application):
    def __init__(self, command, opts):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.command = command
        self.opts = opts
        self.config = Config()
        self.clipboard = None
        self.exit_code = 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(_css(self.config))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.clipboard = output.ClipboardKeeper(self)

    def do_activate(self):
        cmd = self.command
        if cmd in ('gui', 'full', 'screen'):
            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', True)
            self.run_capture(cmd, self.opts)
        elif cmd == 'launcher':
            names = []
            for m in gdk_monitors():
                g = m.get_geometry()
                names.append(f'{m.get_connector()} {g.width}×{g.height} @ {m.get_scale():g}')
            LauncherWindow(self, names).present()
        elif cmd == 'config':
            ConfigWindow(self).present()

    # ------------------------------------------------------------------ capture

    def run_capture(self, mode, opts):
        self.hold()

        def go():
            try:
                shots, pointer = capture(self.config.get('capture_backend', 'auto'))
            except CaptureError as e:
                print('kadar: capture failed:', e, file=sys.stderr)
                output.notify(self.config, 'Screenshot failed', str(e), force=True)
                self.exit_code = 1
                self.release()
                return False
            dump = os.environ.get('KADAR_DUMP')
            if dump:
                for s in shots:
                    s.surface.write_to_png(os.path.join(dump, f'dump_m{s.index}.png'))
            if mode == 'gui':
                CaptureSession(self, shots, opts, pointer).start()
            else:
                if mode == 'full':
                    surface = compose(shots)
                    scale = max(s.sx for s in shots)
                    anchor = None
                else:
                    shot = None
                    if opts.number is not None and 0 <= opts.number < len(shots):
                        shot = shots[opts.number]
                    elif pointer:
                        shot = next((s for s in shots if s.contains_comp(*pointer)), None)
                    shot = shot or shots[0]
                    surface, scale = shot.surface, shot.sx
                    anchor = (shot.comp[0], shot.comp[1], 0, 0, shot.comp_scale)
                # Without -p/-c/... use the "quick_action" setting.
                default = {'copy': ['copy'], 'save': ['save_auto'],
                           'copy_save': ['copy', 'save_auto']}
                actions = self.actions_from_opts(opts) or \
                    default.get(self.config.get('quick_action', 'copy'), ['copy'])
                if 'copy' in actions:
                    self.clipboard.set_texture(surface)
                self.handle_result(surface, actions, opts, anchor, scale)
            self.release()
            return False

        GLib.timeout_add(max(1, int(opts.delay or 0)), go)

    @staticmethod
    def actions_from_opts(opts):
        acts = []
        if opts.raw:
            acts.append('raw')
        if opts.path:
            acts.append('path')
        if opts.clipboard:
            acts.append('copy')
        if opts.pin:
            acts.append('pin')
        if opts.upload:
            acts.append('upload')
        return acts

    def handle_result(self, surface, actions, opts, anchor, scale):
        """Run the post-capture actions. The clipboard was already set by the caller."""
        cfg = self.config
        if 'raw' in actions:
            sys.stdout.buffer.write(output.png_bytes(surface))
            sys.stdout.buffer.flush()
        if 'copy' in actions:
            output.notify(cfg, 'Capture copied to clipboard')
        if 'path' in actions:
            self._save(surface, output.resolve_target(opts.path, cfg))
        if 'save_auto' in actions:
            folder = os.path.expanduser(cfg.get('save_path') or '~')
            os.makedirs(folder, exist_ok=True)
            self._save(surface, output.unique_path(os.path.join(folder, output.default_filename(cfg))))
        if 'save' in actions:
            self.save_with_dialog(surface)
        if 'pin' in actions:
            PinWindow(self, surface, scale, anchor).present()
        if 'open_with' in actions:
            OpenWithWindow(self, output.temp_image(surface)).present()
        if 'upload' in actions:
            self.upload(surface)

    def _save(self, surface, path):
        try:
            output.save_surface(surface, path, self.config)
        except Exception as e:  # report I/O and encoder errors alike
            output.notify(self.config, 'Could not save the screenshot', str(e), force=True)
            print('kadar: save failed:', e, file=sys.stderr)
            self.exit_code = 1
            return
        output.notify(self.config, 'Capture saved', path, icon=path)
        if self.config.get('copy_path_after_save'):
            self.clipboard.set_text(path)

    def save_with_dialog(self, surface, parent=None):
        cfg = self.config
        folder = os.path.expanduser(cfg.get('save_path') or '~')
        if not cfg.get('save_dialog', True):
            os.makedirs(folder, exist_ok=True)
            self._save(surface, output.unique_path(os.path.join(folder, output.default_filename(cfg))))
            return
        self.hold()
        dlg = Gtk.FileDialog(title='Save screenshot', initial_name=output.default_filename(cfg))
        if os.path.isdir(folder):
            dlg.set_initial_folder(Gio.File.new_for_path(folder))

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                f = None
            if f is not None and f.get_path():
                path = f.get_path()
                cfg.set('save_path', os.path.dirname(path))
                self._save(surface, path)
            self.release()

        dlg.save(parent, None, done)

    def upload(self, surface):
        cid = self.config.get('imgur_client_id')
        if not cid:
            output.notify(self.config, 'Upload is not configured',
                          'Set an Imgur client ID in the settings.', force=True)
            return
        self.hold()
        output.notify(self.config, 'Uploading screenshot…')

        def done(url, err):
            if url:
                self.clipboard.set_text(url)
                output.notify(self.config, 'Upload finished', f'{url}\n(link copied to clipboard)', force=True)
            else:
                output.notify(self.config, 'Upload failed', err or '', force=True)
            self.release()
            return False

        output.upload_imgur(surface, cid, done)

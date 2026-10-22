# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović

"""Command line entry point (flameshot-compatible subcommands)."""

import argparse
import re
import sys


def _region(value):
    m = re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', value.strip())
    if not m:
        raise argparse.ArgumentTypeError('expected WxH+X+Y, e.g. 800x600+100+50')
    w, h, x, y = (int(g) for g in m.groups())
    return (x, y, w, h)


def build_parser():
    p = argparse.ArgumentParser(prog='kadar', description='Screenshot tool for Wayland (flameshot-style).')
    sub = p.add_subparsers(dest='command')

    def outputs(sp):
        sp.add_argument('-p', '--path', help='save to this file or folder')
        sp.add_argument('-c', '--clipboard', action='store_true', help='copy to the clipboard')
        sp.add_argument('-r', '--raw', action='store_true', help='write PNG data to stdout')
        sp.add_argument('-d', '--delay', type=int, default=0, help='delay in milliseconds')
        sp.add_argument('--pin', action='store_true', help='pin the capture to the desktop')
        sp.add_argument('-u', '--upload', action='store_true', help='upload to Imgur')

    g = sub.add_parser('gui', help='select an area and annotate it (default)')
    outputs(g)
    g.add_argument('-s', '--accept-on-select', action='store_true', help='accept as soon as an area is selected')
    g.add_argument('--region', type=_region, help='preselect WxH+X+Y (logical desktop coordinates)')
    g.add_argument('--last-region', action='store_true', help='preselect the last selected region')

    f = sub.add_parser('full', help='capture all monitors')
    outputs(f)
    s = sub.add_parser('screen', help='capture one monitor')
    outputs(s)
    s.add_argument('-n', '--number', type=int, help='monitor index (default: under the pointer)')

    sub.add_parser('launcher', help='open the capture launcher')
    sub.add_parser('config', help='open the settings')
    sub.add_parser('tray', help='run the tray icon')
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not argv or argv[0].startswith('-') and argv[0] not in ('-h', '--help'):
        argv = ['gui'] + argv
    args = parser.parse_args(argv)

    if args.command == 'tray':
        from .tray import run_tray       # GTK 3 (XApp), so keep it out of the GTK 4 process
        return run_tray()

    from .app import KadarApp
    from .dialogs import Opts
    opts = Opts()
    for key in ('path', 'clipboard', 'raw', 'delay', 'pin', 'upload', 'accept_on_select',
                'region', 'last_region', 'number'):
        if hasattr(args, key):
            setattr(opts, key, getattr(args, key))
    app = KadarApp(args.command, opts)
    app.run(None)
    return app.exit_code


if __name__ == '__main__':
    sys.exit(main())

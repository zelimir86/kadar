#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Želimir Stevanović
# Installs Kadar for the current user (links to this checkout, so edits apply at once).
#   ./install.sh               install
#   ./install.sh --print-key   also bind the Print key to "kadar gui" (Cinnamon)
#   ./install.sh --uninstall   remove the links and the desktop entry
set -e
here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/scalable/apps"

if [ "$1" = "--uninstall" ]; then
    rm -f "$bin/kadar" "$apps/kadar.desktop" "$icons/kadar.svg"
    echo "Kadar removed (settings stay in ~/.config/kadar)."
    exit 0
fi

mkdir -p "$bin" "$apps" "$icons"
ln -sf "$here/bin/kadar" "$bin/kadar"
cp "$here/data/kadar.svg" "$icons/kadar.svg"
cp "$here/data/kadar.desktop" "$apps/kadar.desktop"
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$apps" 2>/dev/null || true
echo "Installed: $bin/kadar"

if [ "$1" = "--print-key" ]; then
    python3 - <<'EOF'
import ast, subprocess
base = 'org.cinnamon.desktop.keybindings'
path = '/org/cinnamon/desktop/keybindings/custom-keybindings/'
def get(schema, key):
    return ast.literal_eval(subprocess.check_output(['gsettings', 'get', schema, key], text=True).replace('@as ', ''))
def kb(name):
    return f'{base}.custom-keybinding:{path}{name}/'
custom = get(base, 'custom-list')
target = None
for name in custom:
    if get(kb(name), 'binding') == ['Print']:
        target = name
        break
if target is None:
    i = 0
    while f'custom{i}' in custom:
        i += 1
    target = f'custom{i}'
    subprocess.check_call(['gsettings', 'set', base, 'custom-list', str(custom + [target])])
subprocess.check_call(['gsettings', 'set', kb(target), 'name', 'Kadar'])
subprocess.check_call(['gsettings', 'set', kb(target), 'command', 'kadar gui'])
subprocess.check_call(['gsettings', 'set', kb(target), 'binding', "['Print']"])
print(f'Print key -> kadar gui ({target})')
EOF
fi

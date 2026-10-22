#!/bin/sh
# "Install" button for Linux: sets everything up and exits.
#
# Installs Node.js if it is missing (portable copy in ~/.local/share, no sudo),
# then npm dependencies + Electron, builds the app, and creates the desktop
# icon / app-grid entry. Afterwards start the app from those icons.

set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sh "$ROOT/scripts/bootstrap.sh" --install
printf '\nSetup complete. Open "Visible AI Assistant" from your app grid or desktop.\n'

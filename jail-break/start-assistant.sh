#!/bin/sh
# One-click setup + launcher for Linux / Ubuntu (also works inside WSL).
#
# Works on a machine with nothing installed:
#   - finds node, or downloads a portable copy to ~/.local/share (no sudo)
#   - installs npm dependencies, including Electron
#   - builds the app
#   - creates a desktop icon / app-grid entry
#   - starts the app detached
#
# Pass --install to set everything up without starting the app.

set -e
exec sh "$(dirname "$0")/scripts/bootstrap.sh" "$@"

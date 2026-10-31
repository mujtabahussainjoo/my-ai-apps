#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
chmod +x install.sh
./install.sh
rc=$?
echo
if [ "$rc" -eq 0 ]; then echo "NexaPilot AI is installed in /Applications."; else echo "Installation failed (exit $rc)."; fi
read -r -p "Press Enter to close..."

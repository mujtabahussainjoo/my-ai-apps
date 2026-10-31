#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
chmod +x install.sh
./install.sh --build
rc=$?
echo
if [ "$rc" -eq 0 ]; then
  echo "NexaPilot AI is installed. You can close this window."
else
  echo "Installation failed (exit $rc). Scroll up for details."
fi
read -r -p "Press Enter to close..."

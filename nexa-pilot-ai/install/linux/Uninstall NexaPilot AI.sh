#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
chmod +x uninstall.sh
echo "Remove NexaPilot AI"
echo "  1) Remove the app, keep chats and settings (recommended)"
echo "  2) Remove the app and all local data"
read -r -p "Choose 1 or 2: " choice
if [ "$choice" = "2" ]; then
  ./uninstall.sh --purge
else
  ./uninstall.sh
fi
rc=$?
echo
if [ "$rc" -eq 0 ]; then
  echo "Uninstall finished. You can close this window."
else
  echo "Uninstall failed (exit $rc). Scroll up for details."
fi
read -r -p "Press Enter to close..."

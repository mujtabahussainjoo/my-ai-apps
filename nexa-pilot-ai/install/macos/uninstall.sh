#!/usr/bin/env bash
set -euo pipefail
PURGE=0; for a in "$@"; do [ "$a" = "--purge" ] && PURGE=1; done
log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
log "Removing NexaPilot AI"
rm -rf /Applications/NexaPilot\ AI.app /Applications/NexaPilot.app
if [ "$PURGE" -eq 1 ]; then
  rm -rf "$HOME/Library/Application Support/nexapilot" "$HOME/Library/Preferences/ai.nexapilot.desktop.plist" "$HOME/Library/Caches/ai.nexapilot.desktop"
  echo "Data removed. Revoke Google OAuth at https://myaccount.google.com/permissions"
else
  echo "Kept ~/Library/Application Support/nexapilot"
fi

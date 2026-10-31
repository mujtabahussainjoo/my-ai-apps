#!/usr/bin/env bash
# NexaPilot AI - uninstaller for Ubuntu/Debian desktops.
#
#   ./uninstall.sh           remove the application, keep conversations/settings
#   ./uninstall.sh --purge   also delete local data and vault entries
set -euo pipefail

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] && SUDO="" || SUDO="sudo"

if dpkg -s nexa-pilot-ai >/dev/null 2>&1; then
  log "Removing the NexaPilot AI package"
  $SUDO apt-get remove -y nexa-pilot-ai
  $SUDO apt-get autoremove -y
else
  log "NexaPilot AI package is not installed"
fi

if [ "$PURGE" -eq 1 ]; then
  log "Deleting local data (conversations, approvals, settings, logs)"
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/nexapilot"
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/nexapilot"
  if command -v secret-tool >/dev/null; then
    secret-tool search service nexapilot 2>/dev/null | awk -F' = ' '/^attribute.ref/{print $2}' |
      while read -r ref; do
        [ -n "$ref" ] && secret-tool clear service nexapilot ref "$ref" 2>/dev/null || true
      done
  fi
  echo "Local data removed."
else
  echo "Conversations and settings were kept in:"
  echo "  ${XDG_DATA_HOME:-$HOME/.local/share}/nexapilot"
  echo "Re-run with --purge to delete them."
fi

log "Done. Google OAuth grants (if any) must be revoked at https://myaccount.google.com/permissions"

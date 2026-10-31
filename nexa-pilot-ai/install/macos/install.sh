#!/usr/bin/env bash
# NexaPilot AI - one-step installer for macOS.
#   ./install.sh                use pre-built .dmg/.app next to script
#   ./install.sh --build         build from source
set -euo pipefail
APP_NAME="NexaPilot AI"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
DO_BUILD=0; NO_LAUNCH=0
for arg in "$@"; do case "$arg" in --build) DO_BUILD=1;; --no-launch) NO_LAUNCH=1;; esac; done

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }
[ "$(uname -s)" = "Darwin" ] || die "macOS only"

find_art() {
  find "$HERE" "$REPO_ROOT/desktop/src-tauri/target/release/bundle" -maxdepth 3 \( -name "NexaPilot*.dmg" -o -name "NexaPilot*.app" \) 2>/dev/null | head -n1
}

if [ "$DO_BUILD" -eq 1 ]; then
  command -v rustc >/dev/null || (curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && . "$HOME/.cargo/env")
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  npm --prefix "$REPO_ROOT/frontend" install
  npm --prefix "$REPO_ROOT/desktop" install
  "$REPO_ROOT/desktop/scripts/build-sidecar.sh"
  ( cd "$REPO_ROOT/desktop" && npx tauri build --bundles dmg )
fi

ART="$(find_art)"
if [ -z "$ART" ]; then
  if command -v node >/dev/null && command -v rustc >/dev/null && command -v uv >/dev/null && [ -f "$REPO_ROOT/backend/pyproject.toml" ]; then
    log "No .dmg/.app found - building from source"
    DO_BUILD=1
    "$0" --build --no-launch
    ART="$(find_art)"
  fi
fi
[ -n "$ART" ] || die "No .dmg/.app found; run with --build or drop the installer next to this script"
if [[ "$ART" == *.dmg ]]; then
  log "Mounting and installing from $(basename "$ART")"
  MOUNT="$(hdiutil attach -nobrowse -quiet "$ART" | grep -o '/Volumes/.*' | head -n1)"
  cp -R "$MOUNT"/*.app /Applications/
  hdiutil detach "$MOUNT" -quiet
else
  cp -R "$ART" /Applications/
fi
xattr -dr com.apple.quarantine /Applications/NexaPilot*.app 2>/dev/null || true
if [ "$NO_LAUNCH" -eq 0 ]; then open -a "NexaPilot AI" 2>/dev/null || open /Applications/NexaPilot\ AI.app; fi
echo "Installed to /Applications. Uninstall with ./install/macos/uninstall.sh"

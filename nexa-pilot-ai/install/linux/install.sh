#!/usr/bin/env bash
# NexaPilot AI - one-step installer for Ubuntu/Debian desktops.
#
#   ./install.sh                 install a pre-built .deb next to this script
#   ./install.sh --build         build from the source checkout, then install
#   ./install.sh --build --system-deps
#                                also install the build toolchain (Rust, Node, uv)
#
# Everything runs as the normal user except the final apt/dpkg step.
set -euo pipefail

APP_NAME="NexaPilot AI"
DEB_GLOB="NexaPilot*.deb"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
DO_BUILD=0
INSTALL_DEPS=0
NO_LAUNCH=0

for arg in "$@"; do
  case "$arg" in
    --build) DO_BUILD=1 ;;
    --system-deps) INSTALL_DEPS=1 ;;
    --no-launch) NO_LAUNCH=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "this installer is for Linux; use install/windows/install.ps1 on Windows"
command -v apt-get >/dev/null || die "only Debian/Ubuntu systems are supported by this script"
[ -f /etc/os-release ] && . /etc/os-release

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  command -v sudo >/dev/null || die "sudo is required to install system packages"
  SUDO="sudo"
fi

# ---------------------------------------------------------------- prebuilt deb
find_deb() {
  local candidate
  candidate="$(find "$HERE" "$REPO_ROOT/dist" "$REPO_ROOT/desktop/src-tauri/target/release/bundle/deb" \
    -maxdepth 2 -name "$DEB_GLOB" -type f 2>/dev/null | head -n 1 || true)"
  printf '%s' "$candidate"
}

# ------------------------------------------------------------------- packages
install_runtime_deps() {
  log "Installing runtime packages (WebKitGTK, GTK3, tray, xdg tools)"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y --no-install-recommends \
    libwebkit2gtk-4.1-0 \
    libgtk-3-0 \
    librsvg2-2 \
    libayatana-appindicator3-1 \
    xdg-utils \
    ca-certificates
}

install_build_deps() {
  log "Installing build toolchain"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y --no-install-recommends \
    build-essential curl wget file pkg-config \
    libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libssl-dev \
    patchelf python3 python3-venv nodejs npm
  if ! command -v uv >/dev/null; then
    log "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi
  if ! command -v cargo >/dev/null; then
    log "Installing Rust (rustup)"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  fi
}

build_app() {
  [ -f "$REPO_ROOT/backend/pyproject.toml" ] || die "source checkout not found at $REPO_ROOT"
  log "Installing JavaScript dependencies"
  npm --prefix "$REPO_ROOT/frontend" install
  npm --prefix "$REPO_ROOT/desktop" install
  log "Building the backend sidecar (PyInstaller)"
  "$REPO_ROOT/desktop/scripts/build-sidecar.sh"
  log "Building the desktop bundle (Tauri)"
  ( cd "$REPO_ROOT/desktop" && npx tauri build --bundles deb )
}

# --------------------------------------------------------------------- install
log "NexaPilot AI installer - $PRETTY_NAME"

if [ "$DO_BUILD" -eq 1 ]; then
  [ "$INSTALL_DEPS" -eq 1 ] && install_build_deps
  install_runtime_deps
  build_app
else
  DEB="$(find_deb)"
  if [ -z "$DEB" ]; then
    log "No pre-built .deb found - falling back to a source build"
    [ "$INSTALL_DEPS" -eq 1 ] && install_build_deps
    install_runtime_deps
    build_app
  fi
fi

DEB="$(find_deb)"
[ -n "$DEB" ] || die "build finished but no .deb was produced"

log "Installing $(basename "$DEB")"
$SUDO apt-get install -y "$DEB"

log "Refreshing the desktop database"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

log "Installed. Launch \"$APP_NAME\" from your application menu, or run:"
echo "    nexapilot-desktop"

if [ "$NO_LAUNCH" -eq 0 ]; then
  if command -v nexapilot-desktop >/dev/null; then
    nohup nexapilot-desktop >/dev/null 2>&1 &
    echo "    (started in the background)"
  fi
fi

cat <<'EOF'

Uninstall later with:
    ./install/linux/uninstall.sh            # keep your chats/settings
    ./install/linux/uninstall.sh --purge    # remove app + local data

EOF

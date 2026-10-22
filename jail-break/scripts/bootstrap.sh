#!/bin/sh
# One-click setup for Linux (Ubuntu, Debian, Fedora, Arch...).
#
# Runs before Node.js exists, so it only uses POSIX tools:
#   1. Finds node (PATH, then our portable copy in ~/.local/share).
#   2. If missing/too old: downloads the official Node.js tarball from
#      nodejs.org, verifies its SHA256, and unpacks it into ~/.local/share.
#      No sudo and no system packages are touched.
#   3. Hands off to scripts/launch.js, which installs npm packages
#      (including Electron) and builds the app, then starts it (or installs
#      desktop entries only when --install is passed).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/visible-ai-assistant"
NODE_DIR="$DATA_DIR/node"
NODE_BIN="$NODE_DIR/bin/node"
MIN_MAJOR=18

step() { printf '[install] %s\n' "$1"; }
fail() {
  printf '\n[install] FAILED: %s\n' "$1" >&2
  printf 'Visible AI Assistant needs an internet connection the first time.\n' >&2
  if [ -t 0 ]; then
    printf 'Press Enter to close...'
    read -r _ || true
  fi
  exit 1
}

node_version() {
  [ -x "$1" ] || return 1
  "$1" -p 'process.versions.node' 2>/dev/null || return 1
}

node_major() {
  v=$(node_version "$1") || { echo 0; return; }
  echo "${v%%.*}"
}

node_ok() {
  [ "$(node_major "$1")" -ge "$MIN_MAJOR" ] 2>/dev/null
}

find_node() {
  if node_ok "$NODE_BIN"; then echo "$NODE_BIN"; return 0; fi
  if command -v node >/dev/null 2>&1 && node_ok "$(command -v node)"; then
    command -v node
    return 0
  fi
  return 1
}

fetch() {
  url=$1
  out=$2
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 20 -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$out" "$url"
  else
    fail "Need curl or wget to download Node.js."
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo ""
  fi
}

install_node() {
  step "Node.js not found (or too old) - downloading a portable copy..."
  step "No sudo needed; it stays inside $DATA_DIR."

  case "$(uname -m)" in
    x86_64 | amd64) arch=linux-x64 ;;
    aarch64 | arm64) arch=linux-arm64 ;;
    armv7l) arch=linux-armv7l ;;
    ppc64le) arch=linux-ppc64le ;;
    *) arch=linux-x64 ;;
  esac

  base="https://nodejs.org/dist/latest-v22.x"
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/vai-node.XXXXXX")
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM

  sums="$tmp/SHASUMS256.txt"
  fetch "$base/SHASUMS256.txt" "$sums" || fail "Could not reach nodejs.org."

  line=$(grep -E "node-v[0-9.]+-$arch\.tar\.xz$" "$sums" | head -n 1 || true)
  [ -n "$line" ] || fail "No $arch build listed at nodejs.org."

  hash=$(printf '%s\n' "$line" | awk '{print $1}')
  file=$(printf '%s\n' "$line" | awk '{print $2}')

  step "Downloading $file ..."
  fetch "$base/$file" "$tmp/$file" || fail "Node.js download failed."

  step "Verifying checksum..."
  actual=$(sha256_of "$tmp/$file")
  if [ -n "$actual" ] && [ "$actual" != "$hash" ]; then
    fail "Node.js download failed its SHA256 check."
  fi

  step "Extracting Node.js..."
  mkdir -p "$DATA_DIR"
  rm -rf "$NODE_DIR.tmp"
  mkdir -p "$NODE_DIR.tmp"
  tar -xJf "$tmp/$file" -C "$NODE_DIR.tmp" --strip-components=1 || fail "Could not extract Node.js."
  rm -rf "$NODE_DIR"
  mv "$NODE_DIR.tmp" "$NODE_DIR"

  node_ok "$NODE_BIN" || fail "Node.js extraction failed."
  step "Node.js ready: $("$NODE_BIN" --version)"
}

[ -f "$ROOT/scripts/launch.js" ] || fail "Cannot find scripts/launch.js. Keep the project folder together."

NODE=$(find_node || true)
if [ -z "$NODE" ]; then
  install_node
  NODE="$NODE_BIN"
fi

PATH="$(dirname "$NODE"):$PATH"
export PATH

step "Starting setup..."
exec "$NODE" "$ROOT/scripts/launch.js" "$@"

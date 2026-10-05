#!/usr/bin/env bash
# Linux/macOS entry point: bash install.sh
set -euo pipefail
mypa_source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command_exists() { command -v "$1" >/dev/null 2>&1; }
as_admin() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
python_ready() {
  command_exists python3 && python3 -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1
}
for mypa_argument in "$@"; do
  if [ "$mypa_argument" = --dry-run ]; then
    if python_ready; then exec python3 "$mypa_source_dir/install.py" "$@"; fi
    echo 'Plan: bootstrap Python 3.10+, create myPA virtual environment, install dependencies and Ollama, download the model, install launcher and PATH.'
    exit 0
  fi
done
if [ "$(uname -s)" = Darwin ]; then
  if ! python_ready && ! command_exists brew; then
    command_exists curl || { echo 'curl is required to bootstrap Homebrew' >&2; exit 1; }
    mypa_brew_script="$(mktemp)"
    curl --fail --location https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh --output "$mypa_brew_script"
    /bin/bash "$mypa_brew_script"
    rm -f "$mypa_brew_script"
    for mypa_brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [ -x "$mypa_brew_path" ]; then eval "$("$mypa_brew_path" shellenv)"; break; fi
    done
  fi
  if ! python_ready; then brew install python; fi
elif [ "$(uname -s)" = Linux ]; then
  if ! python_ready || ! command_exists curl; then
    if command_exists apt-get; then
      as_admin apt-get update
      as_admin apt-get install -y python3 python3-venv python3-pip ca-certificates curl
    elif command_exists dnf; then
      as_admin dnf install -y python3 python3-pip ca-certificates curl
    elif command_exists yum; then
      as_admin yum install -y python3 python3-pip ca-certificates curl
    elif command_exists pacman; then
      as_admin pacman -Syu --needed --noconfirm python python-pip ca-certificates curl
    elif command_exists zypper; then
      as_admin zypper --non-interactive install python3 python3-pip ca-certificates curl
    else
      echo 'No supported package manager found. Install Python 3.10+ with venv and pip.' >&2
      exit 1
    fi
  fi
else
  echo 'Use install.ps1 on Windows. Supported Unix platforms: Linux/macOS.' >&2
  exit 1
fi
python_ready || { echo 'This OS did not provide Python 3.10+ with venv. Upgrade Python and rerun.' >&2; exit 1; }
exec python3 "$mypa_source_dir/install.py" "$@"

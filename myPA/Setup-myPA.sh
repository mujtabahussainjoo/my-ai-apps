#!/bin/sh
# ============================================================
#  myPA Setup for Ubuntu — DOUBLE-CLICK (Run as Program) or:
#      sh Setup-myPA.sh
#  No sudo needed. Nothing installs without your permission.
# ============================================================
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "[myPA] python3 not found."
  echo "Install it first? (needs sudo — we will ask before running)"
  printf "Run 'sudo apt install -y python3 python3-pip'? [y/N] "
  read ans
  if [ "$ans" = "y" ] || [ "$ans" = "yes" ]; then
    sudo apt update && sudo apt install -y python3 python3-pip
  else
    echo "Aborted. Install python3.10+ and run again."
    exit 1
  fi
fi
sh ./install.sh

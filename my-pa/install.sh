#!/bin/sh
# myPA Ubuntu/macOS installer — permission-first, no silent installs.
# Started by double-clicking Setup-myPA.sh (or: sh Setup-myPA.sh)
set -eu
cd "$(dirname "$0")"
echo "=== myPA setup (linux/mac) ==="
python3 --version
printf "Install myPA Python package (pip install -e .)? [y/N] "
read ans
if [ "$ans" = "y" ] || [ "$ans" = "yes" ]; then pip3 install -e .; else echo "Skipped."; fi
printf "Run setup wizard (providers, Ollama local models, keys)? [Y/n] "
read ans2
if [ "$ans2" = "n" ] || [ "$ans2" = "no" ]; then echo "Run 'python3 setup_wizard.py' later."; else python3 setup_wizard.py; fi
printf "Create 'mypa' launcher command (symlink into ~/.local/bin)? [y/N] "
read ans3
if [ "$ans3" = "y" ] || [ "$ans3" = "yes" ]; then
  mkdir -p "$HOME/.local/bin"
  printf '#!/bin/sh\ncd "%s"\nexec python3 -m mypa "$@"\n' "$(pwd)" > "$HOME/.local/bin/mypa"
  chmod +x "$HOME/.local/bin/mypa"
  echo "Created ~/.local/bin/mypa (make sure it is on your PATH)."
else
  echo "Skipped launcher."
fi
printf "Install desktop icon (mypa.desktop)? [y/N] "
read ans4
if [ "$ans4" = "y" ] || [ "$ans4" = "yes" ]; then
  mkdir -p "$HOME/.local/share/applications"
  sed "s|INSTALL_DIR|$(pwd)|" mypa.desktop > "$HOME/.local/share/applications/mypa.desktop"
  echo "Desktop icon installed."
else
  echo "Skipped desktop icon."
fi
echo "Done. Run: python3 -m mypa --web   (optional .deb: sh build_deb.sh)"

#!/bin/sh
# myPA optional .deb builder (Ubuntu). Asks before doing anything.
# Produces mypa_0.1.0_all.deb which installs to /opt/mypa + /usr/bin/mypa
set -eu
cd "$(dirname "$0")"
VERSION="${1:-0.1.0}"
PKG="build/deb/mypa_${VERSION}_all"
printf "Build %s ? (needs dpkg-deb only, no sudo) [y/N] " "mypa_${VERSION}_all.deb"
read ans
[ "$ans" = "y" ] || [ "$ans" = "yes" ] || { echo "Skipped."; exit 0; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found. Run: sudo apt install dpkg-dev"; exit 1; }
rm -rf "$PKG"
mkdir -p "$PKG/opt/mypa" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/DEBIAN"
cp -r mypa web mypa.example.jsonc README.md pyproject.toml setup_wizard.py "$PKG/opt/mypa/"
printf '#!/bin/sh\nexec python3 -m mypa "$@"\n' > "$PKG/usr/bin/mypa"
printf 'import sys; sys.path.insert(0, "/opt/mypa")\n' > "$PKG/opt/mypa/mypa.pth.hint"
sed "s|INSTALL_DIR|/opt/mypa|" mypa.desktop > "$PKG/usr/share/applications/mypa.desktop"
cat > "$PKG/DEBIAN/control" <<EOF
Package: mypa
Version: $VERSION
Architecture: all
Maintainer: myPA
Description: myPA - Personal AI agent (OpenCode-compatible)
 Depends: python3 (>= 3.10), python3-requests
EOF
dpkg-deb --build "$PKG"
echo "Built $PKG.deb — install with:  sudo dpkg -i $PKG.deb"

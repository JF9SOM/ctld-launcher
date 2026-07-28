#!/usr/bin/env bash
# build-appimage.sh — wrap the PyInstaller output into a Linux AppImage
#
# Prerequisites (installed by CI before this script runs):
#   - appimagetool  (downloaded as AppImage, placed in PATH, or fetched below)
#   - PyInstaller dist/ctld-launcher/ already built
#
# Output: dist/ctld-launcher-x86_64.AppImage

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
COLLECT_DIR="$DIST_DIR/ctld-launcher"
APPDIR="$DIST_DIR/AppDir"

# --------------------------------------------------------------------------- #
# Sanity check
# --------------------------------------------------------------------------- #
if [[ ! -d "$COLLECT_DIR" ]]; then
    echo "ERROR: PyInstaller output not found at $COLLECT_DIR" >&2
    echo "       Run 'pyinstaller scripts/ctld-launcher.spec' first." >&2
    exit 1
fi

# --------------------------------------------------------------------------- #
# Build AppDir structure
# --------------------------------------------------------------------------- #
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller output into AppDir
cp -r "$COLLECT_DIR/." "$APPDIR/usr/bin/"

# AppRun entry point
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/usr/bin:${LD_LIBRARY_PATH:-}"
exec "$HERE/usr/bin/ctld-launcher" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# .desktop file (required by AppImage spec)
cat > "$APPDIR/usr/share/applications/ctld-launcher.desktop" << 'EOF'
[Desktop Entry]
Name=ctld-launcher
Comment=Hamlib rigctld/rotctld launcher
Exec=ctld-launcher
Icon=ctld-launcher
Type=Application
Categories=HamRadio;
EOF
ln -sf usr/share/applications/ctld-launcher.desktop "$APPDIR/ctld-launcher.desktop"

# App icon
ICON_SRC="$REPO_ROOT/assets/icon_256.png"
if [[ ! -f "$ICON_SRC" ]]; then
    echo "ERROR: $ICON_SRC not found — run 'python assets/generate_icons.py' first." >&2
    exit 1
fi
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ctld-launcher.png"
ln -sf usr/share/icons/hicolor/256x256/apps/ctld-launcher.png "$APPDIR/ctld-launcher.png"

# --------------------------------------------------------------------------- #
# Download appimagetool if not in PATH
# --------------------------------------------------------------------------- #
if ! command -v appimagetool &>/dev/null; then
    echo "Downloading appimagetool..."
    TOOL="$DIST_DIR/appimagetool-x86_64.AppImage"
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
    APPIMAGETOOL="$TOOL"
else
    APPIMAGETOOL="appimagetool"
fi

# --------------------------------------------------------------------------- #
# Build AppImage
# --------------------------------------------------------------------------- #
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$DIST_DIR/ctld-launcher-x86_64.AppImage"

echo ""
echo "AppImage created: $DIST_DIR/ctld-launcher-x86_64.AppImage"

#!/usr/bin/env bash
# generate-icns.sh — build assets/icon.icns from assets/icon_1024.png
#
# macOS-only (uses the native sips/iconutil tools, no extra dependency).
# Must run *before* `pyinstaller scripts/ctld-launcher.spec` — that spec
# reads assets/icon.icns to set the .app bundle's icon, so generating it
# afterwards would have no effect on the already-built bundle.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICON_PNG="$REPO_ROOT/assets/icon_1024.png"
ICON_ICNS="$REPO_ROOT/assets/icon.icns"

if [[ ! -f "$ICON_PNG" ]]; then
    echo "ERROR: $ICON_PNG not found — run 'python assets/generate_icons.py' first." >&2
    exit 1
fi

ICONSET="$REPO_ROOT/dist/icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICON_ICNS"
rm -rf "$ICONSET"

echo "Generated $ICON_ICNS"

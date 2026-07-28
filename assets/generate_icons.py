"""Generates the placeholder app icon set from a single vector-ish drawing.

Not wired into CI — run manually (`python assets/generate_icons.py`) when
the icon design changes. Produces:
  - icon_{16,32,48,64,128,256,512}.png  (Linux/AppImage, Qt window icon)
  - icon.ico                            (Windows)
  - icon_1024.png                       (source for macOS .icns, generated
                                          on the macOS CI runner via
                                          `sips`/`iconutil`, not here)

Reuses the same purple mark as ui/tray.py's app_icon() for visual
consistency between the taskbar/dock icon and the tray icon.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PURPLE = (127, 119, 221, 255)  # c-purple 400, matches ui/tray.py app_icon()
PURPLE_DARK = (38, 33, 92, 255)  # c-purple 900
WHITE = (255, 255, 255, 255)

OUTPUT_DIR = Path(__file__).parent
SIZES = [16, 32, 48, 64, 128, 256, 512]
SOURCE_SIZE = 1024


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = round(size * 0.04)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=PURPLE, outline=PURPLE_DARK, width=max(1, size // 64))

    cx, cy = size / 2, size * 0.62
    mast_w = max(1, round(size * 0.045))
    draw.line([(cx, size * 0.22), (cx, cy)], fill=WHITE, width=mast_w)
    draw.ellipse(
        [cx - mast_w * 1.4, cy - mast_w * 1.4, cx + mast_w * 1.4, cy + mast_w * 1.4], fill=WHITE
    )

    arc_w = max(1, round(size * 0.035))
    for i, radius_frac in enumerate((0.16, 0.28, 0.40)):
        r = size * radius_frac
        bbox = [cx - r, size * 0.22 - r, cx + r, size * 0.22 + r]
        draw.arc(bbox, start=290 - i * 6, end=250 + i * 6, fill=WHITE, width=arc_w)

    return img


def main() -> None:
    source = draw_icon(SOURCE_SIZE)
    source.save(OUTPUT_DIR / f"icon_{SOURCE_SIZE}.png")

    pngs: list[Image.Image] = []
    for size in SIZES:
        resized = source.resize((size, size), Image.LANCZOS)
        resized.save(OUTPUT_DIR / f"icon_{size}.png")
        pngs.append(resized)

    ico_sizes = [(s, s) for s in (16, 32, 48, 256)]
    source.save(OUTPUT_DIR / "icon.ico", sizes=ico_sizes)

    print(f"Wrote {len(SIZES)} PNGs, icon_{SOURCE_SIZE}.png, and icon.ico to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

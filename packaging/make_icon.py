"""Generate packaging/icon.ico: rounded-square pastel cream tile, charcoal "V".

Run: backend/.venv/Scripts/python.exe packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "icon.ico"
CREAM = (239, 237, 230, 255)      # #EFEDE6
CHARCOAL = (47, 46, 44, 255)      # warm charcoal
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_tile(size: int) -> Image.Image:
    scale = 4  # supersample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(s * 0.22)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=CREAM)

    # charcoal "V": two thick rounded strokes meeting at the bottom
    stroke = max(2, int(s * 0.13))
    x0, x1 = int(s * 0.26), int(s * 0.74)
    y0, y1 = int(s * 0.28), int(s * 0.74)
    cx = s // 2
    draw.line([x0, y0, cx, y1], fill=CHARCOAL, width=stroke)
    draw.line([x1, y0, cx, y1], fill=CHARCOAL, width=stroke)
    # rounded caps
    cap = stroke / 2
    for px, py in ((x0, y0), (x1, y0), (cx, y1)):
        draw.ellipse([px - cap, py - cap, px + cap, py + cap], fill=CHARCOAL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    base = draw_tile(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

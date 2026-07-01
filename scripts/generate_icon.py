"""Generate the IA Halo app icon PNG and ICO sizes."""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icons" / "app_icon.png"


def draw_icon(size: int = 256) -> Image.Image:
    """Render the octagonal IA monogram icon at ``size`` by ``size`` pixels."""
    img = Image.new("RGBA", (size, size), (10, 14, 20, 255))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r = size * 0.42

    # Octagon field
    chamfer = size * 0.08
    oct_pts = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 8
        oct_pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(oct_pts, outline=(0, 229, 255, 220), fill=(10, 20, 35, 200))

    # Halo arcs
    bbox = [cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72]
    draw.arc(bbox, start=200, end=340, fill=(0, 229, 255, 255), width=max(2, size // 64))
    draw.arc(bbox, start=20, end=160, fill=(124, 58, 237, 200), width=max(2, size // 64))

    # IA monogram
    try:
        font = ImageFont.truetype("consola.ttf", size=int(size * 0.28))
    except OSError:
        font = ImageFont.load_default()
    text = "IA"
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    draw.text((cx - tw / 2, cy - th / 2 - size * 0.02), text, fill=(232, 244, 255, 255), font=font)

    # 12 o'clock tick
    draw.ellipse([cx - 3, cy - r * 0.55 - 3, cx + 3, cy - r * 0.55 + 3], fill=(192, 38, 211, 255))
    return img


def main() -> None:
    """Write PNG, ICO, and scaled icon files under ``assets/icons/``."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = draw_icon(256)
    icon.save(OUT)
    ico_path = OUT.with_suffix(".ico")
    icon.save(ico_path, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
    for s in (16, 32, 48, 64, 128):
        icon.resize((s, s), Image.Resampling.LANCZOS).save(OUT.with_name(f"app_icon_{s}.png"))
    print(f"Saved {OUT}")
    print(f"Saved {ico_path}")


if __name__ == "__main__":
    main()

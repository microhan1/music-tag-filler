"""Draw assets/splash.png, the picture the one-file exe shows while it unpacks (build.bat --splash).

    python assets/make_splash.py

The app icon (make_icon.draw) and the name "Music Tag Filler", which is the English title and
the name of the exe; the picture carries no other words, so it serves all four languages.
Drawn at 4x and scaled down so the edges stay clean; kept small (optimize=True).
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_icon  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCALE = 4
W, H = 340, 104
INK, RULE = "#1f2937", "#d1d5db"  # gui.TEXT and gui.BORDER
ICON = 56
FONT = r"C:\Windows\Fonts\segoeuib.ttf"
TEXT = "Music Tag Filler"


def main(path: str) -> None:
    s = SCALE
    img = Image.new("RGB", (W * s, H * s), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * s - 1, H * s - 1), outline=RULE, width=s)
    icon = make_icon.draw(ICON * s)
    img.paste(icon, (24 * s, (H - ICON) // 2 * s), icon)
    font = ImageFont.truetype(FONT, 29 * s)
    x = (24 + ICON + 16) * s
    width = d.textlength(TEXT, font=font)
    assert x + width <= (W - 16) * s, f"text too wide: {width / s:.0f}px"
    d.text((x, H // 2 * s), TEXT, font=font, fill=INK, anchor="lm")
    img.resize((W, H), Image.LANCZOS).save(path, optimize=True)
    print(path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "splash.png"))

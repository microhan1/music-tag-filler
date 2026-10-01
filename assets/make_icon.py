"""Draw the app icon and write assets/icon.ico (multi-size) and assets/icon.png.

    python assets/make_icon.py

A white beamed note on the app's accent blue, with a small amber tag in the
corner: music + tag. Drawn at 4x and scaled down so the small sizes stay clean.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024  # working canvas
BLUE_TOP = (59, 130, 246)
BLUE_BOTTOM = (29, 78, 216)
WHITE = (255, 255, 255)
AMBER = (251, 191, 36)
AMBER_DARK = (217, 119, 6)


def _gradient(size: int) -> Image.Image:
    im = Image.new("RGB", (size, size))
    px = im.load()
    for y in range(size):
        t = y / (size - 1)
        row = tuple(round(BLUE_TOP[i] + (BLUE_BOTTOM[i] - BLUE_TOP[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = row
    return im


def draw(size: int = SIZE) -> Image.Image:
    s = size / 1024
    base = _gradient(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40 * s, 40 * s, 984 * s, 984 * s), radius=220 * s, fill=255)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(icon)

    # beamed note: two heads, two stems, a slanted beam
    def head(cx: float, cy: float) -> None:
        w, h = 150 * s, 112 * s
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse((cx - w, cy - h, cx + w, cy + h), fill=WHITE)
        layer = layer.rotate(20, center=(cx, cy), resample=Image.BICUBIC)
        icon.alpha_composite(layer)

    head(330 * s, 720 * s)
    head(660 * s, 640 * s)
    stem = 46 * s
    d.rectangle((430 * s, 300 * s, 430 * s + stem, 720 * s), fill=WHITE)
    d.rectangle((760 * s, 220 * s, 760 * s + stem, 640 * s), fill=WHITE)
    d.polygon([(430 * s, 300 * s), (760 * s + stem, 220 * s), (760 * s + stem, 350 * s), (430 * s, 430 * s)], fill=WHITE)

    # tag badge, bottom right
    tag = [(600 * s, 770 * s), (690 * s, 690 * s), (900 * s, 690 * s), (900 * s, 900 * s), (690 * s, 900 * s), (600 * s, 820 * s)]
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 10 * s, y + 14 * s) for x, y in tag], fill=(0, 0, 0, 70))
    icon.alpha_composite(shadow)
    d = ImageDraw.Draw(icon)
    d.polygon(tag, fill=AMBER)
    d.line(tag + [tag[0]], fill=AMBER_DARK, width=max(1, round(10 * s)), joint="curve")
    d.ellipse((668 * s, 768 * s, 722 * s, 822 * s), fill=BLUE_BOTTOM)  # the tag's hole
    for y in (752, 800, 848):  # text lines on the tag
        d.rounded_rectangle((760 * s, y * s, 868 * s, (y + 22) * s), radius=10 * s, fill=AMBER_DARK)
    return icon


def main() -> None:
    big = draw(SIZE)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon.ico"), sizes=[(n, n) for n in sizes])
    print("wrote", os.path.join(HERE, "icon.ico"), "and icon.png")


if __name__ == "__main__":
    main()

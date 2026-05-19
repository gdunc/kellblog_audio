#!/usr/bin/env python3
"""Generate 3000x3000 show artwork PNG."""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install pillow") from None

OUT = Path(__file__).resolve().parents[1] / "src" / "kellblog_audio" / "assets" / "show-artwork.png"
SIZE = 3000


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), color=(26, 35, 50))
    draw = ImageDraw.Draw(img)
    margin = 200
    draw.rectangle(
        [margin, margin, SIZE - margin, SIZE - margin],
        outline=(220, 180, 90),
        width=12,
    )
    try:
        font_lg = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 220)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 90)
    except OSError:
        font_lg = ImageFont.load_default()
        font_sm = font_lg

    draw.text((SIZE // 2, 1100), "Kellblog", fill=(255, 255, 255), anchor="mm", font=font_lg)
    draw.text(
        (SIZE // 2, 1400),
        "Audio",
        fill=(220, 180, 90),
        anchor="mm",
        font=font_lg,
    )
    draw.text(
        (SIZE // 2, 1750),
        "Dave Kellogg on\nEnterprise Software Startups",
        fill=(200, 200, 200),
        anchor="mm",
        font=font_sm,
        align="center",
    )
    img.save(OUT, "PNG", optimize=True)
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

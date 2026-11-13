#!/usr/bin/env python3
"""Generate 3000x3000 show artwork PNG (bold editorial concepts).

    uv run python scripts/generate_artwork.py            # writes the chosen concept to assets
    uv run python scripts/generate_artwork.py --preview DIR   # writes all concepts + a thumbnail sheet
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from kellblog_audio.config import ARTWORK_FILENAME

OUT = Path(__file__).resolve().parents[1] / "src" / "kellblog_audio" / "assets" / ARTWORK_FILENAME
SIZE = 3000
CHOSEN = "cobalt"

DIN_COND = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
AVENIR_NEXT = "/System/Library/Fonts/Avenir Next.ttc"

# Waveform heights (0..1): noisy speech envelope that trends upward like a growth chart.
WAVE = [0.18, 0.30, 0.22, 0.40, 0.28, 0.46, 0.34, 0.55, 0.42, 0.62, 0.50, 0.70,
        0.58, 0.78, 0.66, 0.86, 0.74, 0.94, 0.82, 1.00]


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


def avenir(size: int, weight: str = "Demi Bold") -> ImageFont.FreeTypeFont:
    # Avenir Next.ttc faces: pick by style name for robustness.
    for i in range(12):
        try:
            f = ImageFont.truetype(AVENIR_NEXT, size, index=i)
        except OSError:
            break
        if f.getname()[1] == weight:
            return f
    return ImageFont.truetype(AVENIR_NEXT, size)


def fit_width(path: str, text: str, width: int, index: int = 0) -> ImageFont.FreeTypeFont:
    """Largest font size whose rendered ink width fits `width`."""
    lo, hi = 50, 3000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = font(path, mid, index)
        l, _, r, _ = f.getbbox(text)
        if r - l <= width:
            lo = mid
        else:
            hi = mid - 1
    return font(path, lo, index)


def draw_text_ink(draw, x, y_top, text, f, fill, align="left", width=None, tracking=0):
    """Place text by its ink box top (not baseline), optional letter tracking."""
    if tracking:
        chars = list(text)
        widths = [f.getlength(c) for c in chars]
        total = sum(widths) + tracking * (len(chars) - 1)
        cx = x if align == "left" else x + (width - total) / 2
        top = f.getbbox(text)[1]
        for c, w in zip(chars, widths):
            draw.text((cx, y_top - top), c, font=f, fill=fill)
            cx += w + tracking
        return
    l, t, r, b = f.getbbox(text)
    if align == "center":
        x = x + (width - (r - l)) / 2
    draw.text((x - l, y_top - t), text, font=f, fill=fill)


def ink_height(f, text):
    _, t, _, b = f.getbbox(text)
    return b - t


def waveform(draw, x0, y_base, width, height, color, bars=WAVE, gap_ratio=0.38, round_=True):
    n = len(bars)
    step = width / n
    bw = step * (1 - gap_ratio)
    for i, h in enumerate(bars):
        bx = x0 + i * step
        bh = max(bw, h * height)
        rect = [bx, y_base - bh, bx + bw, y_base]
        if round_:
            draw.rounded_rectangle(rect, radius=bw / 2, fill=color)
        else:
            draw.rectangle(rect, fill=color)


def concept_ink() -> Image.Image:
    """Near-black, cream wordmark, orange waveform/growth bars, big byline."""
    bg, cream, accent, muted = (17, 19, 24), (244, 238, 226), (255, 106, 61), (160, 160, 168)
    img = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)
    m = 260
    w = SIZE - 2 * m
    f = fit_width(DIN_COND, "KELLBLOG", w)
    y = 560
    draw_text_ink(d, m, y, "KELLBLOG", f, cream)
    y += ink_height(f, "KELLBLOG") + 90
    fa = fit_width(DIN_COND, "AUDIO", int(w * 0.52))
    draw_text_ink(d, m, y, "AUDIO", fa, accent)
    ah = ink_height(fa, "AUDIO")
    wx = m + int(w * 0.52) + 110
    waveform(d, wx, y + ah, SIZE - m - wx, ah, accent)
    # byline block anchored to bottom
    fb = avenir(230, "Bold")
    fy = SIZE - m - 330
    d.rectangle([m, fy - 120, m + 300, fy - 98], fill=accent)
    draw_text_ink(d, m, fy, "DAVE KELLOGG", fb, cream, tracking=16)
    draw_text_ink(d, m, fy + ink_height(fb, "DAVE KELLOGG") + 70,
                  "ON ENTERPRISE SOFTWARE STARTUPS", avenir(92, "Demi Bold"), muted, tracking=12)
    return img


def concept_cobalt() -> Image.Image:
    """Saturated cobalt, bars as hero, wordmark + byline, vertically centred."""
    bg, cream, accent = (28, 58, 214), (247, 243, 233), (255, 140, 56)
    img = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)
    m = 260
    w = SIZE - 2 * m
    bars_h, gap1, gap2 = 820, 170, 150
    f = fit_width(DIN_COND, "KELLBLOG", w)
    kh = ink_height(f, "KELLBLOG")
    fl = avenir(172, "Bold")
    lh = ink_height(fl, "AUDIO")
    total = bars_h + gap1 + kh + gap2 + lh
    y = (SIZE - total) // 2
    base = y + bars_h
    waveform(d, m, base, w, bars_h, cream, gap_ratio=0.40)
    n = len(WAVE)
    step = w / n
    bw = step * 0.60
    bx = m + (n - 1) * step
    d.rounded_rectangle([bx, base - bars_h, bx + bw, base], radius=bw / 2, fill=accent)
    y = base + gap1
    draw_text_ink(d, m, y, "KELLBLOG", f, cream)
    y += kh + gap2
    draw_text_ink(d, m, y, "AUDIO", fl, accent, tracking=34)
    aw = sum(fl.getlength(c) for c in "AUDIO") + 34 * 4
    draw_text_ink(d, m + aw + 120, y, "DAVE KELLOGG", fl, cream, tracking=16)
    return img


def concept_paper() -> Image.Image:
    """Warm paper, black stacked type, red band carrying AUDIO + waveform."""
    bg, ink, red, cream = (241, 234, 220), (20, 20, 22), (214, 48, 39), (241, 234, 220)
    img = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)
    m = 260
    w = SIZE - 2 * m
    f = fit_width(DIN_COND, "BLOG", int(w * 0.74))
    y = 250
    draw_text_ink(d, m, y, "KELL", f, ink)
    y += ink_height(f, "KELL") + 70
    draw_text_ink(d, m, y, "BLOG", f, ink)
    y += ink_height(f, "BLOG") + 150
    d.rectangle([0, y, SIZE, SIZE], fill=red)
    fa = avenir(230, "Heavy")
    ah = ink_height(fa, "AUDIO")
    ay = y + 170
    draw_text_ink(d, m, ay, "AUDIO", fa, cream, tracking=40)
    waveform(d, m + 1080, ay + ah, w - 1080, ah, cream)
    draw_text_ink(d, m, ay + ah + 150, "DAVE KELLOGG", avenir(150, "Bold"), cream, tracking=16)
    return img


CONCEPTS = {"ink": concept_ink, "cobalt": concept_cobalt, "paper": concept_paper}


def preview(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    imgs = {}
    for name, fn in CONCEPTS.items():
        img = fn()
        img.save(out_dir / f"concept-{name}.png", optimize=True)
        imgs[name] = img
    # Sheet: each concept large (900) + phone-grid size (180) + tiny (60)
    big, mid, small, pad = 900, 180, 60, 60
    sheet = Image.new("RGB", (len(imgs) * (big + pad) + pad, big + mid + 3 * pad), (40, 40, 44))
    for i, img in enumerate(imgs.values()):
        x = pad + i * (big + pad)
        sheet.paste(img.resize((big, big), Image.LANCZOS), (x, pad))
        sheet.paste(img.resize((mid, mid), Image.LANCZOS), (x, big + 2 * pad))
        sheet.paste(img.resize((small, small), Image.LANCZOS), (x + mid + pad, big + 2 * pad + mid - small))
    sheet.save(out_dir / "concepts-sheet.png")
    print(f"Wrote concepts to {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write all concepts + sheet to this dir")
    ap.add_argument("--concept", default=CHOSEN, choices=sorted(CONCEPTS))
    args = ap.parse_args()
    if args.preview:
        preview(args.preview)
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    CONCEPTS[args.concept]().save(OUT, "PNG", optimize=True)
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

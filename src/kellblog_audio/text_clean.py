"""Normalize extracted HTML/text for TTS."""

from __future__ import annotations

import html
import re
import unicodedata

from kellblog_audio.footnotes import prepare_for_tts
from kellblog_audio.glossary import apply_glossary

SMART_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": " — ",
    "\u2026": "...",
    "\u00a0": " ",
}


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for src, dst in SMART_MAP.items():
        text = text.replace(src, dst)
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    return text


def strip_site_suffix(title: str) -> str:
    for suffix in (" | Kellblog", " - Kellblog", " — Kellblog"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title.strip()


def html_to_plain(fragment: str) -> str:
    """Minimal HTML to plain text."""
    text = html.unescape(fragment)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>\s*", "\n\n", text, flags=re.I)
    text = re.sub(r"</li>\s*", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"<h[1-6][^>]*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</h[1-6]>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_for_tts(
    text: str,
    *,
    inline_footnotes: bool = False,
    image_disclaimer: bool = False,
) -> str:
    text = normalize_unicode(text)
    text = html_to_plain(text) if "<" in text else text
    text = re.sub(r"\?ref=kellblog\.com", "", text)
    text = prepare_for_tts(text, inline_footnotes=inline_footnotes)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" ?— ?", " — ", text)
    # Lists: pause between bullets
    text = re.sub(r"•\s*", "Next: ", text)
    text = apply_glossary(text)
    if image_disclaimer:
        text = (
            "Note: this post includes images; see the original post on Kellblog for visuals. "
            + text
        )
    return text.strip()


def excerpt_from_body(body: str, max_chars: int = 600) -> str:
    plain = html_to_plain(body) if "<" in body else body
    plain = normalize_unicode(plain)
    if len(plain) <= max_chars:
        return plain
    cut = plain[:max_chars]
    last_period = cut.rfind(". ")
    if last_period > max_chars // 2:
        return cut[: last_period + 1].strip() + "…"
    return cut.strip() + "…"

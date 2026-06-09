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

_MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

_MAGNITUDE_WORDS = {
    "K": "thousand",
    "M": "million",
    "MM": "million",
    "B": "billion",
    "BN": "billion",
    "T": "trillion",
    "TN": "trillion",
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


def _remove_initialism_dots(match: re.Match[str]) -> str:
    trailing_space = " " if match.group(0)[-1].isspace() else ""
    return " ".join(re.findall(r"[A-Z]", match.group(0))) + trailing_space


def _replace_dollar_amount(match: re.Match[str]) -> str:
    amount = match.group(1)
    magnitude = match.group(2)
    if magnitude:
        return f"{amount} {_MAGNITUDE_WORDS[magnitude.upper()]} dollars"
    suffix = "dollar" if amount in {"1", "1.0", "1.00"} else "dollars"
    return f"{amount} {suffix}"


def _replace_magnitude(match: re.Match[str]) -> str:
    amount = match.group(1)
    magnitude = match.group(2).upper()
    return f"{amount} {_MAGNITUDE_WORDS[magnitude]}"


def _replace_slash_date(match: re.Match[str]) -> str:
    month = int(match.group(1))
    day = int(match.group(2))
    year = match.group(3)
    if month not in _MONTH_NAMES or not (1 <= day <= 31):
        return match.group(0)
    if year:
        year_number = int(year)
        if len(year) == 2:
            year_number += 2000 if year_number <= 30 else 1900
        return f"{_MONTH_NAMES[month]} {day}, {year_number}"
    return f"{_MONTH_NAMES[month]} {day}"


def _verbalize_symbols(text: str) -> str:
    """Make compact written notation less surprising when read aloud."""
    text = re.sub(
        r"\bDownload\s+\S*(?:%[0-9A-Fa-f]{2}|_)\S*\b",
        "Download the linked file",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\$(\d+)s\s+of\s+millions\b",
        "tens of millions of dollars",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\$(\d+)in(\s+V\s*C)\b",
        r"\1 million dollars in\2",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\$(\d+(?:\.\d+)?)(MM|BN|TN|[KMBT])?\b",
        _replace_dollar_amount,
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(\d+(?:\.\d+)?)(MM|BN|TN|[KMBT])/(year|month|week|day)\b",
        lambda m: f"{m.group(1)} {_MAGNITUDE_WORDS[m.group(2).upper()]} per {m.group(3)}",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(\d+(?:\.\d+)?)(MM|BN|TN|[KMBT])\b", _replace_magnitude, text, flags=re.I
    )
    text = re.sub(
        r"\b(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\b",
        r"\1 to \2 to \3",
        text,
    )
    text = re.sub(
        r"\b(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(x)?\b",
        lambda m: f"{m.group(1)} to {m.group(2)}{' times' if m.group(3) else ''}",
        text,
    )
    text = re.sub(r"\b(\d+(?:\.\d+)?)x\b", r"\1 times", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*%", r"\1 percent", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\^2\b", r"\1 squared", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\^3\b", r"\1 cubed", text)
    text = re.sub(r"\^([A-Za-z])\b", r" to the \1", text)
    text = re.sub(r"\^(\d+)\b", r" to the \1", text)
    text = re.sub(r"#\s*(\d+)", r"number \1", text)
    text = re.sub(r"(?<!\w)@([A-Za-z][A-Za-z0-9_]*)", r"at \1", text)
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", _replace_slash_date, text)
    text = re.sub(r"\band/or\b", "and or", text, flags=re.I)
    text = re.sub(r"\bhis/her\b", "his or her", text, flags=re.I)
    text = re.sub(r"\b([A-Za-z]+)s/salesrep\b", r"\1s per sales rep", text, flags=re.I)
    text = re.sub(r"\b([A-Za-z]+)s/day\b", r"\1s per day", text, flags=re.I)
    text = re.sub(r"\b([A-Za-z]+)s/week\b", r"\1s per week", text, flags=re.I)
    text = re.sub(r"\s+/\s+", " slash ", text)
    text = re.sub(r"(?<=\w)/(?=\w)", " slash ", text)
    text = re.sub(r"(?<=\w)&(?=\w)", " and ", text)
    text = re.sub(r"(?<=\w)@(?=\w)", " at ", text)
    text = re.sub(r"(?<=\s)&(?=\s)", "and", text)
    text = text.replace("&", " and ")
    text = re.sub(r"(?<=\s)@(?=\s)", "at", text)
    text = re.sub(r"\s*--\s*", " — ", text)
    return text


def _repair_legacy_import_artifacts(text: str) -> str:
    """Fix obvious old-post import artifacts that read badly in audio."""
    text = re.sub(r"\b([A-Za-z]+)'\s+([A-Za-z])", r"\1'\2", text)
    text = re.sub(r"\bFamous Last WordsI\b", "Famous Last Words. I", text)
    text = re.sub(r"\bSpringsteenThe\b", "Springsteen. The", text)
    text = re.sub(r"\bLevittAt\b", "Levitt. At", text)
    text = re.sub(r"\)(?=[A-Z][a-z])", "). ", text)
    text = re.sub(r"\ba\.k\.a\.?", "also known as", text, flags=re.I)
    text = re.sub(r"\ba\.m\.?", "A M", text, flags=re.I)
    text = re.sub(r"\bp\.m\.?", "P M", text, flags=re.I)
    replacements = (
        (r"\bfor year\b", "for a year"),
        (r"\bpre-attachment to\b", "predilection for"),
        (r"\bhave all start to show interest\b", "have all started to show interest"),
        (r"\bfor application such as\b", "for applications such as"),
        (
            r"\bnee MD-DBMSs\b",
            "formerly called multidimensional database management systems",
        ),
        (
            r"\bnée MD-DBMSs\b",
            "formerly called multidimensional database management systems",
        ),
        (
            r"\bMD-DBMSs\b",
            "multidimensional database management systems",
        ),
        (
            r"\bMD-DBMS\b",
            "multidimensional database management system",
        ),
        (r"\ba la Sybase IQ\b", "such as Sybase I Q"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


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
    text = re.sub(r"https?://[^\s<>()]+", "the linked page", text)
    text = re.sub(r"\bwww\.[^\s<>()]+", "the linked page", text)
    text = re.sub(r"\b(?:[A-Z]\.\s*){2,}", _remove_initialism_dots, text)
    text = re.sub(r"\be\.g\.,?", "for example,", text, flags=re.I)
    text = re.sub(r"\bi\.e\.,?", "that is,", text, flags=re.I)
    text = _repair_legacy_import_artifacts(text)
    text = _verbalize_symbols(text)
    text = prepare_for_tts(text, inline_footnotes=inline_footnotes)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" ?— ?", " — ", text)
    # Lists: keep item boundaries without adding a word that gets read aloud.
    text = re.sub(r"•\s*", "", text)
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

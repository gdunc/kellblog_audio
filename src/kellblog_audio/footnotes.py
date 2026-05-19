"""Footnote handling: move Notes section to end for TTS."""

from __future__ import annotations

import re

NOTES_HEADER = re.compile(
    r"^(#{1,3}\s+)?notes\s*$",
    re.IGNORECASE | re.MULTILINE,
)
INLINE_NOTE = re.compile(r"\[(\d+)\]")


def split_body_and_notes(text: str) -> tuple[str, str | None]:
    """Split main body from Notes section if present."""
    match = NOTES_HEADER.search(text)
    if not match:
        return text, None
    body = text[: match.start()].rstrip()
    notes = text[match.start() :].strip()
    return body, notes


def strip_inline_note_markers(text: str) -> str:
    return INLINE_NOTE.sub("", text)


def prepare_for_tts(text: str, inline_footnotes: bool = False) -> str:
    body, notes = split_body_and_notes(text)
    if inline_footnotes:
        return text
    body = strip_inline_note_markers(body)
    if notes:
        notes_clean = strip_inline_note_markers(notes)
        # Remove markdown heading markers for spoken notes
        notes_clean = re.sub(r"^#+\s*", "", notes_clean, flags=re.MULTILINE)
        return body + "\n\nNotes follow.\n\n" + notes_clean
    return body

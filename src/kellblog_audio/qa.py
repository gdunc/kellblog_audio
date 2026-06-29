"""Audio QA using local Whisper transcripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import (
    MAX_AUDIO_BODY_WPM,
    QA_TRANSCRIPTS_DIR,
    WHISPER_CLI,
    WHISPER_MODEL,
    get_settings,
)
from kellblog_audio.intro_outro import SPOKEN_OUTRO, spoken_intro


MIN_SOURCE_COVERAGE = 0.85
MIN_TAIL_SIMILARITY = 0.70
MAX_REPEATED_THREE_GRAM = 12

KNOWN_ACRONYMS = {
    "abm",
    "ai",
    "api",
    "arr",
    "asp",
    "atr",
    "bi",
    "cac",
    "ceo",
    "cfo",
    "cmo",
    "cpp",
    "crm",
    "cro",
    "dbms",
    "ecm",
    "eii",
    "emc",
    "epm",
    "erp",
    "faq",
    "gaap",
    "gsi",
    "gtm",
    "hp",
    "ibm",
    "icp",
    "ipo",
    "it",
    "kpi",
    "ltv",
    "mba",
    "ml",
    "mql",
    "mrr",
    "nps",
    "nrr",
    "odbms",
    "okr",
    "olap",
    "pe",
    "plg",
    "plm",
    "pmm",
    "rdbms",
    "rfid",
    "roi",
    "rto",
    "sap",
    "sdr",
    "sql",
    "tcv",
    "tla",
    "us",
    "usa",
    "vc",
    "vp",
    "xml",
}

CANONICAL_WORDS = {
    "apis": "api",
    "ceos": "ceo",
    "cmos": "cmo",
    "dbmss": "dbms",
    "kpis": "kpi",
    "mqls": "mql",
    "okrs": "okr",
    "rdmbs": "rdbms",
    "rdbmss": "rdbms",
    "sdrs": "sdr",
    "sequel": "sql",
    "tlAs".lower(): "tla",
    "vcs": "vc",
    "vps": "vp",
    "xquery": "xquery",
}


@dataclass
class TranscriptQAResult:
    passed: bool
    reason: str
    source_coverage: float
    tail_similarity: float
    max_repeated_three_gram: int
    body_wpm: float | None
    source_words: int
    transcript_words: int


def normalize_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())
    words = _collapse_spelled_acronyms(words)
    normalized: list[str] = []
    for word in words:
        if word in {"sas", "sass"}:
            normalized.append("saas")
        elif word == "x" and normalized and normalized[-1] == "query":
            normalized[-1] = "xquery"
        else:
            normalized.append(CANONICAL_WORDS.get(word, word))
    return normalized


def _collapse_spelled_acronyms(words: list[str]) -> list[str]:
    collapsed: list[str] = []
    i = 0
    while i < len(words):
        matched = False
        for size in range(6, 1, -1):
            group = words[i : i + size]
            if len(group) != size or not all(_is_spelled_letter(w) for w in group):
                continue
            joined = "".join(_letter_value(w) for w in group)
            if joined in KNOWN_ACRONYMS:
                collapsed.append(joined)
                i += size
                matched = True
                break
            if joined.endswith("s") and joined[:-1] in KNOWN_ACRONYMS:
                collapsed.append(joined[:-1])
                i += size
                matched = True
                break
        if matched:
            continue
        word = words[i]
        if word == "x" and i + 1 < len(words) and words[i + 1] == "query":
            collapsed.append("xquery")
            i += 2
            continue
        collapsed.append(_letter_value(word) if _is_spelled_letter(word) else word)
        i += 1
    return collapsed


def _is_spelled_letter(word: str) -> bool:
    return len(word) == 1 or (len(word) == 3 and word.endswith("'s"))


def _letter_value(word: str) -> str:
    return word[0]


def analyze_transcript(
    source_text: str,
    transcript_text: str,
    *,
    duration_sec: int | None = None,
    intro_text: str | None = None,
    outro_text: str | None = SPOKEN_OUTRO,
) -> TranscriptQAResult:
    source_words = normalize_words(source_text)
    transcript_words = _strip_known_intro_outro(
        normalize_words(transcript_text),
        intro_words=normalize_words(intro_text or ""),
        outro_words=normalize_words(outro_text or ""),
    )
    source_coverage = _source_coverage(source_words, transcript_words)
    tail_similarity = _tail_similarity(source_words, transcript_words)
    max_repeated = _max_repeated_ngram(transcript_words, n=3)
    body_wpm = None
    if duration_sec and duration_sec > 0:
        body_wpm = len(source_words) * 60.0 / duration_sec

    failures: list[str] = []
    if body_wpm is not None and body_wpm > MAX_AUDIO_BODY_WPM:
        failures.append(f"body wpm {body_wpm:.1f} > {MAX_AUDIO_BODY_WPM:g}")
    if source_coverage < MIN_SOURCE_COVERAGE:
        failures.append(f"coverage {source_coverage:.1%} < {MIN_SOURCE_COVERAGE:.0%}")
    if tail_similarity < MIN_TAIL_SIMILARITY:
        failures.append(
            f"tail similarity {tail_similarity:.1%} < {MIN_TAIL_SIMILARITY:.0%}"
        )
    if max_repeated > MAX_REPEATED_THREE_GRAM:
        failures.append(
            f"repetition {max_repeated} > {MAX_REPEATED_THREE_GRAM} repeated 3-grams"
        )

    return TranscriptQAResult(
        passed=not failures,
        reason="ok" if not failures else "; ".join(failures),
        source_coverage=source_coverage,
        tail_similarity=tail_similarity,
        max_repeated_three_gram=max_repeated,
        body_wpm=body_wpm,
        source_words=len(source_words),
        transcript_words=len(transcript_words),
    )


def transcribe_audio(
    audio_path: Path,
    *,
    output_dir: Path = QA_TRANSCRIPTS_DIR,
    output_stem: str | None = None,
) -> Path:
    whisper = shutil.which(WHISPER_CLI)
    if not whisper:
        raise RuntimeError(f"Local Whisper CLI not found: {WHISPER_CLI}")
    model = Path(WHISPER_MODEL).expanduser()
    if not model.exists():
        raise RuntimeError(f"Local Whisper model not found: {model}")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem or audio_path.stem
    out_base = output_dir / stem
    subprocess.run(
        [
            whisper,
            "-m",
            str(model),
            "-f",
            str(audio_path),
            "-l",
            "en",
            "-otxt",
            "-oj",
            "-of",
            str(out_base),
            "-np",
        ],
        check=True,
    )
    return out_base.with_suffix(".txt")


def qa_post_audio(
    catalog: Catalog,
    slug: str,
    *,
    output_dir: Path = QA_TRANSCRIPTS_DIR,
) -> TranscriptQAResult:
    post = catalog.get(slug)
    if not post or not post.text:
        raise ValueError(f"Post {slug} not ingested or has no text")
    if not post.audio_path:
        raise ValueError(f"Post {slug} has no audio path")
    audio_path = get_settings().root / post.audio_path
    transcript_path = transcribe_audio(audio_path, output_dir=output_dir, output_stem=slug)
    transcript = transcript_path.read_text(encoding="utf-8")
    intro = spoken_intro(post.title or slug, post.published_at or "1970-01-01T00:00:00Z")
    result = analyze_transcript(
        post.text,
        transcript,
        duration_sec=post.duration_sec,
        intro_text=intro,
        outro_text=SPOKEN_OUTRO,
    )
    report_path = output_dir / f"{slug}.qa.json"
    report_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return result


def queue_audio_rerun(catalog: Catalog, slug: str, reason: str) -> None:
    catalog.update_post(
        slug,
        audio_path=None,
        audio_bytes=None,
        audio_etag=None,
        audio_status="stale",
        audio_error=f"Audio QA failed; queued for rerun: {reason}"[:500],
        duration_sec=None,
        feed_published_at=None,
        backfill_run_id=None,
    )


def _source_coverage(source_words: list[str], transcript_words: list[str]) -> float:
    if not source_words:
        return 1.0
    matcher = SequenceMatcher(None, source_words, transcript_words, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(source_words)


def _tail_similarity(source_words: list[str], transcript_words: list[str]) -> float:
    if not source_words:
        return 1.0
    tail = source_words[-min(80, len(source_words)) :]
    if not transcript_words:
        return 0.0
    if len(transcript_words) <= len(tail):
        return SequenceMatcher(None, tail, transcript_words, autojunk=False).ratio()
    best = 0.0
    for start in range(0, len(transcript_words) - len(tail) + 1):
        window = transcript_words[start : start + len(tail)]
        score = SequenceMatcher(None, tail, window, autojunk=False).ratio()
        best = max(best, score)
    return best


def _strip_known_intro_outro(
    words: list[str],
    *,
    intro_words: list[str],
    outro_words: list[str],
) -> list[str]:
    words = _strip_boundary_segment(words, intro_words, from_start=True)
    return _strip_boundary_segment(words, outro_words, from_start=False)


def _strip_boundary_segment(
    words: list[str],
    segment: list[str],
    *,
    from_start: bool,
) -> list[str]:
    if not words or not segment:
        return words

    # Whisper may hear titles/acronyms differently, so trim a fuzzy boundary match.
    max_extra = 12
    min_len = max(1, len(segment) - max_extra)
    max_len = min(len(words), len(segment) + max_extra)
    best_len = 0
    best_score = 0.0
    for size in range(min_len, max_len + 1):
        candidate = words[:size] if from_start else words[-size:]
        score = SequenceMatcher(None, segment, candidate, autojunk=False).ratio()
        if score > best_score:
            best_score = score
            best_len = size

    if best_score < 0.60 or best_len == 0:
        return words
    return words[best_len:] if from_start else words[:-best_len]


def _max_repeated_ngram(words: list[str], *, n: int) -> int:
    if len(words) < n:
        return 0
    counts = Counter(tuple(words[i : i + n]) for i in range(len(words) - n + 1))
    return max(counts.values(), default=0)

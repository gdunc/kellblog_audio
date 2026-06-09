"""Generate the collaborator listening review page."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kellblog_audio.catalog import Catalog, PostRow
from kellblog_audio.config import OUTPUT_DIR, QA_TRANSCRIPTS_DIR

MIN_REVIEW_COVERAGE = 0.93
MIN_REVIEW_TAIL = 0.82
MAX_REVIEW_WPM = 200.0
MAX_REVIEW_REPEAT = 5


@dataclass
class ReviewItem:
    post: PostRow
    qa: dict[str, Any] | None
    concerns: list[str]


def concern_reasons(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return ["missing QA"]

    reasons: list[str] = []
    if data.get("passed") is not True:
        reasons.append(str(data.get("reason") or "QA failed"))

    coverage = _float_or_none(data.get("source_coverage"))
    if coverage is not None and coverage < MIN_REVIEW_COVERAGE:
        reasons.append(f"coverage {coverage:.1%}")

    tail = _float_or_none(data.get("tail_similarity"))
    if tail is not None and tail < MIN_REVIEW_TAIL:
        reasons.append(f"ending match {tail:.1%}")

    wpm = _float_or_none(data.get("body_wpm"))
    if wpm is not None and wpm >= MAX_REVIEW_WPM:
        reasons.append(f"pace {wpm:.0f} WPM")

    repeated = _int_or_none(data.get("max_repeated_three_gram"))
    if repeated is not None and repeated > MAX_REVIEW_REPEAT:
        reasons.append(f"repeat x{repeated}")

    return reasons


def collect_review_items(
    catalog: Catalog,
    *,
    qa_dir: Path = QA_TRANSCRIPTS_DIR,
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for post in catalog.list_by_filter(audio_status="done"):
        if not post.audio_path:
            continue
        qa = _read_qa(qa_dir / f"{post.slug}.qa.json")
        items.append(ReviewItem(post=post, qa=qa, concerns=concern_reasons(qa)))
    return items


def write_review_page(
    catalog: Catalog,
    *,
    out_path: Path = OUTPUT_DIR / "index.html",
    qa_dir: Path = QA_TRANSCRIPTS_DIR,
    updated_at: str | None = None,
) -> Path:
    items = collect_review_items(catalog, qa_dir=qa_dir)
    counts = catalog.counts()
    qa_passed = sum(1 for item in items if item.qa and item.qa.get("passed") is True)
    qa_artifacts = sum(1 for item in items if item.qa)
    concerning = [item for item in items if item.concerns]
    updated = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _render_page(
            items=items,
            concerning=concerning,
            qa_passed=qa_passed,
            qa_artifacts=qa_artifacts,
            counts=counts,
            updated_at=updated,
        ),
        encoding="utf-8",
    )
    _remove_stale_feedback_redirect(out_path.parent)
    return out_path


def _render_page(
    *,
    items: list[ReviewItem],
    concerning: list[ReviewItem],
    qa_passed: int,
    qa_artifacts: int,
    counts: dict[str, int],
    updated_at: str,
) -> str:
    episode_word = "MP3" if len(items) == 1 else "MP3s"
    cards = "\n".join(_render_article(item) for item in items)
    concerns = _render_concerns(concerning)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kellblog Audio Review Batch</title>
  <style>{_css()}</style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>Kellblog Audio Review Batch</h1>
      <p class="lede">AI-narrated Kellblog episodes ready for collaborator listening. Please focus on audio quality, pronunciation of technical terms and company names, repeated phrases, pacing, and whether endings feel complete.</p>
      <div class="status">
        <span class="pill ok">{qa_passed} QA passed</span>
        <span class="pill">{qa_artifacts} QA artifacts</span>
        <span class="pill">{counts.get("audio_pending", 0)} still rebuilding</span>
        <span class="pill">{counts.get("audio_skip", 0)} skipped</span>
        <span class="pill">{counts.get("publish_pending", 0)} publish pending</span>
        <span class="pill">Updated {html.escape(updated_at)}</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="review-brief" aria-labelledby="review-heading">
      <div>
        <h2 id="review-heading">What to review</h2>
        <p>Start with the manual-audit list, then sample a few normal episodes. Send notes in the same thread where this page was shared, with the episode title and timestamp when possible.</p>
      </div>
      <a class="feed-link" href="/feed.xml">RSS feed</a>
    </section>
    {concerns}
    <div class="toolbar">
      <span>{len(items)} published {episode_word} available for review.</span>
    </div>
    <section class="episodes" aria-label="Episodes">
{cards}
    </section>
  </main>
  <footer class="wrap">
    <div class="notes">
      Whisper QA transcribes each episode and checks the audio passes basic quality gates. Pace is words per minute from the Whisper transcript.
    </div>
  </footer>
</body>
</html>
"""


def _render_concerns(items: list[ReviewItem]) -> str:
    if not items:
        return """<section class="audit" aria-labelledby="audit-heading">
      <h2 id="audit-heading">Needs manual audit</h2>
      <p>No current QA warning thresholds were triggered.</p>
    </section>"""

    rows = "\n".join(
        "        "
        + f'<li><a href="#{_anchor(item.post.slug)}">{html.escape(item.post.title or item.post.slug)}</a>'
        + f' <span>{html.escape(", ".join(item.concerns))}</span></li>'
        for item in items
    )
    return f"""<section class="audit" aria-labelledby="audit-heading">
      <h2 id="audit-heading">Needs manual audit</h2>
      <p>These passed or have artifacts, but their metrics make them the best candidates to regenerate or spot-check before promotion.</p>
      <ol>
{rows}
      </ol>
    </section>"""


def _render_article(item: ReviewItem) -> str:
    post = item.post
    qa = item.qa or {}
    title = html.escape(post.title or post.slug)
    meta_bits = [_format_date(post.published_at), _format_duration(post.duration_sec)]
    if post.word_count:
        meta_bits.append(f"{post.word_count:,} words")
    concern_badge = ""
    concern_details = ""
    if item.concerns:
        concern_badge = '<span class="badge warn">Manual audit</span>'
        concern_details = (
            '<div class="concerns"><span>Review focus</span><strong>'
            + html.escape(", ".join(item.concerns))
            + "</strong></div>"
        )
    audio_url = _public_audio_path(post.audio_path)
    return f"""      <article id="{_anchor(post.slug)}">
        <div class="episode-head">
          <div>
            <h2>{title}</h2>
            <div class="meta">{html.escape(" · ".join(bit for bit in meta_bits if bit))}</div>
          </div>
          <div class="links">
            {concern_badge}
            <a href="{html.escape(post.url)}">Original</a>
            <a href="{html.escape(audio_url)}">MP3</a>
          </div>
        </div>
        <audio controls preload="metadata" src="{html.escape(audio_url)}"></audio>
        {concern_details}
        <div class="qa">
          <div class="metric"><span>Whisper QA</span><strong>{_qa_status(qa)}</strong></div>
          <div class="metric"><span>Pace</span><strong>{_wpm(qa.get("body_wpm"))}</strong></div>
        </div>
      </article>"""


def _css() -> str:
    return """
    :root {
      --bg: #f6f7f9;
      --surface: #ffffff;
      --ink: #17202a;
      --muted: #647184;
      --line: #d8dee8;
      --accent: #12646f;
      --accent-soft: #e6f3f4;
      --ok: #20744a;
      --warn: #8a5a00;
      --warn-soft: #fff4dc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }
    .wrap {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
    }
    header .wrap { padding: 28px 0 24px; }
    h1 {
      margin: 0 0 8px;
      font-size: 2rem;
      line-height: 1.15;
      letter-spacing: 0;
    }
    h2 {
      margin: 0;
      font-size: 1.15rem;
      line-height: 1.25;
      letter-spacing: 0;
    }
    .lede {
      max-width: 850px;
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }
    .status {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }
    .pill, .badge {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 4px 10px;
      background: var(--surface);
      color: var(--muted);
      font-size: 0.875rem;
      white-space: nowrap;
    }
    .pill.ok {
      border-color: #b7dbc9;
      background: #eef8f3;
      color: var(--ok);
      font-weight: 600;
    }
    .badge.warn {
      border-color: #e0bd70;
      background: var(--warn-soft);
      color: var(--warn);
      font-weight: 700;
    }
    main { padding: 24px 0 40px; }
    a {
      color: var(--accent);
      font-weight: 600;
      text-decoration: none;
    }
    a:hover { text-decoration: underline; }
    .review-brief, .audit {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 16px;
      padding: 18px;
    }
    .review-brief {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: start;
    }
    .review-brief p, .audit p {
      margin: 6px 0 0;
      color: var(--muted);
    }
    .feed-link {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      white-space: nowrap;
    }
    .feed-link:hover {
      background: var(--accent-soft);
      border-color: #9fcdd2;
    }
    .audit ol {
      margin: 12px 0 0;
      padding-left: 24px;
    }
    .audit li + li { margin-top: 6px; }
    .audit li span {
      color: var(--muted);
      font-size: 0.9rem;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin: 18px 0;
      color: var(--muted);
    }
    .episodes {
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }
    article {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .episode-head {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: start;
      margin-bottom: 12px;
    }
    .meta {
      margin-top: 4px;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    .links a {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 5px 9px;
      font-size: 0.875rem;
      white-space: nowrap;
    }
    .links a:hover {
      background: var(--accent-soft);
      border-color: #9fcdd2;
    }
    audio {
      display: block;
      width: 100%;
      margin: 8px 0 12px;
    }
    .concerns {
      border: 1px solid #e0bd70;
      border-radius: 6px;
      background: var(--warn-soft);
      margin-bottom: 10px;
      padding: 8px 10px;
    }
    .concerns span, .metric span {
      display: block;
      color: var(--muted);
      font-size: 0.76rem;
    }
    .concerns strong, .metric strong {
      display: block;
      margin-top: 2px;
      font-size: 0.95rem;
      overflow-wrap: anywhere;
    }
    .qa {
      display: grid;
      grid-template-columns: repeat(2, minmax(128px, 1fr));
      gap: 8px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fbfcfd;
      min-width: 0;
    }
    footer {
      color: var(--muted);
      font-size: 0.9rem;
      padding: 18px 0 36px;
    }
    .notes {
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }
    @media (max-width: 760px) {
      .review-brief, .episode-head { grid-template-columns: 1fr; }
      .links { justify-content: flex-start; }
    }
    @media (max-width: 460px) {
      .wrap { width: min(100% - 20px, 1120px); }
      header .wrap { padding-top: 22px; }
      h1 { font-size: 1.55rem; }
      article, .review-brief, .audit { padding: 14px; }
    }
    """


def _read_qa(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _remove_stale_feedback_redirect(output_dir: Path) -> None:
    feedback = output_dir / "feedback" / "index.html"
    feedback.unlink(missing_ok=True)
    try:
        feedback.parent.rmdir()
    except OSError:
        pass


def _public_audio_path(audio_path: str | None) -> str:
    if not audio_path:
        return ""
    path = audio_path.replace("\\", "/")
    if path.startswith("output/"):
        path = path[len("output/") :]
    if not path.startswith("/"):
        path = "/" + path
    return path


def _format_date(value: str | None) -> str:
    if not value:
        return ""
    return value[:10]


def _format_duration(duration_sec: int | None) -> str:
    if not duration_sec:
        return ""
    minutes, seconds = divmod(int(duration_sec), 60)
    return f"{minutes}:{seconds:02d}"


def _qa_status(data: dict[str, Any]) -> str:
    if not data:
        return "Missing"
    return "Pass" if data.get("passed") is True else "Fail"


def _pct(value: Any) -> str:
    number = _float_or_none(value)
    return "n/a" if number is None else f"{number:.1%}"


def _wpm(value: Any) -> str:
    number = _float_or_none(value)
    return "n/a" if number is None else f"{number:.0f} WPM"


def _repeat(value: Any) -> str:
    number = _int_or_none(value)
    return "n/a" if number is None else str(number)


def _anchor(slug: str) -> str:
    return "episode-" + "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in slug)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

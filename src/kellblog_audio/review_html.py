"""Generate the public Kellblog audio listening page."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from kellblog_audio.catalog import Catalog, PostRow
from kellblog_audio.config import OUTPUT_DIR, PUBLIC_BASE_URL, QA_TRANSCRIPTS_DIR
from kellblog_audio.qa import qa_report_passed

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
    """Internal QA soft-threshold helpers (not shown on the public listening page)."""
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
    require_qa: bool = False,
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for post in catalog.list_by_filter(audio_status="done"):
        if not post.audio_path:
            continue
        if require_qa and not qa_report_passed(post.slug, output_dir=qa_dir):
            continue
        qa = _read_qa(qa_dir / f"{post.slug}.qa.json")
        items.append(ReviewItem(post=post, qa=qa, concerns=concern_reasons(qa)))
    return items


def write_review_page(
    catalog: Catalog,
    *,
    out_path: Path = OUTPUT_DIR / "index.html",
    qa_dir: Path = QA_TRANSCRIPTS_DIR,
    require_qa: bool = False,
    updated_at: str | None = None,
) -> Path:
    items = collect_review_items(catalog, qa_dir=qa_dir, require_qa=require_qa)
    updated = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _render_page(items=items, updated_at=updated),
        encoding="utf-8",
    )
    _remove_stale_feedback_redirect(out_path.parent)
    return out_path


def _render_page(*, items: list[ReviewItem], updated_at: str) -> str:
    episode_word = "episode" if len(items) == 1 else "episodes"
    page_url = _public_page_url()
    cards = "\n".join(_render_article(item, page_url=page_url) for item in items)
    mailto_href = _mailto_page_href(page_url)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kellblog Audio</title>
  <style>{_css()}</style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>Kellblog Audio</h1>
      <p class="lede">AI-narrated archive of Dave Kellogg’s Kellblog posts. Browse and listen below.</p>
      <div class="share-actions" aria-label="Share this page">
        <button type="button" class="share-button" data-copy-page-url="{html.escape(page_url)}">Copy page link</button>
        <a class="share-link" href="{html.escape(mailto_href)}">Email page link</a>
        <span class="updated">Updated {html.escape(updated_at)}</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <div class="toolbar">
      <span>{len(items)} {episode_word}</span>
    </div>
    <section class="episodes" aria-label="Episodes">
{cards}
    </section>
  </main>
  <script>{_share_script()}</script>
</body>
</html>
"""


def _render_article(item: ReviewItem, *, page_url: str) -> str:
    post = item.post
    title = html.escape(post.title or post.slug)
    meta_bits = [_format_date(post.published_at), _format_duration(post.duration_sec)]
    if post.word_count:
        meta_bits.append(f"{post.word_count:,} words")
    audio_url = _public_audio_path(post.audio_path)
    anchor = _anchor(post.slug)
    return f"""      <article id="{anchor}">
        <div class="episode-head">
          <div>
            <h2>{title}</h2>
            <div class="meta">{html.escape(" · ".join(bit for bit in meta_bits if bit))}</div>
          </div>
          <div class="links">
            <a href="{html.escape(post.url)}">Original</a>
            <a href="{html.escape(audio_url)}">MP3</a>
            <button type="button" data-copy-page-url="{html.escape(page_url)}#{anchor}" data-share-label="{title}">Copy link</button>
          </div>
        </div>
        <audio controls preload="metadata" src="{html.escape(audio_url)}"></audio>
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
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 1rem;
    }
    .share-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .share-link, .share-button, .links button {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      background: var(--surface);
      color: var(--accent);
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .share-link:hover, .share-button:hover, .links button:hover {
      background: var(--accent-soft);
      border-color: #9fcdd2;
      text-decoration: none;
    }
    .updated {
      color: var(--muted);
      font-size: 0.875rem;
    }
    main { padding: 24px 0 40px; }
    a {
      color: var(--accent);
      font-weight: 600;
      text-decoration: none;
    }
    a:hover { text-decoration: underline; }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 18px;
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
    .links a, .links button {
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
      margin: 8px 0 0;
    }
    @media (max-width: 760px) {
      .episode-head { grid-template-columns: 1fr; }
      .links, .share-actions { justify-content: flex-start; }
    }
    @media (max-width: 460px) {
      .wrap { width: min(100% - 20px, 1120px); }
      header .wrap { padding-top: 22px; }
      h1 { font-size: 1.55rem; }
      article { padding: 14px; }
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


def _anchor(slug: str) -> str:
    return "episode-" + "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in slug)


def _public_page_url() -> str:
    return f"{PUBLIC_BASE_URL.rstrip('/')}/index.html"


def _mailto_page_href(page_url: str) -> str:
    subject = quote("Kellblog Audio")
    body = quote(f"Listen to the Kellblog audio archive here:\n\n{page_url}")
    return f"mailto:?subject={subject}&body={body}"


def _share_script() -> str:
    return """
    (function () {
      function pageUrl(target) {
        return new URL(target, window.location.href).href;
      }
      function fallbackCopy(text) {
        var input = document.createElement("textarea");
        input.value = text;
        input.setAttribute("readonly", "");
        input.style.position = "fixed";
        input.style.left = "-9999px";
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        document.body.removeChild(input);
      }
      function flash(button) {
        var original = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(function () { button.textContent = original; }, 1400);
      }
      document.querySelectorAll("[data-copy-page-url]").forEach(function (button) {
        button.addEventListener("click", function () {
          var url = pageUrl(button.getAttribute("data-copy-page-url"));
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function () { flash(button); });
          } else {
            fallbackCopy(url);
            flash(button);
          }
        });
      });
    }());
    """


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

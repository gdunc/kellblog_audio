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
from kellblog_audio.config import FEED_URL, OUTPUT_DIR, PUBLIC_BASE_URL, QA_TRANSCRIPTS_DIR
from kellblog_audio.listen_platforms import RSS_ICON, ListenPlatform, listen_platforms
from kellblog_audio.qa import read_qa_report, report_accepted
from kellblog_audio.text_clean import excerpt_from_body, html_to_plain

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


def _feed_eligible(slug: str, qa_dir: Path) -> bool:
    """Same rule as the feed: a missing QA report is fine, a failing one is not."""
    report = read_qa_report(slug, output_dir=qa_dir)
    return report is None or report_accepted(report)


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
        if require_qa and not _feed_eligible(post.slug, qa_dir):
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
    sections, years = _render_year_sections(items, page_url=page_url)
    year_links = "\n".join(
        f'        <a href="#year-{year}">{year}</a>' for year, _count in years
    )
    mailto_href = _mailto_page_href(page_url)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kellblog Audio</title>
  <link rel="alternate" type="application/rss+xml" title="Kellblog Audio" href="{html.escape(FEED_URL)}">
  <style>{_css()}</style>
</head>
<body>
  <header>
    <div class="wrap">
      <div class="title-row">
        <h1>Kellblog Audio</h1>
        <div class="share-actions" aria-label="Share this page">
          <button type="button" class="share-quiet" data-copy-page-url="{html.escape(page_url)}">{_svg(_LINK_ICON, stroke=True)}<span class="label">Copy link</span></button>
          <a class="share-quiet" href="{html.escape(mailto_href)}">{_svg(_MAIL_ICON, stroke=True)}<span class="label">Email</span></a>
        </div>
      </div>
      <p class="lede">AI-narrated audio editions of Dave Kellogg’s <a href="https://www.kellblog.com">Kellblog</a>. Produced by <a href="https://thisisgrant.com">Grant Duncan</a>.</p>
{_render_subscribe()}
      <p class="updated">Updated {html.escape(updated_at)}</p>
    </div>
  </header>
  <main class="wrap">
    <div class="toolbar">
      <span id="episode-count" data-total="{len(items)}">{len(items)} {episode_word}</span>
      <input id="episode-search" type="search" placeholder="Search titles and summaries" aria-label="Search episodes">
    </div>
    <nav class="years" aria-label="Jump to year">
{year_links}
    </nav>
    <p id="no-results" class="no-results" hidden>No episodes match that search.</p>
{sections}
  </main>
  <script>{_share_script()}</script>
</body>
</html>
"""


def _release_key(post: PostRow) -> str:
    return post.released_at or post.published_at or ""


def _render_year_sections(
    items: list[ReviewItem], *, page_url: str
) -> tuple[str, list[tuple[int, int]]]:
    """Newest episodes first, grouped by year (the same year the feed uses as its season)."""
    by_year: dict[int, list[ReviewItem]] = {}
    for item in items:
        by_year.setdefault(item.post.year or 0, []).append(item)

    sections: list[str] = []
    years: list[tuple[int, int]] = []
    for year in sorted(by_year, reverse=True):
        group = sorted(by_year[year], key=lambda it: _release_key(it.post), reverse=True)
        years.append((year, len(group)))
        cards = "\n".join(_render_article(item, page_url=page_url) for item in group)
        label = str(year) if year else "Undated"
        count = len(group)
        sections.append(
            f'''    <section class="year" id="year-{year}" aria-labelledby="year-{year}-title">
      <h2 class="year-title" id="year-{year}-title">{label} <span>{count} {"episode" if count == 1 else "episodes"}</span></h2>
      <div class="episodes">
{cards}
      </div>
    </section>'''
        )
    return "\n".join(sections), years


def _summary(post: PostRow, max_chars: int = 240) -> str:
    raw = post.rss_excerpt or ""
    text = html_to_plain(raw) if "<" in raw else raw
    if not text.strip():
        text = excerpt_from_body(post.text or "", max_chars=max_chars)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def _render_article(item: ReviewItem, *, page_url: str) -> str:
    post = item.post
    title = html.escape(post.title or post.slug)
    meta_bits = [_format_date(_release_key(post)), _format_duration(post.duration_sec)]
    audio_url = _public_audio_path(post.audio_path)
    anchor = _anchor(post.slug)
    summary = _summary(post)
    summary_html = f'\n        <p class="excerpt">{html.escape(summary)}</p>' if summary else ""
    return f"""      <article id="{anchor}">
        <div class="episode-head">
          <div>
            <h3>{title}</h3>
            <div class="meta">{html.escape(" · ".join(bit for bit in meta_bits if bit))}</div>
          </div>
          <div class="links">
            <a href="{html.escape(post.url)}">Read original</a>
            <button type="button" data-copy-page-url="{html.escape(page_url)}#{anchor}" data-share-label="{title}">Copy link</button>
          </div>
        </div>{summary_html}
        <audio controls preload="none" src="{html.escape(audio_url)}"></audio>
      </article>"""


_LINK_ICON = '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
_MAIL_ICON = '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>'


def _svg(inner: str, *, stroke: bool = False) -> str:
    """Inline 24x24 icon, hidden from screen readers (the button text labels it)."""
    paint = (
        ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
        if stroke
        else ""
    )
    return f'<svg class="icon" viewBox="0 0 24 24" width="18" height="18"{paint} aria-hidden="true" focusable="false">{inner}</svg>'


def _render_platform(p: ListenPlatform) -> str:
    icon = _svg(p.icon_svg)
    name = html.escape(p.name)
    if p.url:
        return (
            f'          <a class="listen-btn" href="{html.escape(p.url)}" '
            f'target="_blank" rel="noopener" data-platform="{p.key}">{icon}<span>{name}</span></a>'
        )
    return (
        f'          <span class="listen-btn is-pending" aria-disabled="true" '
        f'title="{name} listing coming soon" data-platform="{p.key}">{icon}<span>{name}</span>'
        f'<span class="soon">Soon</span></span>'
    )


def _render_subscribe(platforms: list[ListenPlatform] | None = None) -> str:
    buttons = "\n".join(_render_platform(p) for p in (platforms or listen_platforms()))
    rss_icon = _svg(f'<path fill="#EE802F" d="{RSS_ICON}"/>')
    return f'''      <section class="subscribe" aria-labelledby="subscribe-title">
        <h2 id="subscribe-title">Subscribe free in your podcast app</h2>
        <div class="listen-buttons">
{buttons}
          <button type="button" class="listen-btn" data-copy-page-url="{html.escape(FEED_URL)}">{rss_icon}<span class="label">Copy RSS feed</span></button>
        </div>
        <p class="subscribe-hint">Using another app? Copy the RSS feed and paste it into the app’s “Add podcast by URL” option.</p>
      </section>'''


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
    .title-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 16px;
      align-items: flex-start;
      justify-content: space-between;
    }
    .share-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      align-items: center;
    }
    .share-quiet {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 0;
      border-radius: 6px;
      padding: 6px 8px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: 0.875rem;
      font-weight: 500;
      cursor: pointer;
    }
    .share-quiet:hover { background: var(--bg); color: var(--ink); text-decoration: none; }
    .share-quiet .icon { width: 16px; height: 16px; }
    .subscribe {
      margin: 4px 0 14px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--bg);
    }
    .subscribe h2 { margin: 0 0 12px; font-size: 1rem; }
    .listen-buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .listen-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 44px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 14px;
      background: var(--surface);
      color: var(--ink);
      font: inherit;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .listen-btn .icon { width: 22px; height: 22px; flex: none; }
    a.listen-btn:hover, button.listen-btn:hover {
      border-color: #9fcdd2;
      background: var(--accent-soft);
      text-decoration: none;
    }
    .listen-btn.is-pending { cursor: default; color: var(--muted); }
    .listen-btn.is-pending .icon { opacity: 0.55; }
    .listen-btn .soon {
      border-radius: 999px;
      padding: 1px 7px;
      background: var(--bg);
      color: var(--muted);
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .subscribe-hint {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 0.85rem;
    }
    .links button {
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
    .links button:hover {
      background: var(--accent-soft);
      border-color: #9fcdd2;
      text-decoration: none;
    }
    .updated {
      margin: 0;
      color: var(--muted);
      font-size: 0.8rem;
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
    h3 { margin: 0; font-size: 1.15rem; line-height: 1.25; letter-spacing: 0; }
    .excerpt {
      margin: 0 0 4px;
      color: var(--ink);
      font-size: 0.95rem;
    }
    .year { margin: 0 0 28px; scroll-margin-top: 12px; }
    .year-title {
      margin: 0 0 12px;
      font-size: 1.5rem;
      line-height: 1.2;
    }
    .year-title span {
      color: var(--muted);
      font-size: 0.9rem;
      font-weight: 400;
      margin-left: 6px;
    }
    .years {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 0 0 22px;
    }
    .years a {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      padding: 4px 9px;
      font-size: 0.875rem;
    }
    .years a:hover { background: var(--accent-soft); border-color: #9fcdd2; text-decoration: none; }
    #episode-search {
      flex: 1 1 260px;
      max-width: 380px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      background: var(--surface);
      color: var(--ink);
    }
    .no-results { color: var(--muted); }
    @media (max-width: 760px) {
      .episode-head { grid-template-columns: 1fr; }
      .links { justify-content: flex-start; }
    }
    @media (max-width: 460px) {
      .wrap { width: min(100% - 20px, 1120px); }
      header .wrap { padding-top: 22px; }
      h1 { font-size: 1.55rem; }
      #episode-search { max-width: none; }
      article { padding: 14px; }
      .listen-btn { padding: 8px 10px; font-size: 0.875rem; }
      .subscribe { padding: 14px 12px; }
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
    return f"{PUBLIC_BASE_URL.rstrip('/')}/"


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
        var target = button.querySelector(".label") || button;
        var original = target.textContent;
        target.textContent = "Copied";
        window.setTimeout(function () { target.textContent = original; }, 1400);
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
      var search = document.getElementById("episode-search");
      var count = document.getElementById("episode-count");
      var none = document.getElementById("no-results");
      if (search) {
        var cards = Array.prototype.slice.call(document.querySelectorAll("section.year article"));
        cards.forEach(function (card) {
          var h = card.querySelector("h3"), e = card.querySelector(".excerpt");
          card.searchText = ((h ? h.textContent : "") + " " + (e ? e.textContent : "")).toLowerCase();
        });
        var sections = Array.prototype.slice.call(document.querySelectorAll("section.year"));
        var yearLinks = document.querySelector("nav.years");
        search.addEventListener("input", function () {
          var q = search.value.trim().toLowerCase();
          var shown = 0;
          cards.forEach(function (card) {
            var match = !q || card.searchText.indexOf(q) !== -1;
            card.hidden = !match;
            if (match) { shown += 1; }
          });
          sections.forEach(function (sec) {
            sec.hidden = !sec.querySelector("article:not([hidden])");
          });
          if (yearLinks) { yearLinks.hidden = !!q; }
          var total = parseInt(count.getAttribute("data-total"), 10);
          count.textContent = q ? shown + " of " + total + " episodes" : total + (total === 1 ? " episode" : " episodes");
          none.hidden = shown !== 0;
        });
      }
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

"""Slack alerts and audio sanity checks.

Alerts go to a Slack incoming webhook (``SLACK_WEBHOOK_URL_KELLBLOG``, falling back to
``SLACK_WEBHOOK_URL``). Delivery is best-effort: with no webhook configured, or if Slack
is down, nothing is raised, so an alert can never break the pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from kellblog_audio.catalog import Catalog, PostRow

WEBHOOK_ENV_VARS = ("SLACK_WEBHOOK_URL_KELLBLOG", "SLACK_WEBHOOK_URL")
SLACK_TIMEOUT_SECONDS = 5

# Narration pace across the archive is ~146-224 words/min for posts of 300+ words. Short
# posts are skipped: the spoken intro/outro dominates their duration.
MIN_WORDS_FOR_PACE_CHECK = 300
MIN_WORDS_PER_MINUTE = 130
MAX_WORDS_PER_MINUTE = 260

# A re-ingest that loses more than this share of a long post's text looks like a paywall
# or markup change, not a normal edit.
SHRINK_MIN_PRIOR_WORDS = 150
SHRINK_RATIO = 0.5

# Subscribe-wall text that must never appear in narrated copy. This is a second line of
# defence for when the site's paywall markup changes and extract.py stops noticing it.
PAYWALL_PHRASES = (
    "subscribers only",
    "subscribe now",
    "already have an account",
)


@dataclass(frozen=True)
class Finding:
    slug: str
    problem: str

    def line(self) -> str:
        return f"• `{self.slug}`: {self.problem}"


def webhook_url() -> str:
    for name in WEBHOOK_ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def send_slack(message: str) -> bool:
    """Post `message` to Slack. Returns True only if Slack accepted it."""
    url = webhook_url()
    if not url:
        return False
    try:
        resp = httpx.post(url, json={"text": message}, timeout=SLACK_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200


def shrank_sharply(prior_words: int | None, new_words: int) -> bool:
    if not prior_words or prior_words < SHRINK_MIN_PRIOR_WORDS:
        return False
    return new_words < prior_words * SHRINK_RATIO


def audio_findings(catalog: Catalog) -> list[Finding]:
    """Episodes that are on (or about to go on) the feed but look wrong."""
    findings: list[Finding] = []
    for post in catalog.list_by_filter():
        if post.audio_status != "done":
            continue
        findings.extend(_episode_findings(post))
    return findings


def _episode_findings(post: PostRow) -> list[Finding]:
    found: list[Finding] = []
    if post.paywalled:
        found.append(Finding(post.slug, "marked paywalled but has finished audio on the feed"))
    text = (post.text or "").lower()
    hit = next((p for p in PAYWALL_PHRASES if p in text), None)
    if hit:
        found.append(Finding(post.slug, f'narrated text contains subscribe-wall copy ("{hit}")'))
    words, seconds = post.word_count or 0, post.duration_sec or 0
    if words >= MIN_WORDS_FOR_PACE_CHECK and seconds > 0:
        pace = words * 60 / seconds
        if not MIN_WORDS_PER_MINUTE <= pace <= MAX_WORDS_PER_MINUTE:
            found.append(
                Finding(
                    post.slug,
                    f"{words} words but only {seconds}s of audio ({pace:.0f} words/min); "
                    "audio may be truncated",
                )
            )
    return found


def format_findings(findings: list[Finding]) -> str:
    head = f":warning: Kellblog Audio: {len(findings)} episode(s) need a look"
    return "\n".join([head, *(f.line() for f in findings[:20])])

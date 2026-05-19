"""SQLite catalog for posts and pipeline state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    slug TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    year INTEGER,
    rss_excerpt TEXT,
    categories TEXT,
    body_raw TEXT,
    text TEXT,
    word_count INTEGER,
    content_hash TEXT,
    sitemap_lastmod TEXT,
    etag TEXT,
    last_modified TEXT,
    ingest_status TEXT DEFAULT 'pending',
    ingest_error TEXT,
    audio_path TEXT,
    audio_status TEXT DEFAULT 'pending',
    audio_error TEXT,
    duration_sec INTEGER,
    episode_in_season INTEGER,
    feed_published_at TEXT,
    skip_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_audio_status ON posts(audio_status);
CREATE INDEX IF NOT EXISTS idx_posts_ingest_status ON posts(ingest_status);
CREATE INDEX IF NOT EXISTS idx_posts_year ON posts(year);
"""


@dataclass
class PostRow:
    slug: str
    url: str
    title: str | None = None
    published_at: str | None = None
    year: int | None = None
    rss_excerpt: str | None = None
    categories: str | None = None
    body_raw: str | None = None
    text: str | None = None
    word_count: int | None = None
    content_hash: str | None = None
    sitemap_lastmod: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    ingest_status: str = "pending"
    ingest_error: str | None = None
    audio_path: str | None = None
    audio_status: str = "pending"
    audio_error: str | None = None
    duration_sec: int | None = None
    episode_in_season: int | None = None
    feed_published_at: str | None = None
    skip_reason: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PostRow:
        return cls(**{k: row[k] for k in row.keys()})


class Catalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_sitemap_entry(
        self, slug: str, url: str, sitemap_lastmod: str | None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO posts (slug, url, sitemap_lastmod, ingest_status)
                VALUES (?, ?, ?, 'pending')
                ON CONFLICT(slug) DO UPDATE SET
                    url = excluded.url,
                    sitemap_lastmod = excluded.sitemap_lastmod
                """,
                (slug, url, sitemap_lastmod),
            )

    def update_post(self, slug: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [slug]
        with self.connect() as conn:
            conn.execute(f"UPDATE posts SET {cols} WHERE slug = ?", vals)

    def get(self, slug: str) -> PostRow | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
        return PostRow.from_row(row) if row else None

    def list_by_filter(
        self,
        *,
        ingest_status: str | None = None,
        audio_status: str | None = None,
        year: int | None = None,
        slug: str | None = None,
    ) -> list[PostRow]:
        clauses: list[str] = []
        params: list[Any] = []
        if ingest_status:
            clauses.append("ingest_status = ?")
            params.append(ingest_status)
        if audio_status:
            clauses.append("audio_status = ?")
            params.append(audio_status)
        if year is not None:
            clauses.append("year = ?")
            params.append(year)
        if slug:
            clauses.append("slug = ?")
            params.append(slug)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM posts {where} ORDER BY published_at ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [PostRow.from_row(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            ingest_pending = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE ingest_status = 'pending'"
            ).fetchone()[0]
            audio_pending = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE audio_status IN ('pending', 'stale')"
            ).fetchone()[0]
            audio_done = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE audio_status = 'done'"
            ).fetchone()[0]
            audio_skip = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE audio_status = 'skip'"
            ).fetchone()[0]
            publish_pending = conn.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE audio_status = 'done' AND feed_published_at IS NULL
                """
            ).fetchone()[0]
        return {
            "total": total,
            "ingest_pending": ingest_pending,
            "audio_pending": audio_pending,
            "audio_done": audio_done,
            "audio_skip": audio_skip,
            "publish_pending": publish_pending,
        }

    def assign_episode_numbers(self) -> None:
        """Assign episode_in_season per year (oldest = 1)."""
        with self.connect() as conn:
            years = conn.execute(
                "SELECT DISTINCT year FROM posts WHERE year IS NOT NULL ORDER BY year"
            ).fetchall()
            for (year,) in years:
                rows = conn.execute(
                    """
                    SELECT slug FROM posts
                    WHERE year = ? AND published_at IS NOT NULL
                    ORDER BY published_at ASC
                    """,
                    (year,),
                ).fetchall()
                for idx, (slug,) in enumerate(rows, start=1):
                    conn.execute(
                        "UPDATE posts SET episode_in_season = ? WHERE slug = ?",
                        (idx, slug),
                    )

    def mark_feed_published(self, slug: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_post(slug, feed_published_at=now)

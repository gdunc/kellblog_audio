import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from kellblog_audio.catalog import Catalog
from kellblog_audio import cli
from kellblog_audio import qa as qa_mod
from kellblog_audio.podcast import build_feed
from kellblog_audio import publish as publish_mod
from kellblog_audio.review_html import write_review_page


def _catalog_with_posts(db: Path) -> Catalog:
    catalog = Catalog(db)
    catalog.init_schema()
    for slug in ("passed-post", "missing-qa-post", "failed-qa-post"):
        catalog.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
        catalog.update_post(
            slug,
            title=slug.replace("-", " ").title(),
            published_at="2024-06-01T12:00:00.000Z",
            year=2024,
            url=f"https://www.kellblog.com/{slug}/",
            text="Body text for TTS.",
            word_count=4,
            ingest_status="done",
            audio_status="done",
            duration_sec=120,
            audio_path=f"output/audio/2024/{slug}.mp3",
        )
    return catalog


def test_public_feed_omits_failed_qa_but_includes_missing_reports(tmp_path):
    catalog = _catalog_with_posts(tmp_path / "catalog.sqlite")
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    (qa_dir / "passed-post.qa.json").write_text(
        json.dumps({"passed": True}), encoding="utf-8"
    )
    (qa_dir / "failed-qa-post.qa.json").write_text(
        json.dumps({"passed": False, "reason": "coverage"}), encoding="utf-8"
    )

    root = ET.fromstring(
        build_feed(catalog, local_audio=False, require_qa=True, qa_dir=qa_dir)
    )

    assert set(item.findtext("title") for item in root.findall("./channel/item")) == {
        "Passed Post",
        "Missing Qa Post",
    }


def test_public_review_page_matches_feed_qa_rule(tmp_path):
    catalog = _catalog_with_posts(tmp_path / "catalog.sqlite")
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    (qa_dir / "passed-post.qa.json").write_text(
        json.dumps({"passed": True}), encoding="utf-8"
    )
    (qa_dir / "failed-qa-post.qa.json").write_text(
        json.dumps({"passed": False}), encoding="utf-8"
    )

    out = tmp_path / "index.html"
    write_review_page(catalog, out_path=out, qa_dir=qa_dir, require_qa=True)

    html = out.read_text(encoding="utf-8")
    assert "Passed Post" in html
    assert "Missing Qa Post" in html  # no report: unchecked, but listed like the feed does
    assert "Failed Qa Post" not in html


def test_r2_publish_omits_failed_qa_and_succeeds_when_some_episodes_pass(
    tmp_path, monkeypatch
):
    catalog = _catalog_with_posts(tmp_path / "catalog.sqlite")
    uploaded: list[str] = []
    marked: list[str] = []

    class FakeClient:
        def copy_object(self, **_kwargs):
            return None

        def delete_object(self, **_kwargs):
            return None

    monkeypatch.setattr(publish_mod, "get_s3_client", FakeClient)
    monkeypatch.setattr(
        publish_mod,
        "upload_file",
        lambda _client, local, key, _ctype: uploaded.append(key) or "etag",
    )
    monkeypatch.setattr(
        publish_mod,
        "write_review_page",
        lambda catalog, require_qa=False: tmp_path / "index.html",
    )
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(
        publish_mod,
        "write_feed",
        lambda catalog, path, **_kwargs: path.write_text("<rss/>", encoding="utf-8") or path,
    )
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    (qa_dir / "passed-post.qa.json").write_text(
        json.dumps({"passed": True}), encoding="utf-8"
    )
    (qa_dir / "failed-qa-post.qa.json").write_text(
        json.dumps({"passed": False}), encoding="utf-8"
    )
    monkeypatch.setattr(publish_mod, "QA_TRANSCRIPTS_DIR", qa_dir)
    monkeypatch.setattr(qa_mod, "QA_TRANSCRIPTS_DIR", qa_dir)
    monkeypatch.setattr(
        catalog,
        "mark_feed_published",
        lambda slug: marked.append(slug),
    )

    url = publish_mod.publish_to_r2(catalog, upload_audio=False)

    assert url.endswith("/feed.xml")
    assert "feed.xml.tmp" in uploaded
    assert set(marked) == {"passed-post", "missing-qa-post"}


def test_site_only_publish_skips_feed_and_qa_gate(tmp_path, monkeypatch):
    catalog = _catalog_with_posts(tmp_path / "catalog.sqlite")
    uploaded: list[str] = []
    deleted: list[str] = []

    class FakeClient:
        def delete_object(self, *, Bucket, Key):
            deleted.append(Key)

        def copy_object(self, **_kwargs):
            raise AssertionError("site-only publish must not update feed.xml")

    monkeypatch.setattr(publish_mod, "get_s3_client", FakeClient)
    monkeypatch.setattr(
        publish_mod,
        "upload_file",
        lambda _client, local, key, _ctype: uploaded.append(key) or "etag",
    )
    monkeypatch.setattr(
        publish_mod,
        "write_review_page",
        lambda catalog, require_qa=False: tmp_path / "index.html",
    )
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(
        publish_mod,
        "qa_report_passed",
        lambda slug: False,
    )
    monkeypatch.setattr(
        catalog,
        "mark_feed_published",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("site-only must not mark feed published")
        ),
    )

    url = publish_mod.publish_site_to_r2(catalog, upload_audio=False)

    assert url.endswith("/index.html")
    assert "index.html" in uploaded
    assert "feed.xml" not in uploaded
    assert "feed.xml.tmp" not in uploaded
    assert "feedback/index.html" in deleted


def test_r2_publish_still_fails_when_archive_has_almost_no_passing_qa(
    tmp_path, monkeypatch
):
    catalog = _catalog_with_posts(tmp_path / "catalog.sqlite")
    for i in range(50):
        slug = f"extra-{i}"
        catalog.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
        catalog.update_post(
            slug,
            title=slug,
            published_at="2024-06-01T12:00:00.000Z",
            year=2024,
            url=f"https://www.kellblog.com/{slug}/",
            text="Body",
            word_count=1,
            ingest_status="done",
            audio_status="done",
            duration_sec=60,
            audio_path=f"output/audio/2024/{slug}.mp3",
        )

    monkeypatch.setattr(publish_mod, "get_s3_client", lambda: object())
    monkeypatch.setattr(
        publish_mod,
        "qa_report_passed",
        lambda slug: slug == "passed-post",
    )

    with pytest.raises(RuntimeError, match="QA restore looks empty"):
        publish_mod.publish_to_r2(catalog, upload_audio=False)


def test_cli_does_not_downgrade_a_qa_gate_failure_to_local_publish(monkeypatch):
    monkeypatch.setattr(cli, "_catalog", lambda: object())
    monkeypatch.setattr(
        cli,
        "publish_to_r2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("QA restore looks empty: 1/53 done episode(s) have passing QA")
        ),
    )
    monkeypatch.setattr(
        cli,
        "publish_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("QA failure must not fall back to local publish")
        ),
    )

    with pytest.raises(RuntimeError, match="QA restore looks empty"):
        cli.publish(local_only=False, skip_audio=False, site_only=False)

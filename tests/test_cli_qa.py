from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from kellblog_audio import cli
from kellblog_audio.catalog import PostRow


runner = CliRunner()


def _passing_result():
    return SimpleNamespace(
        passed=True,
        reason="ok",
        source_coverage=1.0,
        tail_similarity=1.0,
        max_repeated_three_gram=0,
    )


def test_qa_audio_missing_only_selects_done_posts_without_artifacts(tmp_path, monkeypatch):
    posts = [
        PostRow(slug="done-1", url="https://example.com/1", audio_status="done"),
        PostRow(slug="done-2", url="https://example.com/2", audio_status="done"),
        PostRow(slug="done-3", url="https://example.com/3", audio_status="done"),
    ]
    (tmp_path / "done-1.qa.json").write_text("{}", encoding="utf-8")
    calls: list[str] = []

    fake_catalog = SimpleNamespace(
        get=lambda _slug: None,
        list_by_filter=lambda **_kwargs: posts,
    )
    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(cli, "QA_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )
    monkeypatch.setattr(
        cli,
        "qa_post_audio",
        lambda _catalog, slug: calls.append(slug) or _passing_result(),
    )

    result = runner.invoke(cli.app, ["qa-audio", "--missing-only", "--limit", "1"])

    assert result.exit_code == 0
    assert calls == ["done-2"]
    assert "selected=1" in result.output
    assert "passed=1" in result.output


def test_qa_audio_rejects_slug_with_missing_only():
    result = runner.invoke(cli.app, ["qa-audio", "--slug", "done-1", "--missing-only"])

    assert result.exit_code != 0
    assert "--slug and --missing-only cannot be combined" in result.output


def test_qa_audio_rejects_negative_limit(monkeypatch):
    posts = [
        PostRow(slug="done-1", url="https://example.com/1", audio_status="done"),
        PostRow(slug="done-2", url="https://example.com/2", audio_status="done"),
    ]
    fake_catalog = SimpleNamespace(
        get=lambda _slug: None,
        list_by_filter=lambda **_kwargs: posts,
    )

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )
    monkeypatch.setattr(
        cli,
        "qa_post_audio",
        lambda _catalog, _slug: _passing_result(),
    )

    result = runner.invoke(cli.app, ["qa-audio", "--limit", "-1"])

    assert result.exit_code != 0
    assert "--limit must be >= 0" in result.output


def test_qa_audio_continues_after_episode_error_and_only_queues_real_failures(
    tmp_path, monkeypatch
):
    posts = [
        PostRow(slug="error-post", url="https://example.com/error", audio_status="done"),
        PostRow(slug="fail-post", url="https://example.com/fail", audio_status="done"),
    ]
    queued: list[tuple[str, str]] = []

    fake_catalog = SimpleNamespace(
        get=lambda _slug: None,
        list_by_filter=lambda **_kwargs: posts,
    )
    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(cli, "QA_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )

    def fake_qa(_catalog, slug):
        if slug == "error-post":
            raise RuntimeError("missing local mp3")
        return SimpleNamespace(
            passed=False,
            reason="coverage 10.0% < 85%",
            source_coverage=0.10,
            tail_similarity=0.92,
            max_repeated_three_gram=0,
        )

    monkeypatch.setattr(cli, "qa_post_audio", fake_qa)
    monkeypatch.setattr(
        cli,
        "queue_audio_rerun",
        lambda _catalog, slug, reason: queued.append((slug, reason)),
    )

    result = runner.invoke(cli.app, ["qa-audio", "--missing-only", "--rerun-failed"])

    assert result.exit_code == 0
    assert queued == [("fail-post", "coverage 10.0% < 85%")]
    assert "errored=1" in result.output
    assert "failed=1" in result.output
    assert "queued-for-rerun=1" in result.output


def test_qa_audio_rerun_failed_skips_when_auto_rerun_false(tmp_path, monkeypatch):
    posts = [
        PostRow(slug="short-fail", url="https://example.com/1", audio_status="done"),
    ]
    queued: list[tuple[str, str]] = []
    fake_catalog = SimpleNamespace(
        get=lambda slug: posts[0] if slug == "short-fail" else None,
        list_by_filter=lambda **_kwargs: posts,
    )
    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(cli, "QA_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )
    monkeypatch.setattr(
        cli,
        "qa_post_audio",
        lambda _catalog, _slug: SimpleNamespace(
            passed=False,
            reason="coverage 72.0% < 85%",
            source_coverage=0.72,
            tail_similarity=0.72,
            max_repeated_three_gram=1,
            auto_rerun=False,
        ),
    )
    monkeypatch.setattr(
        cli,
        "queue_audio_rerun",
        lambda _catalog, slug, reason: queued.append((slug, reason)),
    )

    result = runner.invoke(cli.app, ["qa-audio", "--slug", "short-fail", "--rerun-failed"])

    assert result.exit_code == 0
    assert queued == []
    assert "queued-for-rerun=0" in result.output
    assert "failed=1" in result.output

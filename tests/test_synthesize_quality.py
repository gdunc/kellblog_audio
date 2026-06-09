import pytest

from kellblog_audio import synthesize as synth
from kellblog_audio.catalog import PostRow


def test_validate_audio_duration_rejects_implausibly_short_render():
    post = PostRow(
        slug="bad-render",
        url="https://example.com/bad-render",
        word_count=1200,
    )

    with pytest.raises(RuntimeError, match="Implausibly short audio"):
        synth.validate_audio_duration(post, duration_sec=240)


def test_validate_audio_duration_allows_reasonable_render():
    post = PostRow(
        slug="good-render",
        url="https://example.com/good-render",
        word_count=1200,
    )

    synth.validate_audio_duration(post, duration_sec=480)


def test_synthesize_batch_stops_on_first_qa_failure(monkeypatch):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First"),
        PostRow(slug="second", url="https://example.com/second", text="Second"),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.errors: list[tuple[str, str]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.errors.append((slug, fields["audio_status"]))

    class FakeQAResult:
        passed = False
        reason = "coverage 10% < 70%"

    synthesized: list[str] = []
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(
        synth,
        "synthesize_post",
        lambda _catalog, slug, *_args, **_kwargs: synthesized.append(slug),
    )
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())

    ok, err = synth.synthesize_batch(FakeCatalog(), qa_first=1)

    assert (ok, err) == (0, 1)
    assert synthesized == ["first"]


def test_synthesize_batch_marks_qa_failure_for_rerun(monkeypatch):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First"),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.updated: list[tuple[str, dict]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.updated.append((slug, fields))

    class FakeQAResult:
        passed = False
        reason = "tail similarity 40% < 70%"

    catalog = FakeCatalog()
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(synth, "synthesize_post", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())

    synth.synthesize_batch(catalog, qa_first=1)

    assert catalog.updated == [
        (
            "first",
            {
                "audio_status": "stale",
                "audio_error": "Audio QA failed; queued for rerun: tail similarity 40% < 70%",
                "feed_published_at": None,
            },
        )
    ]

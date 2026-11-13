from kellblog_audio import alerts
from kellblog_audio import publish as publish_mod
from kellblog_audio.catalog import Catalog


def _post(cat: Catalog, slug: str, **fields) -> None:
    cat.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
    base = dict(
        year=2026,
        ingest_status="done",
        audio_status="done",
        text="word " * 600,
        word_count=600,
        duration_sec=190,
        paywalled=0,
    )
    base.update(fields)
    cat.update_post(slug, **base)


def _cat(tmp_path) -> Catalog:
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    return cat


def test_healthy_episode_has_no_findings(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "fine")
    assert alerts.audio_findings(cat) == []


def test_truncated_audio_is_flagged(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "cut-off", duration_sec=40)  # 600 words in 40s
    [f] = alerts.audio_findings(cat)
    assert f.slug == "cut-off" and "truncated" in f.problem


def test_short_posts_skip_pace_check(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "video-post", word_count=20, duration_sec=21, text="a video post")
    assert alerts.audio_findings(cat) == []


def test_subscribe_wall_text_is_flagged(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "leaky", text="Preview. This post is for paying subscribers only. Subscribe now")
    problems = [f.problem for f in alerts.audio_findings(cat)]
    assert any("subscribe-wall" in p for p in problems)


def test_paywalled_post_with_finished_audio_is_flagged(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "inconsistent", paywalled=1)
    assert any("paywalled" in f.problem for f in alerts.audio_findings(cat))


def test_only_done_episodes_are_checked(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "pending-one", audio_status="pending", duration_sec=1)
    assert alerts.audio_findings(cat) == []


def test_shrank_sharply():
    assert alerts.shrank_sharply(1000, 300)
    assert not alerts.shrank_sharply(1000, 800)
    assert not alerts.shrank_sharply(100, 10)  # too short to judge
    assert not alerts.shrank_sharply(None, 10)


def test_send_slack_without_webhook_is_a_noop(monkeypatch):
    for name in alerts.WEBHOOK_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert alerts.send_slack("hi") is False


def test_send_slack_posts_text(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL_KELLBLOG", "https://hooks.example/x")
    sent = {}

    class Resp:
        status_code = 200

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json)
        return Resp()

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    assert alerts.send_slack("hello") is True
    assert sent == {"url": "https://hooks.example/x", "json": {"text": "hello"}}


def test_send_slack_swallows_network_errors(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL_KELLBLOG", "https://hooks.example/x")

    def boom(*a, **k):
        raise alerts.httpx.ConnectError("down")

    monkeypatch.setattr(alerts.httpx, "post", boom)
    assert alerts.send_slack("hello") is False


def test_paywalled_mp3s_are_deleted_from_r2(tmp_path):
    cat = _cat(tmp_path)
    _post(cat, "now-paid", audio_status="paywalled", year=2025)
    _post(cat, "still-free")

    class Client:
        deleted = []

        def delete_object(self, Bucket, Key):
            self.deleted.append(Key)

    client = Client()
    removed = publish_mod._remove_paywalled_audio(cat, client)
    assert removed == ["now-paid"]
    assert client.deleted == ["audio/2025/now-paid.mp3"]

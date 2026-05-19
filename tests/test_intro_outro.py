from kellblog_audio.intro_outro import (
    ATTRIBUTION_PLAIN,
    SPOKEN_OUTRO,
    build_episode_description_html,
    spoken_intro,
)


def test_spoken_intro():
    s = spoken_intro("Hello World", "2024-11-05T12:00:00.000Z")
    assert "November 5, 2024" in s
    assert "Hello World" in s
    assert "Kellblog post" in s


def test_attribution_in_description():
    html = build_episode_description_html("Excerpt.", "https://www.kellblog.com/foo/")
    assert "thisisgrant.com" in html
    assert "Grant Duncan" in html
    assert "permission from Dave" in html


def test_spoken_outro():
    assert "Grant Duncan" in SPOKEN_OUTRO
    assert "thisisgrant.com" not in SPOKEN_OUTRO
    assert "thisisgrant.com" in ATTRIBUTION_PLAIN

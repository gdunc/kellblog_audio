from kellblog_audio.footnotes import prepare_for_tts, split_body_and_notes


def test_split_notes():
    text = "Body paragraph.\n\n## Notes\n\n[1] Note one."
    body, notes = split_body_and_notes(text)
    assert "Body" in body
    assert notes is not None
    assert "Note one" in notes


def test_inline_footnotes_preserved():
    text = "See reference [1] here.\n\n## Notes\n\n[1] Detail."
    result = prepare_for_tts(text, inline_footnotes=True)
    assert "[1]" in result

from kellblog_audio.tts import chunk_text


def test_chunk_splits_long_paragraph():
    para = "a" * 2000
    chunks = chunk_text(para, max_chars=500)
    assert len(chunks) >= 4
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_keeps_short_paragraphs_together():
    text = "First para.\n\nSecond para."
    chunks = chunk_text(text, max_chars=500)
    assert len(chunks) == 1

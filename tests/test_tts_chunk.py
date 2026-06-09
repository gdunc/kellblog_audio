from pathlib import Path

from kellblog_audio import tts
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


class RecordingProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.chunks: list[str] = []

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        self.chunks.append(text)
        out_wav.write_text(text, encoding="utf-8")


def test_synthesize_uses_smaller_chunks_for_chatterbox(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "MAX_CHUNK_CHARS", 1000)
    monkeypatch.setattr(tts, "CHATTERBOX_MAX_CHUNK_CHARS", 50)
    monkeypatch.setattr(
        tts,
        "concat_wavs",
        lambda _parts, out_wav: out_wav.write_text("combined", encoding="utf-8"),
    )
    provider = RecordingProvider("chatterbox")

    tts.synthesize_text_to_wav(provider, "a" * 120, tmp_path / "out.wav")

    assert [len(chunk) for chunk in provider.chunks] == [50, 50, 20]


def test_synthesize_keeps_default_chunks_for_other_providers(tmp_path):
    provider = RecordingProvider("fake")

    tts.synthesize_text_to_wav(provider, "a" * 120, tmp_path / "out.wav")

    assert len(provider.chunks) == 1

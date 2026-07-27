from pathlib import Path

import pytest

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
    monkeypatch.setattr(tts, "CHUNK_LOOP_RETRY_ENABLED", False)
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


def test_kokoro_is_not_a_supported_provider():
    with pytest.raises(ValueError, match="Unknown TTS provider: kokoro"):
        tts._make_provider("kokoro")


class FlakyLoopProvider:
    """Fails loop check on first synthesize, clean on retry."""

    name = "chatterbox"

    def __init__(self) -> None:
        self.attempts = 0
        self.exaggeration = 0.4
        self.cfg_weight = 0.5
        self.seen_params: list[tuple[float, float]] = []

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        self.attempts += 1
        self.seen_params.append((float(self.exaggeration), float(self.cfg_weight)))
        out_wav.write_bytes(b"RIFF" + bytes([self.attempts]) + b"fake-wav")


def test_synthesize_retries_looping_chunk_with_calmer_params(tmp_path, monkeypatch):
    from kellblog_audio import qa as qa_mod

    monkeypatch.setattr(tts, "CHUNK_LOOP_RETRY_ENABLED", True)
    monkeypatch.setattr(tts, "CHUNK_LOOP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(tts, "CHATTERBOX_MAX_CHUNK_CHARS", 50)
    monkeypatch.setattr(
        tts,
        "concat_wavs",
        lambda _parts, out_wav: out_wav.write_bytes(b"combined"),
    )

    transcripts = iter(
        [
            "the rule of " * 20,  # attempt 1: loop
            "clean normal prose about metrics and growth",  # attempt 2: ok
        ]
    )

    def fake_transcribe(audio_path: Path, **_kwargs) -> Path:
        out = audio_path.with_suffix(".txt")
        out.write_text(next(transcripts), encoding="utf-8")
        return out

    monkeypatch.setattr(qa_mod, "transcribe_audio", fake_transcribe)
    provider = FlakyLoopProvider()

    tts.synthesize_text_to_wav(provider, "a" * 40, tmp_path / "out.wav")

    assert provider.attempts == 2
    assert provider.seen_params[0] == (0.4, 0.5)
    assert provider.seen_params[1][0] < provider.seen_params[0][0]

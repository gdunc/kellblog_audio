from pathlib import Path

from kellblog_audio import synthesize as synth


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        self.calls += 1
        out_wav.write_text(f"call={self.calls}\n{text}", encoding="utf-8")


def test_outro_cache_reuses_identical_outro_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(synth, "OUTRO_CACHE_DIR", tmp_path / "cache")
    provider = FakeProvider()
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"

    synth.synthesize_outro_to_wav(provider, first)
    synth.synthesize_outro_to_wav(provider, second)

    assert provider.calls == 1
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")

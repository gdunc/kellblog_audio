"""TTS provider interface and implementations."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from kellblog_audio.config import (
    CHATTERBOX_EXAGGERATION,
    KOKORO_VOICE,
    MAX_CHUNK_CHARS,
    PIPER_VOICE,
    PIPER_VOICES_DIR,
    TTS_PROVIDER,
)


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        ...

    def is_available(self) -> bool:
        try:
            self._check_deps()
            return True
        except ImportError:
            return False

    def _check_deps(self) -> None:
        pass


class KokoroProvider(TTSProvider):
    name = "kokoro"

    def __init__(self, voice: str = KOKORO_VOICE) -> None:
        self.voice = voice
        self._pipeline = None

    def _check_deps(self) -> None:
        import kokoro  # noqa: F401

    def _get_pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code="a")
        return self._pipeline

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        import numpy as np
        import soundfile as sf

        pipeline = self._get_pipeline()
        chunks_audio: list = []
        sample_rate = 24000
        for _gs, _ps, audio in pipeline(text, voice=self.voice):
            chunks_audio.append(audio)
        if not chunks_audio:
            raise RuntimeError("Kokoro produced no audio")
        combined = np.concatenate(chunks_audio)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_wav), combined, sample_rate)


class ChatterboxProvider(TTSProvider):
    name = "chatterbox"

    def __init__(self, exaggeration: float = CHATTERBOX_EXAGGERATION) -> None:
        self.exaggeration = exaggeration
        self._model = None

    def _check_deps(self) -> None:
        import chatterbox  # noqa: F401

    def _get_model(self):
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS

            self._model = ChatterboxTTS.from_pretrained(device="cpu")
        return self._model

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        import torchaudio

        model = self._get_model()
        wav = model.generate(text, exaggeration=self.exaggeration)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(out_wav), wav.cpu(), model.sr)


class PiperProvider(TTSProvider):
    name = "piper"

    def __init__(self, voice: str = PIPER_VOICE) -> None:
        self.voice = voice
        self._piper_voice = None

    def _check_deps(self) -> None:
        import piper  # noqa: F401

    def _get_voice(self):
        if self._piper_voice is None:
            from piper import PiperVoice
            from piper.download_voices import download_voice

            PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)
            onnx_path = PIPER_VOICES_DIR / f"{self.voice}.onnx"
            json_path = PIPER_VOICES_DIR / f"{self.voice}.onnx.json"
            if not onnx_path.exists():
                download_voice(self.voice, PIPER_VOICES_DIR)
            self._piper_voice = PiperVoice.load(onnx_path, json_path)
        return self._piper_voice

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        import numpy as np
        import soundfile as sf

        voice = self._get_voice()
        chunks = list(voice.synthesize(text))
        if not chunks:
            raise RuntimeError("Piper produced no audio")
        audio = np.concatenate([c.audio_float_array for c in chunks])
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_wav), audio, chunks[0].sample_rate)


class StyleTTS2Provider(TTSProvider):
    name = "styletts2"

    def _check_deps(self) -> None:
        raise ImportError(
            "StyleTTS2 is optional and heavy; install manually per README. "
            "Use kokoro or chatterbox for bake-off."
        )

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        raise NotImplementedError("StyleTTS2 provider not bundled; use kokoro or chatterbox")


def _make_provider(provider_name: str) -> TTSProvider:
    factories: dict[str, type[TTSProvider]] = {
        "kokoro": KokoroProvider,
        "chatterbox": ChatterboxProvider,
        "piper": PiperProvider,
        "styletts2": StyleTTS2Provider,
    }
    if provider_name not in factories:
        raise ValueError(f"Unknown TTS provider: {provider_name}")
    return factories[provider_name]()


def get_provider(name: str | None = None) -> TTSProvider:
    provider_name = (name or TTS_PROVIDER).lower()
    p = _make_provider(provider_name)
    if not p.is_available():
        raise ImportError(
            f"TTS provider '{provider_name}' is not installed. "
            f"Run: uv sync --extra {provider_name}"
        )
    return p


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(para), max_chars):
                chunks.append(para[i : i + max_chars].strip())
            continue
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = para
    if current:
        chunks.append(current.strip())
    return chunks or [text[:max_chars]]


def synthesize_text_to_wav(
    provider: TTSProvider,
    text: str,
    out_wav: Path,
) -> None:
    chunks = chunk_text(text)
    if len(chunks) == 1:
        provider.synthesize_chunk(chunks[0], out_wav)
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        part_files: list[Path] = []
        for i, chunk in enumerate(chunks):
            part = tmp_path / f"part_{i:04d}.wav"
            provider.synthesize_chunk(chunk, part)
            part_files.append(part)
        concat_wavs(part_files, out_wav)


def concat_wavs(wav_files: list[Path], out_wav: Path) -> None:
    if len(wav_files) == 1:
        shutil.copy(wav_files[0], out_wav)
        return
    list_file = out_wav.parent / "concat_list.txt"
    with list_file.open("w") as f:
        for p in wav_files:
            f.write(f"file '{p.resolve()}'\n")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out_wav),
        ],
        check=True,
        capture_output=True,
    )
    list_file.unlink(missing_ok=True)


def wav_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    *,
    title: str,
    artist: str = "Dave Kellogg",
    album: str = "Kellblog Audio",
    track: int | None = None,
) -> int:
    """Convert WAV to 128k mono MP3 with ID3; return duration seconds."""
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    meta: list[str] = []
    if title:
        meta.extend(["-metadata", f"title={title}"])
    if artist:
        meta.extend(["-metadata", f"artist={artist}"])
    if album:
        meta.extend(["-metadata", f"album={album}"])
    if track is not None:
        meta.extend(["-metadata", f"track={track}"])

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            "44100",
            "-b:a",
            "128k",
            *meta,
            str(mp3_path),
        ],
        check=True,
        capture_output=True,
    )
    return probe_duration(mp3_path)


def probe_duration(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(float(result.stdout.strip()))


def merge_audio_parts(parts: list[Path], out_mp3: Path, **id3) -> int:
    """Concatenate WAV/MP3 parts and encode to final MP3."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        wav_parts: list[Path] = []
        for i, p in enumerate(parts):
            if p.suffix.lower() == ".mp3":
                wav = tmp_path / f"p{i}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(p), str(wav)],
                    check=True,
                    capture_output=True,
                )
                wav_parts.append(wav)
            else:
                wav_parts.append(p)
        combined = tmp_path / "combined.wav"
        concat_wavs(wav_parts, combined)
        return wav_to_mp3(combined, out_mp3, **id3)


def list_available_providers() -> Iterator[str]:
    for name in ("kokoro", "chatterbox", "piper", "styletts2"):
        try:
            p = _make_provider(name)
            if p.is_available():
                yield name
        except Exception:
            pass

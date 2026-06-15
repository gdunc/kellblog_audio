"""TTS provider interface and implementations."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from kellblog_audio.config import (
    CHATTERBOX_MAX_CHUNK_CHARS,
    CHATTERBOX_DEVICE,
    CHATTERBOX_EXAGGERATION,
    KOKORO_VOICE,
    MAX_CHUNK_CHARS,
    PIPER_VOICE,
    PIPER_VOICES_DIR,
    ROOT,
    TTS_PROVIDER,
)


def _resolve_torch_device(preference: str = "auto") -> str:
    """Resolve a torch device string. 'auto' prefers CUDA, then Apple MPS, else CPU."""
    import torch

    pref = (preference or "auto").lower()
    if pref == "cpu":
        return "cpu"
    if pref == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if pref == "mps":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    # auto
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


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

    def __init__(
        self,
        exaggeration: float = CHATTERBOX_EXAGGERATION,
        device: str = CHATTERBOX_DEVICE,
    ) -> None:
        self.exaggeration = exaggeration
        self.device_preference = device
        self._device: str | None = None
        self._model = None

    def _check_deps(self) -> None:
        import chatterbox  # noqa: F401

    def _get_model(self):
        if self._model is None:
            self._device = _resolve_torch_device(self.device_preference)
            if self._device == "mps":
                # Some Chatterbox ops aren't implemented on MPS; fall back to CPU per-op.
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            from chatterbox.tts import ChatterboxTTS

            self._model = ChatterboxTTS.from_pretrained(device=self._device)
        return self._model

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        import gc

        import torch
        import torchaudio

        model = self._get_model()
        # Flush stale allocations from the previous chunk BEFORE generating.
        # Flushing before (not after) means the model's JIT/shader cache and
        # warm allocation patterns are preserved for the current chunk, while
        # the previous chunk's now-unused KV-cache pages are returned to Metal
        # before the new KV cache starts growing. This prevents the Metal heap
        # from accumulating across chunks (which causes the catastrophic
        # >10 s/token slowdown that starts at token ~150 when heaps overflow).
        gc.collect()
        if self._device == "mps" and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif self._device == "cuda":
            torch.cuda.empty_cache()

        # inference_mode disables autograd tracking, reducing per-step memory overhead.
        with torch.inference_mode():
            wav = model.generate(text, exaggeration=self.exaggeration)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(out_wav), wav.cpu(), model.sr)
        del wav


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
    """StyleTTS2 via isolated subprocess (transformers version conflicts with Chatterbox)."""

    name = "styletts2"

    def __init__(self, reference_voice_url: str | None = None) -> None:
        self.reference_voice_url = reference_voice_url

    def _check_deps(self) -> None:
        if not shutil.which("uv"):
            raise ImportError("uv is required to run StyleTTS2 in an isolated environment")

    def is_available(self) -> bool:
        return shutil.which("uv") is not None

    def synthesize_full_text(self, text: str, out_wav: Path) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(text)
            text_file = tmp.name
        try:
            cmd = [
                "uv",
                "run",
                "--with",
                "styletts2",
                "python",
                "-m",
                "kellblog_audio.styletts2_worker",
                "--text-file",
                text_file,
                "--out",
                str(out_wav),
            ]
            if self.reference_voice_url:
                cmd.extend(["--ref-url", self.reference_voice_url])
            subprocess.run(cmd, check=True, cwd=str(ROOT), capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"StyleTTS2 synthesis failed: {detail}") from exc
        finally:
            os.unlink(text_file)

    def synthesize_chunk(self, text: str, out_wav: Path) -> None:
        self.synthesize_full_text(text, out_wav)


def _make_provider(provider_name: str, **kwargs) -> TTSProvider:
    provider_name = provider_name.lower()
    if provider_name == "kokoro":
        return KokoroProvider(voice=kwargs.get("voice", KOKORO_VOICE))
    if provider_name == "chatterbox":
        ex = kwargs.get("exaggeration", CHATTERBOX_EXAGGERATION)
        device = kwargs.get("device", CHATTERBOX_DEVICE)
        return ChatterboxProvider(exaggeration=float(ex), device=device)
    if provider_name == "piper":
        return PiperProvider(voice=kwargs.get("voice", PIPER_VOICE))
    if provider_name == "styletts2":
        return StyleTTS2Provider(reference_voice_url=kwargs.get("reference_voice_url"))
    raise ValueError(f"Unknown TTS provider: {provider_name}")


def get_provider(name: str | None = None, **kwargs) -> TTSProvider:
    provider_name = (name or TTS_PROVIDER).lower()
    p = _make_provider(provider_name, **kwargs)
    if not p.is_available():
        extra = provider_name if provider_name != "styletts2" else "compare + uv"
        raise ImportError(
            f"TTS provider '{provider_name}' is not installed. "
            f"Run: uv sync --extra {extra}"
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


def max_chunk_chars_for_provider(provider: TTSProvider) -> int:
    if provider.name == "chatterbox":
        return CHATTERBOX_MAX_CHUNK_CHARS
    return MAX_CHUNK_CHARS


def synthesize_text_to_wav(
    provider: TTSProvider,
    text: str,
    out_wav: Path,
) -> None:
    synthesize_full = getattr(provider, "synthesize_full_text", None)
    if provider.name == "styletts2" and synthesize_full is not None:
        synthesize_full(text, out_wav)
        return
    chunks = chunk_text(text, max_chars=max_chunk_chars_for_provider(provider))
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
            continue

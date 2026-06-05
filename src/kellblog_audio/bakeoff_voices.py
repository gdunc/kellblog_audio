"""Voice variants and demo links for the TTS bake-off."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BakeoffVariant:
    provider: str
    voice_id: str
    label: str
    description: str = ""
    reference_url: str | None = None
    exaggeration: float | None = None


# Curated variants: multiple voices per engine for side-by-side comparison.
BAKEOFF_VARIANTS: tuple[BakeoffVariant, ...] = (
    # Kokoro — American English males (podcast-friendly)
    BakeoffVariant("kokoro", "am_michael", "Michael", "Default production voice (C+)"),
    BakeoffVariant("kokoro", "am_fenrir", "Fenrir", "Male, grade C+"),
    BakeoffVariant("kokoro", "am_puck", "Puck", "Male, grade C+"),
    # Chatterbox — single built-in voice; exaggeration changes delivery
    BakeoffVariant(
        "chatterbox",
        "builtin-0.4",
        "Built-in (calm)",
        "Default built-in voice, exaggeration 0.4",
        exaggeration=0.4,
    ),
    BakeoffVariant(
        "chatterbox",
        "builtin-0.7",
        "Built-in (expressive)",
        "Same voice, exaggeration 0.7",
        exaggeration=0.7,
    ),
    # Piper — alternatives to lessac
    BakeoffVariant("piper", "en_US-ryan-medium", "Ryan", "US male, medium quality"),
    BakeoffVariant("piper", "en_US-john-medium", "John", "US male, medium quality"),
    BakeoffVariant("piper", "en_US-hfc_male-medium", "HFC Male", "US male, medium quality"),
    # StyleTTS 2 — clones from reference WAV (LibriVox public-domain readers)
    BakeoffVariant(
        "styletts2",
        "ljspeech-00001",
        "LibriVox ref #1",
        "Default StyleTTS2 reference (female)",
        reference_url="https://styletts2.github.io/wavs/LJSpeech/OOD/GT/00001.wav",
    ),
    BakeoffVariant(
        "styletts2",
        "ljspeech-00003",
        "LibriVox ref #3",
        "Alternate LibriVox reader",
        reference_url="https://styletts2.github.io/wavs/LJSpeech/OOD/GT/00003.wav",
    ),
)

# Only quick sample + target pipeline coverage for this bake-off run.
BAKEOFF_SLUGS: tuple[str, ...] = (
    "target-pipeline-coverage-is-not-the-inverse-of-win-rate",
)

PROVIDER_DEMO_URLS: dict[str, str] = {
    "kokoro": "https://huggingface.co/spaces/hexgrad/Kokoro-TTS",
    "chatterbox": "https://huggingface.co/ResembleAI/chatterbox",
    "piper": "https://rhasspy.github.io/piper-samples/",
    "styletts2": "https://styletts2.github.io/",
}

PROVIDER_META: dict[str, dict[str, str]] = {
    "kokoro": {
        "label": "Kokoro 82M",
        "license": "Apache 2.0",
        "cloning": "No (54 preset voices)",
        "notes": "Try voices at the Hugging Face demo; American English uses lang_code a.",
    },
    "chatterbox": {
        "label": "Chatterbox",
        "license": "MIT",
        "cloning": "Yes (5s reference WAV)",
        "notes": "One built-in voice in the pip package; cloning needs a reference clip.",
    },
    "piper": {
        "label": "Piper",
        "license": "MIT",
        "cloning": "No (100+ preset ONNX voices)",
        "notes": "Browse all voices on the Rhasspy samples page.",
    },
    "styletts2": {
        "label": "StyleTTS 2",
        "license": "MIT",
        "cloning": "Yes (reference WAV)",
        "notes": "Runs in an isolated uv env (conflicts with Chatterbox deps). Demo page has LibriTTS/VCTK samples.",
    },
}


def bakeoff_filename(slug: str, variant: BakeoffVariant) -> str:
    """Stable MP3 basename: sample__kokoro__am_michael or slug__piper__en_US-ryan-medium."""
    prefix = "sample" if slug == "__sample__" else slug
    return f"{prefix}__{variant.provider}__{variant.voice_id}.mp3"


def parse_bakeoff_filename(stem: str) -> tuple[str, str, str] | None:
    """Parse basename into (slug, provider, voice_id). slug __sample__ for quick sample."""
    if stem.startswith("sample__"):
        rest = stem[len("sample__") :]
        slug = "__sample__"
    elif "__" in stem:
        slug, rest = stem.split("__", 1)
    else:
        return None
    if "__" not in rest:
        return None
    provider, voice_id = rest.split("__", 1)
    return slug, provider, voice_id

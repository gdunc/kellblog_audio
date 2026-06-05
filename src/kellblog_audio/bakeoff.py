"""TTS bake-off: generate samples from multiple free providers and voices."""

from __future__ import annotations

from pathlib import Path

from kellblog_audio.bakeoff_html import write_bakeoff_page
from kellblog_audio.bakeoff_voices import (
    BAKEOFF_SLUGS,
    BAKEOFF_VARIANTS,
    BakeoffVariant,
    bakeoff_filename,
)
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import BAKEOFF_DIR, get_settings
from kellblog_audio.intro_outro import SPOKEN_OUTRO, spoken_intro
from kellblog_audio.tts import get_provider, synthesize_text_to_wav, wav_to_mp3

SAMPLE_SLUG = "__sample__"

SAMPLE_TEXT = (
    "This is a Kellblog post from May 18, 2026, titled "
    "A Diamond in the Rough. SaaS metrics like ARR and MRR matter to every CMO."
)


def provider_for_variant(variant: BakeoffVariant):
    kwargs: dict = {}
    if variant.provider == "kokoro":
        kwargs["voice"] = variant.voice_id
    elif variant.provider == "piper":
        kwargs["voice"] = variant.voice_id
    elif variant.provider == "chatterbox" and variant.exaggeration is not None:
        kwargs["exaggeration"] = variant.exaggeration
    elif variant.provider == "styletts2" and variant.reference_url:
        kwargs["reference_voice_url"] = variant.reference_url
    return get_provider(variant.provider, **kwargs)


def run_bakeoff(
    catalog: Catalog,
    slugs: list[str] | None = None,
    variants: tuple[BakeoffVariant, ...] | None = None,
) -> list[Path]:
    settings = get_settings()
    settings.ensure_dirs()
    slugs = slugs or list(BAKEOFF_SLUGS)
    variants = variants or BAKEOFF_VARIANTS
    outputs: list[Path] = []

    by_provider: dict[str, list[str]] = {}
    for v in variants:
        by_provider.setdefault(v.provider, []).append(v.voice_id)
    summary = ", ".join(f"{p} ({len(vs)} voices)" for p, vs in by_provider.items())
    print(f"Bake-off: {summary}")
    print(f"Posts: quick sample + {', '.join(slugs)}")

    for variant in variants:
        try:
            provider = provider_for_variant(variant)
        except ImportError as exc:
            print(f"Skipping {variant.provider}/{variant.voice_id}: {exc}")
            continue

        out = BAKEOFF_DIR / bakeoff_filename(SAMPLE_SLUG, variant)
        wav = out.with_suffix(".wav")
        synthesize_text_to_wav(provider, SAMPLE_TEXT + " " + SPOKEN_OUTRO, wav)
        wav_to_mp3(wav, out, title=f"Bakeoff {variant.provider} {variant.label}")
        wav.unlink(missing_ok=True)
        outputs.append(out)
        print(f"Wrote {out}")

    for slug in slugs:
        post = catalog.get(slug)
        if not post or not post.text:
            print(f"Skip {slug}: not ingested")
            continue
        intro = spoken_intro(
            post.title or slug,
            post.published_at or "1970-01-01T00:00:00Z",
        )
        full = intro + "\n\n" + (post.text[:2000] if post.text else "") + "\n\n" + SPOKEN_OUTRO

        for variant in variants:
            try:
                provider = provider_for_variant(variant)
            except ImportError:
                continue
            out = BAKEOFF_DIR / bakeoff_filename(slug, variant)
            wav = out.with_suffix(".wav")
            synthesize_text_to_wav(provider, full, wav)
            wav_to_mp3(wav, out, title=post.title or slug)
            wav.unlink(missing_ok=True)
            outputs.append(out)
            print(f"Wrote {out}")

    decision_path = BAKEOFF_DIR / "DECISION.md"
    decision_path.write_text(
        """# TTS Bake-off Decision

Listen via `index.html` (serve with `kellblog-audio bakeoff-serve`).

| Provider | License | Voice options |
|----------|---------|---------------|
| kokoro | Apache 2.0 | 54 presets — demo: https://huggingface.co/spaces/hexgrad/Kokoro-TTS |
| chatterbox | MIT | Built-in + cloning — https://huggingface.co/ResembleAI/chatterbox |
| piper | MIT | 100+ presets — https://rhasspy.github.io/piper-samples/ |
| styletts2 | MIT | Reference WAV cloning — https://styletts2.github.io/ |

Set `KELLBLOG_TTS_PROVIDER` and voice env vars after choosing.

- [ ] kokoro
- [ ] chatterbox
- [ ] piper
- [ ] styletts2
""",
        encoding="utf-8",
    )
    page = write_bakeoff_page(catalog, BAKEOFF_DIR)
    print(f"Listening page: {page}")
    print("Serve with: uv run kellblog-audio bakeoff-serve")
    return outputs

"""TTS bake-off: generate samples from multiple free providers."""

from __future__ import annotations

from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import BAKEOFF_DIR, get_settings
from kellblog_audio.intro_outro import SPOKEN_OUTRO, spoken_intro
from kellblog_audio.synthesize import synthesize_post
from kellblog_audio.tts import get_provider, list_available_providers, synthesize_text_to_wav, wav_to_mp3

# Representative posts for bake-off (short, medium, long with footnotes)
DEFAULT_BAKEOFF_SLUGS = [
    "taxonomies-and-tags",  # ~665 words
    "target-pipeline-coverage-is-not-the-inverse-of-win-rate",  # ~2100
    "a-diamond-in-the-rough-startup-founder-survival-guide-by-david-politis",  # long + footnotes
]

# All installed providers are used unless overridden
BAKEOFF_PROVIDERS = ("kokoro", "chatterbox", "piper")


def default_bakeoff_providers() -> tuple[str, ...]:
    return tuple(list_available_providers())


def run_bakeoff(
    catalog: Catalog,
    slugs: list[str] | None = None,
    providers: tuple[str, ...] | None = None,
) -> list[Path]:
    settings = get_settings()
    settings.ensure_dirs()
    slugs = slugs or DEFAULT_BAKEOFF_SLUGS
    if providers is None:
        providers = default_bakeoff_providers() or BAKEOFF_PROVIDERS
    outputs: list[Path] = []
    print(f"Bake-off providers: {', '.join(providers)}")

    sample_text = (
        "This is a Kellblog post from May 18, 2026, titled "
        "A Diamond in the Rough. SaaS metrics like ARR and MRR matter to every CMO."
    )

    for provider_name in providers:
        if provider_name not in list(list_available_providers()):
            print(f"Skipping {provider_name} (not installed)")
            continue
        provider = get_provider(provider_name)
        out = BAKEOFF_DIR / f"sample_{provider_name}.mp3"
        wav = BAKEOFF_DIR / f"sample_{provider_name}.wav"
        synthesize_text_to_wav(provider, sample_text + " " + SPOKEN_OUTRO, wav)
        wav_to_mp3(wav, out, title=f"Bakeoff {provider_name}")
        wav.unlink(missing_ok=True)
        outputs.append(out)
        print(f"Wrote {out}")

    for slug in slugs:
        post = catalog.get(slug)
        if not post or not post.text:
            print(f"Skip {slug}: not ingested")
            continue
        for provider_name in providers:
            if provider_name not in list(list_available_providers()):
                continue
            provider = get_provider(provider_name)
            out = BAKEOFF_DIR / f"{slug}_{provider_name}.mp3"
            wav = BAKEOFF_DIR / f"{slug}_{provider_name}.wav"
            intro = spoken_intro(
                post.title or slug,
                post.published_at or "1970-01-01T00:00:00Z",
            )
            full = intro + "\n\n" + (post.text[:2000] if post.text else "") + "\n\n" + SPOKEN_OUTRO
            synthesize_text_to_wav(provider, full, wav)
            wav_to_mp3(wav, out, title=post.title or slug)
            wav.unlink(missing_ok=True)
            outputs.append(out)
            print(f"Wrote {out}")

    decision_path = BAKEOFF_DIR / "DECISION.md"
    decision_path.write_text(
        """# TTS Bake-off Decision

Listen to samples in this directory. Default production provider: **kokoro** (`am_michael`).

| Provider | License | Voice cloning |
|----------|---------|---------------|
| kokoro | Apache 2.0 | No |
| chatterbox | MIT | Yes (5s sample) |
| piper | MIT | No |
| styletts2 | MIT | Finetune only (manual install) |

Set `KELLBLOG_TTS_PROVIDER=kokoro|chatterbox|piper` after choosing.

Record your choice below:

- [ ] kokoro
- [ ] chatterbox
- [ ] piper
""",
        encoding="utf-8",
    )
    return outputs

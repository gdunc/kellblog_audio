"""Run StyleTTS2 in an isolated uv env (avoids transformers conflict with Chatterbox)."""

from __future__ import annotations

import argparse
from pathlib import Path


def _patch_torch_load() -> None:
    import torch

    if getattr(torch.load, "_kellblog_styletts2_patch", False):
        return
    original = torch.load

    def patched_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original(*args, **kwargs)

    patched_load._kellblog_styletts2_patch = True  # type: ignore[attr-defined]
    torch.load = patched_load  # type: ignore[assignment]


def synthesize(text: str, out_wav: Path, ref_url: str | None = None) -> None:
    _patch_torch_load()
    from cached_path import cached_path
    from styletts2 import tts
    from styletts2.tts import DEFAULT_TARGET_VOICE_URL

    model = tts.StyleTTS2()
    ref = ref_url or DEFAULT_TARGET_VOICE_URL
    target = str(cached_path(ref))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    model.inference(text, target_voice_path=target, output_wav_file=str(out_wav))


def main() -> None:
    parser = argparse.ArgumentParser(description="StyleTTS2 synthesis worker")
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ref-url", default=None)
    args = parser.parse_args()
    text = args.text_file.read_text(encoding="utf-8")
    synthesize(text, args.out, ref_url=args.ref_url)


if __name__ == "__main__":
    main()

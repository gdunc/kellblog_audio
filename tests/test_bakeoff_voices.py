"""Tests for bake-off filename parsing."""

from kellblog_audio.bakeoff_voices import bakeoff_filename, parse_bakeoff_filename, BakeoffVariant


def test_bakeoff_filename_roundtrip():
    variant = BakeoffVariant("chatterbox", "builtin-0.4", "Built-in")
    name = bakeoff_filename("__sample__", variant)
    assert name == "sample__chatterbox__builtin-0.4.mp3"
    parsed = parse_bakeoff_filename("sample__chatterbox__builtin-0.4")
    assert parsed == ("__sample__", "chatterbox", "builtin-0.4")

    slug = "target-pipeline-coverage-is-not-the-inverse-of-win-rate"
    name2 = bakeoff_filename(slug, BakeoffVariant("piper", "en_US-ryan-medium", "Ryan"))
    assert name2.startswith(slug)
    parsed2 = parse_bakeoff_filename(name2.removesuffix(".mp3"))
    assert parsed2 == (slug, "piper", "en_US-ryan-medium")


def test_parse_legacy_single_underscore_returns_none():
    assert parse_bakeoff_filename("sample_chatterbox") is None

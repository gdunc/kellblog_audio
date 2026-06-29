"""Configuration from environment and defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo root (kellblog_audio/)
ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
FEEDS_DIR = OUTPUT_DIR / "feeds"
BAKEOFF_DIR = OUTPUT_DIR / "bakeoff"
QA_TRANSCRIPTS_DIR = OUTPUT_DIR / "transcribe" / "qa"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CATALOG_PATH = DATA_DIR / "catalog.sqlite"

SITEMAP_URL = "https://www.kellblog.com/sitemap-posts.xml"
RSS_URL = "https://www.kellblog.com/rss/"
BLOG_BASE = "https://www.kellblog.com"

# Default public URLs (override via env)
PUBLIC_BASE_URL = os.environ.get(
    "KELLBLOG_AUDIO_PUBLIC_URL", "https://kellblog.thisisgrant.com"
)
FEED_URL = f"{PUBLIC_BASE_URL}/feed.xml"

# TTS: kokoro | chatterbox | styletts2
TTS_PROVIDER = os.environ.get("KELLBLOG_TTS_PROVIDER", "kokoro")
KOKORO_VOICE = os.environ.get("KELLBLOG_KOKORO_VOICE", "am_michael")
CHATTERBOX_EXAGGERATION = float(os.environ.get("KELLBLOG_CHATTERBOX_EXAGGERATION", "0.4"))
# Torch device for Chatterbox: auto | mps | cpu | cuda (auto prefers MPS/CUDA when available)
CHATTERBOX_DEVICE = os.environ.get("KELLBLOG_CHATTERBOX_DEVICE", "auto")
# CFG weight for Chatterbox (Chatterbox default is 0.5; 0.0 crashes T3 — do not use)
CHATTERBOX_CFG_WEIGHT = float(os.environ.get("KELLBLOG_CHATTERBOX_CFG_WEIGHT", "0.5"))
PIPER_VOICE = os.environ.get("KELLBLOG_PIPER_VOICE", "en_US-lessac-medium")
PIPER_VOICES_DIR = DATA_DIR / "piper_voices"

# Posts that link to external audio only — skip TTS, include in feed with note
DEFAULT_SKIP_SLUGS: frozenset[str] = frozenset(
    {
        "audio-from-my-exit-five-cmo-leadership-retreat-presentation",
    }
)

SKIP_SLUGS = DEFAULT_SKIP_SLUGS | frozenset(
    s.strip()
    for s in os.environ.get("KELLBLOG_SKIP_SLUGS", "").split(",")
    if s.strip()
)

# R2 / S3-compatible
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "kellblog-audio")
R2_ENDPOINT = os.environ.get(
    "R2_ENDPOINT",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "",
)

SHOW_TITLE = "Kellblog Audio"
SHOW_SUBTITLE = "Dave Kellogg on Enterprise Software Startups (AI-narrated)"
SHOW_AUTHOR = "Dave Kellogg"
SHOW_LANGUAGE = "en-us"
SHOW_CATEGORY = "Business"
SHOW_CATEGORY_SUB = "Management"
SHOW_EMAIL = os.environ.get("KELLBLOG_PODCAST_EMAIL", "grant@thisisgrant.com")

MAX_CHUNK_CHARS = int(os.environ.get("KELLBLOG_MAX_CHUNK_CHARS", "1500"))
CHATTERBOX_MAX_CHUNK_CHARS = int(
    os.environ.get("KELLBLOG_CHATTERBOX_MAX_CHUNK_CHARS", "600")
)
MAX_AUDIO_BODY_WPM = float(os.environ.get("KELLBLOG_MAX_AUDIO_BODY_WPM", "230"))
WHISPER_CLI = os.environ.get("KELLBLOG_WHISPER_CLI", "whisper-cli")
WHISPER_MODEL = os.environ.get(
    "KELLBLOG_WHISPER_MODEL",
    str(Path.home() / "Library/Application Support/pywhispercpp/models/ggml-small.en-q8_0.bin"),
)
INGEST_RATE_LIMIT = 3.0  # requests per second max


@dataclass
class Settings:
    root: Path = field(default_factory=lambda: ROOT)
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)
    catalog_path: Path = field(default_factory=lambda: CATALOG_PATH)
    tts_provider: str = field(default_factory=lambda: TTS_PROVIDER)
    public_base_url: str = field(default_factory=lambda: PUBLIC_BASE_URL)
    skip_slugs: frozenset[str] = field(default_factory=lambda: SKIP_SLUGS)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        FEEDS_DIR.mkdir(parents=True, exist_ok=True)
        BAKEOFF_DIR.mkdir(parents=True, exist_ok=True)
        QA_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def r2_configured(self) -> bool:
        return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET)


def get_settings() -> Settings:
    return Settings()

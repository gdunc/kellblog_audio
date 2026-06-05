"""Generate an HTML listening page for TTS bake-off comparisons."""

from __future__ import annotations

import json
from pathlib import Path

from kellblog_audio.bakeoff_voices import (
    BAKEOFF_VARIANTS,
    PROVIDER_DEMO_URLS,
    PROVIDER_META,
    parse_bakeoff_filename,
)
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import BAKEOFF_DIR, BLOG_BASE


def discover_bakeoff_files(bakeoff_dir: Path) -> dict[str, dict[str, dict[str, Path]]]:
    """slug -> provider -> voice_id -> mp3 path"""
    by_post: dict[str, dict[str, dict[str, Path]]] = {}
    for mp3 in sorted(bakeoff_dir.glob("*.mp3")):
        parsed = parse_bakeoff_filename(mp3.stem)
        if not parsed:
            continue
        slug, provider, voice_id = parsed
        by_post.setdefault(slug, {}).setdefault(provider, {})[voice_id] = mp3
    return by_post


def _provider_sections(
    providers: dict[str, dict[str, Path]],
) -> list[dict]:
    order = ["kokoro", "chatterbox", "piper", "styletts2"]
    sections: list[dict] = []
    for name in order:
        voices_on_disk = providers.get(name, {})
        if not voices_on_disk and name not in {v.provider for v in BAKEOFF_VARIANTS}:
            continue
        meta = PROVIDER_META.get(name, {"label": name, "license": "", "cloning": "", "notes": ""})
        variants = [v for v in BAKEOFF_VARIANTS if v.provider == name]
        voice_entries = []
        for variant in variants:
            path = voices_on_disk.get(variant.voice_id)
            voice_entries.append(
                {
                    "voice_id": variant.voice_id,
                    "label": variant.label,
                    "description": variant.description,
                    "file": path.name if path else None,
                    "ready": path is not None,
                }
            )
        # Include any extra files not in the curated variant list
        known = {v.voice_id for v in variants}
        for voice_id, path in sorted(voices_on_disk.items()):
            if voice_id in known:
                continue
            voice_entries.append(
                {
                    "voice_id": voice_id,
                    "label": voice_id,
                    "description": "",
                    "file": path.name,
                    "ready": True,
                }
            )
        if not voice_entries:
            continue
        sections.append(
            {
                "id": name,
                "label": meta["label"],
                "license": meta["license"],
                "cloning": meta["cloning"],
                "notes": meta.get("notes", ""),
                "demo_url": PROVIDER_DEMO_URLS.get(name, ""),
                "voices": voice_entries,
            }
        )
    return sections


def build_manifest(
    catalog: Catalog,
    by_post: dict[str, dict[str, dict[str, Path]]],
) -> list[dict]:
    posts: list[dict] = []
    for slug, providers in by_post.items():
        if slug == "__sample__":
            posts.append(
                {
                    "slug": slug,
                    "title": "Quick sample (intro + acronyms + outro)",
                    "url": BLOG_BASE,
                    "excerpt": "Same short script on every engine/voice for a fast check.",
                    "providers": _provider_sections(providers),
                }
            )
            continue
        row = catalog.get(slug)
        posts.append(
            {
                "slug": slug,
                "title": row.title if row and row.title else slug,
                "url": row.url if row and row.url else f"{BLOG_BASE}/{slug}/",
                "excerpt": (row.rss_excerpt or "")[:300] if row else "",
                "providers": _provider_sections(providers),
            }
        )
    posts.sort(key=lambda p: (p["slug"] != "__sample__", p["title"].lower()))
    return posts


def render_html(posts: list[dict]) -> str:
    posts_json = json.dumps(posts)
    demos_json = json.dumps(PROVIDER_DEMO_URLS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kellblog Audio — TTS Bake-off</title>
  <style>
    :root {{
      --bg: #1a2332;
      --card: #243044;
      --text: #e8ecf1;
      --muted: #9aa8bc;
      --accent: #d4a84b;
      --border: #3d4f66;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 1.5rem;
      line-height: 1.5;
    }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.75rem; }}
    .subtitle {{ color: var(--muted); margin-bottom: 1.5rem; }}
    nav.post-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 1.5rem;
    }}
    nav.post-tabs button {{
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 0.5rem 1rem;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.9rem;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    nav.post-tabs button.active {{
      border-color: var(--accent);
      background: #2d3a50;
    }}
    .post-panel {{ display: none; }}
    .post-panel.active {{ display: block; }}
    .post-header {{
      background: var(--card);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
      border: 1px solid var(--border);
    }}
    .post-header h2 {{ margin: 0 0 0.5rem; font-size: 1.35rem; }}
    .post-header a {{ color: var(--accent); }}
    .post-header .excerpt {{ color: var(--muted); font-size: 0.95rem; margin-top: 0.75rem; }}
    .engine-block {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1.25rem;
    }}
    .engine-block h3 {{
      margin: 0 0 0.35rem;
      color: var(--accent);
      font-size: 1.15rem;
    }}
    .engine-block .engine-meta {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 1rem;
    }}
    .engine-block .engine-meta a {{ color: var(--accent); }}
    .voice-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 0.85rem;
    }}
    .voice-card {{
      background: #1a2332;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.85rem;
    }}
    .voice-card h4 {{ margin: 0 0 0.2rem; font-size: 1rem; }}
    .voice-card .voice-desc {{ font-size: 0.78rem; color: var(--muted); margin-bottom: 0.5rem; }}
    audio {{ width: 100%; }}
    .demos {{
      margin-bottom: 2rem;
      padding: 1rem 1.25rem;
      background: var(--card);
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 0.9rem;
    }}
    .demos h2 {{ margin: 0 0 0.5rem; font-size: 1.05rem; color: var(--accent); }}
    .demos ul {{ margin: 0; padding-left: 1.25rem; color: var(--muted); }}
    .demos a {{ color: var(--accent); }}
    .note {{
      margin-top: 1.5rem;
      padding: 1rem;
      background: var(--card);
      border-radius: 8px;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    code {{ background: #1a2332; padding: 0.15rem 0.4rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Kellblog Audio — TTS Bake-off</h1>
  <p class="subtitle">Multiple voices per engine. Each clip: spoken intro + first ~2,000 characters + outro.</p>

  <div class="demos" id="demo-links"></div>

  <nav class="post-tabs" id="tabs"></nav>
  <div id="panels"></div>

  <p class="note">
    Serve this folder locally (required for audio in most browsers):<br>
    <code>uv run kellblog-audio bakeoff-serve</code><br>
    Then open <a href="http://localhost:8765/index.html" style="color: var(--accent)">http://localhost:8765/index.html</a>
  </p>

  <script>
    const POSTS = {posts_json};
    const DEMO_URLS = {demos_json};

    const demoLabels = {{
      kokoro: "Kokoro — try all 54 voices online",
      chatterbox: "Chatterbox on Hugging Face",
      piper: "Piper — browse 100+ voice samples",
      styletts2: "StyleTTS 2 paper demo (LibriTTS / VCTK samples)",
    }};

    const demoList = document.getElementById('demo-links');
    demoList.innerHTML = `
      <h2>Listen to voices online (not your text)</h2>
      <ul>${{Object.entries(DEMO_URLS).map(([k, url]) =>
        `<li><a href="${{url}}" target="_blank" rel="noopener">${{demoLabels[k] || k}}</a></li>`
      ).join('')}}</ul>`;

    const tabs = document.getElementById('tabs');
    const panels = document.getElementById('panels');

    function escapeHtml(s) {{
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }}

    POSTS.forEach((post, i) => {{
      const btn = document.createElement('button');
      btn.textContent = post.slug === '__sample__' ? 'Quick sample' : post.title;
      btn.title = post.title;
      if (i === 0) btn.classList.add('active');
      btn.onclick = () => showPost(post.slug);
      tabs.appendChild(btn);

      const panel = document.createElement('div');
      panel.className = 'post-panel' + (i === 0 ? ' active' : '');
      panel.dataset.slug = post.slug;

      const engines = post.providers.map(eng => {{
        const voices = eng.voices.map(v => {{
          if (v.ready && v.file) {{
            return `
              <div class="voice-card">
                <h4>${{escapeHtml(v.label)}}</h4>
                <p class="voice-desc">${{escapeHtml(v.description || v.voice_id)}}</p>
                <audio controls preload="metadata" src="${{escapeHtml(v.file)}}"></audio>
              </div>`;
          }}
          return `
            <div class="voice-card" style="opacity: 0.55">
              <h4>${{escapeHtml(v.label)}}</h4>
              <p class="voice-desc">Still generating…</p>
            </div>`;
        }}).join('');

        const demoLink = eng.demo_url
          ? ` · <a href="${{escapeHtml(eng.demo_url)}}" target="_blank" rel="noopener">Browse voices online</a>`
          : '';

        return `
          <div class="engine-block">
            <h3>${{escapeHtml(eng.label)}}</h3>
            <p class="engine-meta">${{escapeHtml(eng.license)}} · Cloning: ${{escapeHtml(eng.cloning)}}${{demoLink}}</p>
            ${{eng.notes ? `<p class="engine-meta">${{escapeHtml(eng.notes)}}</p>` : ''}}
            <div class="voice-grid">${{voices}}</div>
          </div>`;
      }}).join('');

      panel.innerHTML = `
        <div class="post-header">
          <h2>${{escapeHtml(post.title)}}</h2>
          <a href="${{escapeHtml(post.url)}}" target="_blank" rel="noopener">Original on Kellblog</a>
          ${{post.excerpt ? `<p class="excerpt">${{escapeHtml(post.excerpt)}}</p>` : ''}}
        </div>
        ${{engines}}
      `;
      panels.appendChild(panel);
    }});

    function showPost(slug) {{
      document.querySelectorAll('.post-panel').forEach(p => {{
        p.classList.toggle('active', p.dataset.slug === slug);
      }});
      POSTS.forEach((post, i) => {{
        const btn = tabs.children[i];
        if (btn) btn.classList.toggle('active', post.slug === slug);
      }});
    }}
  </script>
</body>
</html>
"""


def write_bakeoff_page(catalog: Catalog, bakeoff_dir: Path | None = None) -> Path:
    bakeoff_dir = bakeoff_dir or BAKEOFF_DIR
    bakeoff_dir.mkdir(parents=True, exist_ok=True)
    by_post = discover_bakeoff_files(bakeoff_dir)
    posts = build_manifest(catalog, by_post)
    html_content = render_html(posts)
    out = bakeoff_dir / "index.html"
    out.write_text(html_content, encoding="utf-8")
    (bakeoff_dir / "manifest.json").write_text(
        json.dumps(posts, indent=2), encoding="utf-8"
    )
    return out

# Archive QA Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resumable local `qa-audio --missing-only` sweep that fills in missing Whisper QA artifacts for completed episodes and can optionally queue real QA failures for regeneration.

**Architecture:** Keep the current QA pipeline and artifact location intact. Add one shared Whisper preflight helper in `qa.py`, then extend the existing `qa-audio` command in `cli.py` to select missing-artifact episodes, continue past per-episode errors, and print a batch summary that makes reruns and operator decisions straightforward.

**Tech Stack:** Python 3.11+, Typer, Rich, pathlib, pytest

---

## File map
- Modify: `src/kellblog_audio/qa.py:15-20,222-280`
- Modify: `src/kellblog_audio/cli.py:18-24,41,264-290`
- Modify: `tests/test_audio_qa.py:1-73`
- Create: `tests/test_cli_qa.py`

### Task 1: Factor shared Whisper preflight into `qa.py`

**Files:**
- Modify: `src/kellblog_audio/qa.py:15-20,222-254`
- Modify: `tests/test_audio_qa.py:1-73`
- Test: `tests/test_audio_qa.py`

- [ ] **Step 1: Write the failing tests for Whisper preflight**

```python
import pytest

from kellblog_audio import qa


def test_ensure_local_whisper_ready_requires_installed_cli(monkeypatch):
    monkeypatch.setattr(qa.shutil, "which", lambda _cmd: None)

    with pytest.raises(RuntimeError, match="Local Whisper CLI not found"):
        qa.ensure_local_whisper_ready()


def test_ensure_local_whisper_ready_requires_existing_model(tmp_path, monkeypatch):
    monkeypatch.setattr(qa.shutil, "which", lambda _cmd: "/usr/local/bin/whisper-cli")
    monkeypatch.setattr(qa, "WHISPER_MODEL", str(tmp_path / "missing-model.bin"))

    with pytest.raises(RuntimeError, match="Local Whisper model not found"):
        qa.ensure_local_whisper_ready()
```

- [ ] **Step 2: Run the targeted tests to confirm failure**

Run: `uv run pytest tests/test_audio_qa.py -k whisper_ready -v`  
Expected: FAIL because `ensure_local_whisper_ready()` does not exist yet.

- [ ] **Step 3: Add the minimal shared preflight helper and reuse it in `transcribe_audio()`**

```python
def ensure_local_whisper_ready() -> tuple[str, Path]:
    whisper = shutil.which(WHISPER_CLI)
    if not whisper:
        raise RuntimeError(f"Local Whisper CLI not found: {WHISPER_CLI}")

    model = Path(WHISPER_MODEL).expanduser()
    if not model.exists():
        raise RuntimeError(f"Local Whisper model not found: {model}")

    return whisper, model


def transcribe_audio(
    audio_path: Path,
    *,
    output_dir: Path = QA_TRANSCRIPTS_DIR,
    output_stem: str | None = None,
) -> Path:
    whisper, model = ensure_local_whisper_ready()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem or audio_path.stem
    out_base = output_dir / stem
    subprocess.run(
        [
            whisper,
            "-m",
            str(model),
            "-f",
            str(audio_path),
            "-l",
            "en",
            "-otxt",
            "-oj",
            "-of",
            str(out_base),
            "-np",
        ],
        check=True,
    )
    return out_base.with_suffix(".txt")
```

- [ ] **Step 4: Re-run the targeted tests**

Run: `uv run pytest tests/test_audio_qa.py -k whisper_ready -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/kellblog_audio/qa.py tests/test_audio_qa.py && git commit -m "refactor: share whisper QA preflight checks"`

### Task 2: Add missing-artifact selection to `qa-audio`

**Files:**
- Modify: `src/kellblog_audio/cli.py:18-24,41,264-290`
- Create: `tests/test_cli_qa.py`
- Test: `tests/test_cli_qa.py`

- [ ] **Step 1: Write the failing CLI tests for `--missing-only` selection and argument validation**

```python
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from kellblog_audio import cli
from kellblog_audio.catalog import PostRow


runner = CliRunner()


def _passing_result():
    return SimpleNamespace(
        passed=True,
        reason="ok",
        source_coverage=1.0,
        tail_similarity=1.0,
        max_repeated_three_gram=0,
    )


def test_qa_audio_missing_only_selects_done_posts_without_artifacts(tmp_path, monkeypatch):
    posts = [
        PostRow(slug="done-1", url="https://example.com/1", audio_status="done"),
        PostRow(slug="done-2", url="https://example.com/2", audio_status="done"),
        PostRow(slug="done-3", url="https://example.com/3", audio_status="done"),
    ]
    (tmp_path / "done-1.qa.json").write_text("{}", encoding="utf-8")
    calls: list[str] = []

    fake_catalog = SimpleNamespace(
        get=lambda _slug: None,
        list_by_filter=lambda **_kwargs: posts,
    )
    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(cli, "QA_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )
    monkeypatch.setattr(
        cli,
        "qa_post_audio",
        lambda _catalog, slug: calls.append(slug) or _passing_result(),
    )

    result = runner.invoke(cli.app, ["qa-audio", "--missing-only", "--limit", "1"])

    assert result.exit_code == 0
    assert calls == ["done-2"]
    assert "selected=1" in result.output
    assert "passed=1" in result.output


def test_qa_audio_rejects_slug_with_missing_only():
    result = runner.invoke(cli.app, ["qa-audio", "--slug", "done-1", "--missing-only"])

    assert result.exit_code != 0
    assert "--slug and --missing-only cannot be combined" in result.output
```

- [ ] **Step 2: Run the targeted CLI tests to confirm failure**

Run: `uv run pytest tests/test_cli_qa.py -k "missing_only or rejects_slug" -v`  
Expected: FAIL on the unknown `--missing-only` option and missing CLI wiring.

- [ ] **Step 3: Add selection logic, optional limit semantics, and one-time preflight**

```python
from kellblog_audio.catalog import Catalog, PostRow
from kellblog_audio.qa import ensure_local_whisper_ready, qa_post_audio, queue_audio_rerun


def _select_qa_posts(
    catalog: Catalog,
    *,
    slug: str | None,
    missing_only: bool,
    limit: int | None,
) -> list[PostRow]:
    if slug and missing_only:
        raise typer.BadParameter("--slug and --missing-only cannot be combined")

    if slug:
        post = catalog.get(slug)
        return [post] if post else []

    posts = catalog.list_by_filter(audio_status="done")
    if missing_only:
        existing = {path.name[: -len(".qa.json")] for path in QA_TRANSCRIPTS_DIR.glob("*.qa.json")}
        posts = [post for post in posts if post.slug not in existing]
        return posts if limit is None else posts[:limit]

    effective_limit = 5 if limit is None else limit
    return posts[:effective_limit]


@app.command("qa-audio")
def qa_audio(
    slug: Optional[str] = typer.Option(None, "--slug", "-s"),
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only QA done episodes without existing QA artifacts",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max done episodes to QA"),
    rerun_failed: bool = typer.Option(
        False,
        "--rerun-failed",
        help="Mark failed QA episodes stale so synthesize --pending regenerates them",
    ),
) -> None:
    cat = _catalog()
    posts = _select_qa_posts(cat, slug=slug, missing_only=missing_only, limit=limit)
    if not posts:
        console.print("QA sweep complete: selected=0 checked=0 passed=0 failed=0 errored=0 queued-for-rerun=0")
        return

    ensure_local_whisper_ready()
    for post in posts:
        if not post:
            continue
        result = qa_post_audio(cat, post.slug)
        if rerun_failed and not result.passed:
            queue_audio_rerun(cat, post.slug, result.reason)
        style = "green" if result.passed else "red"
        rerun_note = " queued-for-rerun" if rerun_failed and not result.passed else ""
        console.print(
            f"[{style}]{post.slug}: {result.reason}{rerun_note} "
            f"(coverage={result.source_coverage:.1%}, "
            f"tail={result.tail_similarity:.1%}, "
            f"repeat3={result.max_repeated_three_gram})[/{style}]"
        )
```

- [ ] **Step 4: Re-run the targeted CLI tests**

Run: `uv run pytest tests/test_cli_qa.py -k "missing_only or rejects_slug" -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/kellblog_audio/cli.py tests/test_cli_qa.py && git commit -m "feat: add missing-only selection to qa-audio"`

### Task 3: Make `qa-audio` resumable and operator-friendly for archive sweeps

**Files:**
- Modify: `src/kellblog_audio/cli.py:264-320`
- Modify: `tests/test_cli_qa.py`
- Test: `tests/test_cli_qa.py`, `tests/test_audio_qa.py`

- [ ] **Step 1: Add the failing CLI tests for continue-on-error and rerun behavior**

```python
def test_qa_audio_continues_after_episode_error_and_only_queues_real_failures(tmp_path, monkeypatch):
    posts = [
        PostRow(slug="error-post", url="https://example.com/error", audio_status="done"),
        PostRow(slug="fail-post", url="https://example.com/fail", audio_status="done"),
    ]
    queued: list[tuple[str, str]] = []

    fake_catalog = SimpleNamespace(
        get=lambda _slug: None,
        list_by_filter=lambda **_kwargs: posts,
    )
    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(cli, "QA_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "ensure_local_whisper_ready",
        lambda: ("/usr/local/bin/whisper-cli", Path("/tmp/model.bin")),
    )

    def fake_qa(_catalog, slug):
        if slug == "error-post":
            raise RuntimeError("missing local mp3")
        return SimpleNamespace(
            passed=False,
            reason="coverage 10.0% < 85%",
            source_coverage=0.10,
            tail_similarity=0.92,
            max_repeated_three_gram=0,
        )

    monkeypatch.setattr(cli, "qa_post_audio", fake_qa)
    monkeypatch.setattr(cli, "queue_audio_rerun", lambda _catalog, slug, reason: queued.append((slug, reason)))

    result = runner.invoke(cli.app, ["qa-audio", "--missing-only", "--rerun-failed"])

    assert result.exit_code == 0
    assert queued == [("fail-post", "coverage 10.0% < 85%")]
    assert "errored=1" in result.output
    assert "failed=1" in result.output
    assert "queued-for-rerun=1" in result.output
```

- [ ] **Step 2: Run the targeted CLI tests to confirm failure**

Run: `uv run pytest tests/test_cli_qa.py -k "continues_after_episode_error" -v`  
Expected: FAIL because `qa-audio` still stops on the first exception and does not print batch counts.

- [ ] **Step 3: Add per-episode error handling, rerun filtering, and summary output**

```python
selected = len(posts)
checked = 0
passed = 0
failed = 0
errored = 0
queued = 0

for post in posts:
    if not post:
        continue

    try:
        result = qa_post_audio(cat, post.slug)
    except Exception as exc:
        errored += 1
        console.print(f"[yellow]{post.slug}: error {exc}[/yellow]")
        continue

    checked += 1
    if rerun_failed and not result.passed:
        queue_audio_rerun(cat, post.slug, result.reason)
        queued += 1

    if result.passed:
        passed += 1
        style = "green"
    else:
        failed += 1
        style = "red"

    rerun_note = " queued-for-rerun" if rerun_failed and not result.passed else ""
    console.print(
        f"[{style}]{post.slug}: {result.reason}{rerun_note} "
        f"(coverage={result.source_coverage:.1%}, "
        f"tail={result.tail_similarity:.1%}, "
        f"repeat3={result.max_repeated_three_gram})[/{style}]"
    )

console.print(
    "QA sweep complete: "
    f"selected={selected} checked={checked} passed={passed} "
    f"failed={failed} errored={errored} queued-for-rerun={queued}"
)
```

- [ ] **Step 4: Re-run the targeted regression tests**

Run: `uv run pytest tests/test_audio_qa.py tests/test_cli_qa.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/kellblog_audio/cli.py tests/test_cli_qa.py tests/test_audio_qa.py && git commit -m "feat: make qa-audio resumable for archive sweeps"`

## Final verification
- [ ] Run: `uv run pytest tests/test_audio_qa.py tests/test_cli_qa.py -v`
- [ ] Run: `uv run kellblog-audio qa-audio --missing-only --limit 1`
- [ ] Confirm the command exits `0` and prints `selected=1 checked=1`
- [ ] Run: `uv run kellblog-audio qa-stats`
- [ ] Confirm `qa artifacts` increased by `1` and `done missing qa` decreased by `1`
- [ ] If the smoke run looks correct, launch the full sweep with `uv run kellblog-audio qa-audio --missing-only`

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kellblog_audio import cli


runner = CliRunner()


def test_synthesize_command_wires_distributed_options(tmp_path, monkeypatch):
    fake_catalog = object()
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)

    def fake_synthesize_batch(catalog, **kwargs):
        calls["catalog"] = catalog
        calls["kwargs"] = kwargs
        return (3, 1)

    monkeypatch.setattr(cli, "synthesize_batch", fake_synthesize_batch)

    manifest_path = tmp_path / "shard.json"
    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--run-id",
            "run-1",
            "--shard",
            "0/2",
            "--upload-r2",
            "--manifest-out",
            str(manifest_path),
            "--manifest-r2-key",
            "backfill/runs/run-1/manifests/shard-0-of-2.json",
        ],
    )

    assert result.exit_code == 0
    assert calls["catalog"] is fake_catalog
    assert calls["kwargs"]["run_id"] == "run-1"
    assert calls["kwargs"]["upload_r2"] is True
    assert calls["kwargs"]["manifest_out"] == manifest_path
    assert calls["kwargs"]["manifest_r2_key"] == "backfill/runs/run-1/manifests/shard-0-of-2.json"
    assert calls["kwargs"]["shard_index"] == 0
    assert calls["kwargs"]["shard_count"] == 2


def test_synthesize_command_rejects_manifest_output_without_shard(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "synthesize_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--run-id",
            "run-1",
            "--manifest-out",
            str(tmp_path / "shard.json"),
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)
    assert "--shard is required when writing shard manifests" in result.output


def test_create_backfill_baseline_command_uses_helper(monkeypatch):
    fake_catalog = object()
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(
        cli,
        "create_backfill_baseline",
        lambda catalog, run_id: calls.append((catalog, run_id)) or "backfill/runs/run-1/baseline/catalog.sqlite",
    )

    result = runner.invoke(cli.app, ["create-backfill-baseline", "--run-id", "run-1"])

    assert result.exit_code == 0
    assert calls == [(fake_catalog, "run-1")]
    assert "backfill/runs/run-1/baseline/catalog.sqlite" in result.output


def test_merge_shard_manifests_command_uses_manifest_dir(tmp_path, monkeypatch):
    fake_catalog = object()
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "b.json").write_text("{}", encoding="utf-8")
    (manifest_dir / "a.json").write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)

    def fake_merge(catalog, run_id, manifests):
        calls["catalog"] = catalog
        calls["run_id"] = run_id
        calls["manifests"] = manifests
        return SimpleNamespace(done=2, errors=1, skipped=0)

    monkeypatch.setattr(cli, "merge_shard_manifests", fake_merge)

    result = runner.invoke(
        cli.app,
        ["merge-shard-manifests", "--run-id", "run-1", "--manifest-dir", str(manifest_dir)],
    )

    assert result.exit_code == 0
    assert calls["catalog"] is fake_catalog
    assert calls["run_id"] == "run-1"
    assert calls["manifests"] == [manifest_dir / "a.json", manifest_dir / "b.json"]
    assert "Merged 2 done / 1 errors / 0 skipped" in result.output


def test_merge_shard_manifests_command_rejects_empty_manifest_dir(tmp_path, monkeypatch):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()

    monkeypatch.setattr(cli, "_catalog", lambda: object())

    result = runner.invoke(
        cli.app,
        ["merge-shard-manifests", "--run-id", "run-1", "--manifest-dir", str(manifest_dir)],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "no shard manifests found" in str(result.exception)


def test_restore_catalog_uses_uninitialized_catalog_then_inits_schema(monkeypatch):
    calls: list[object] = []

    class FakeCatalog:
        path = Path("/tmp/catalog.sqlite")

        def init_schema(self) -> None:
            calls.append("init_schema")

    fake_catalog = FakeCatalog()

    monkeypatch.setattr(
        cli,
        "_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("_catalog should not be used")),
    )
    monkeypatch.setattr(
        cli,
        "_catalog_uninitialized",
        lambda: calls.append("_catalog_uninitialized") or fake_catalog,
    )
    monkeypatch.setattr(
        cli,
        "restore_catalog",
        lambda catalog, key=None: calls.append((catalog, key)) or True,
    )

    result = runner.invoke(cli.app, ["restore-catalog", "--run-id", "run-1", "--kind", "baseline"])

    assert result.exit_code == 0
    assert calls == [
        "_catalog_uninitialized",
        (fake_catalog, "backfill/runs/run-1/baseline/catalog.sqlite"),
        "init_schema",
    ]


def test_backup_catalog_accepts_explicit_or_run_scoped_keys(monkeypatch):
    fake_catalog = object()
    calls: list[tuple[object, str | None]] = []

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(
        cli,
        "backup_catalog",
        lambda catalog, key=None: calls.append((catalog, key)) or (key or "backup/default.sqlite"),
    )

    explicit = runner.invoke(cli.app, ["backup-catalog", "--key", "custom/catalog.sqlite"])
    run_scoped = runner.invoke(
        cli.app,
        ["backup-catalog", "--run-id", "run-1", "--kind", "final"],
    )

    assert explicit.exit_code == 0
    assert run_scoped.exit_code == 0
    assert calls == [
        (fake_catalog, "custom/catalog.sqlite"),
        (fake_catalog, "backfill/runs/run-1/catalog/final.sqlite"),
    ]


@pytest.mark.parametrize(
    ("args", "expected_key"),
    [
        (["--key", "custom/catalog.sqlite"], "custom/catalog.sqlite"),
        (["--run-id", "run-1", "--kind", "final"], "backfill/runs/run-1/catalog/final.sqlite"),
    ],
)
def test_backup_catalog_key_resolution_examples(args, expected_key, monkeypatch):
    fake_catalog = object()
    calls: list[tuple[object, str | None]] = []

    monkeypatch.setattr(cli, "_catalog", lambda: fake_catalog)
    monkeypatch.setattr(
        cli,
        "backup_catalog",
        lambda catalog, key=None: calls.append((catalog, key)) or (key or "backup/default.sqlite"),
    )

    result = runner.invoke(cli.app, ["backup-catalog", *args])

    assert result.exit_code == 0
    assert calls == [(fake_catalog, expected_key)]


def test_progress_backfill_command_uses_helper(monkeypatch):
    snapshot = SimpleNamespace(
        run_id="run-1",
        shard_count=2,
        assigned_count=19,
        processed_count=14,
        counts={"done": 13, "error": 1, "skipped": 0},
        shards=[
            SimpleNamespace(
                shard_index=0,
                shard_count=2,
                processed_count=5,
                assigned_count=10,
                counts={"done": 4, "error": 1, "skipped": 0},
                last_slug="alpha",
                complete=False,
            )
        ],
    )
    calls: list[str] = []

    monkeypatch.setattr(cli, "read_backfill_progress", lambda run_id: calls.append(run_id) or snapshot)

    result = runner.invoke(cli.app, ["progress-backfill", "--run-id", "run-1"])

    assert result.exit_code == 0
    assert calls == ["run-1"]
    assert "run-1" in result.output
    assert "13 done / 1 errors / 0 skipped" in result.output
    assert "0/2" in result.output
    assert "5/10" in result.output


def test_progress_backfill_command_surfaces_empty_progress(monkeypatch):
    monkeypatch.setattr(
        cli,
        "read_backfill_progress",
        lambda _run_id: (_ for _ in ()).throw(ValueError("no shard progress found for run_id: run-1")),
    )

    result = runner.invoke(cli.app, ["progress-backfill", "--run-id", "run-1"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "no shard progress found" in str(result.exception)
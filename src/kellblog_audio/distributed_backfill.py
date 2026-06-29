"""Helpers for run-scoped distributed backfill coordination."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kellblog_audio.catalog import Catalog
from kellblog_audio.ingest import ingest_all
from kellblog_audio.config import R2_BUCKET
from kellblog_audio.publish import backup_catalog, get_s3_client

_ALLOWED_ITEM_STATUSES = frozenset({"done", "error", "skip", "skipped"})


def _required_done_fields(item: "ShardManifestItem") -> list[str]:
    required = {
        "audio_path": item.audio_path,
        "duration_sec": item.duration_sec,
        "audio_bytes": item.audio_bytes,
    }
    return [field for field, value in required.items() if value is None]


def _update_post_in_txn(conn: Any, slug: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [slug]
    conn.execute(f"UPDATE posts SET {cols} WHERE slug = ?", values)


@dataclass(frozen=True)
class ShardManifestItem:
    slug: str
    status: str
    year: int | None = None
    audio_path: str | None = None
    duration_sec: int | None = None
    audio_bytes: int | None = None
    audio_etag: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("manifest item slug is required")
        if self.status not in _ALLOWED_ITEM_STATUSES:
            raise ValueError(f"unsupported manifest item status: {self.status}")
        if self.status == "done":
            missing_fields = _required_done_fields(self)
            if missing_fields:
                missing = ", ".join(missing_fields)
                raise ValueError(
                    f"done manifest item missing required fields: {missing}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShardManifestItem:
        return cls(
            slug=data["slug"],
            status=data["status"],
            year=data.get("year"),
            audio_path=data.get("audio_path"),
            duration_sec=data.get("duration_sec"),
            audio_bytes=data.get("audio_bytes"),
            audio_etag=data.get("audio_etag"),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class ShardManifest:
    run_id: str
    shard_index: int | None = None
    shard_count: int | None = None
    provider: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    items: list[ShardManifestItem] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"done": 0, "error": 0, "skipped": 0}
        for item in self.items:
            if item.status == "done":
                counts["done"] += 1
            elif item.status == "error":
                counts["error"] += 1
            else:
                counts["skipped"] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "provider": self.provider,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "items": [item.to_dict() for item in self.items],
            "counts": self.counts,
        }
        return {key: value for key, value in data.items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShardManifest:
        return cls(
            run_id=data["run_id"],
            shard_index=data.get("shard_index"),
            shard_count=data.get("shard_count"),
            provider=data.get("provider"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            items=[ShardManifestItem.from_dict(item) for item in data.get("items", [])],
        )

    @classmethod
    def from_json(cls, raw: str) -> ShardManifest:
        return cls.from_dict(json.loads(raw))

    @classmethod
    def from_path(cls, path: Path) -> ShardManifest:
        return cls.from_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class MergeResult:
    run_id: str
    done: int = 0
    errors: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ShardProgress:
    run_id: str
    shard_index: int
    shard_count: int
    assigned_count: int
    processed_count: int
    counts: dict[str, int]
    provider: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    last_slug: str | None = None
    last_status: str | None = None
    complete: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "provider": self.provider,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "assigned_count": self.assigned_count,
            "processed_count": self.processed_count,
            "counts": self.counts,
            "last_slug": self.last_slug,
            "last_status": self.last_status,
            "complete": self.complete,
            "error": self.error,
        }
        return {key: value for key, value in data.items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShardProgress":
        return cls(
            run_id=data["run_id"],
            shard_index=data["shard_index"],
            shard_count=data["shard_count"],
            provider=data.get("provider"),
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
            finished_at=data.get("finished_at"),
            assigned_count=data["assigned_count"],
            processed_count=data["processed_count"],
            counts=data.get("counts", {"done": 0, "error": 0, "skipped": 0}),
            last_slug=data.get("last_slug"),
            last_status=data.get("last_status"),
            complete=bool(data.get("complete", False)),
            error=data.get("error"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "ShardProgress":
        return cls.from_dict(json.loads(raw))


@dataclass(frozen=True)
class BackfillProgressSnapshot:
    run_id: str
    shard_count: int
    assigned_count: int
    processed_count: int
    counts: dict[str, int]
    shards: list[ShardProgress] = field(default_factory=list)


def baseline_catalog_key(run_id: str) -> str:
    return f"backfill/runs/{run_id}/baseline/catalog.sqlite"


def shard_progress_key(run_id: str, shard_index: int, shard_count: int) -> str:
    return f"backfill/runs/{run_id}/progress/shard-{shard_index}-of-{shard_count}.json"


def create_backfill_baseline(catalog: Catalog, run_id: str) -> str:
    ingest_all(catalog)
    return backup_catalog(catalog, key=baseline_catalog_key(run_id))


def read_backfill_progress(run_id: str) -> BackfillProgressSnapshot:
    client = get_s3_client()
    prefix = f"backfill/runs/{run_id}/progress/"
    pattern = re.compile(rf"^{re.escape(prefix)}shard-([0-9]+)-of-([0-9]+)\.json$")
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []

    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if pattern.match(key):
                keys.append(key)

    if not keys:
        raise ValueError(f"no shard progress found for run_id: {run_id}")

    shards: list[ShardProgress] = []
    shard_count: int | None = None
    assigned_count = 0
    processed_count = 0
    counts = {"done": 0, "error": 0, "skipped": 0}

    for key in sorted(keys):
        body = client.get_object(Bucket=R2_BUCKET, Key=key)["Body"].read()
        progress = ShardProgress.from_json(body.decode("utf-8"))
        if progress.run_id != run_id:
            raise ValueError(f"progress run_id mismatch for {key}: {progress.run_id} != {run_id}")
        if shard_count is None:
            shard_count = progress.shard_count
        elif progress.shard_count != shard_count:
            raise ValueError(
                f"progress shard_count mismatch for {key}: {progress.shard_count} != {shard_count}"
            )
        shards.append(progress)
        assigned_count += progress.assigned_count
        processed_count += progress.processed_count
        counts["done"] += progress.counts.get("done", 0)
        counts["error"] += progress.counts.get("error", 0)
        counts["skipped"] += progress.counts.get("skipped", 0)

    shards.sort(key=lambda progress: progress.shard_index)
    return BackfillProgressSnapshot(
        run_id=run_id,
        shard_count=shard_count or 0,
        assigned_count=assigned_count,
        processed_count=processed_count,
        counts=counts,
        shards=shards,
    )


def _load_and_validate_shard_manifests(
    run_id: str, manifests: list[Path]
) -> list[tuple[Path, ShardManifest]]:
    if not manifests:
        raise ValueError("no shard manifests found")

    loaded: list[tuple[Path, ShardManifest]] = []
    shard_count: int | None = None
    shard_indexes: set[int] = set()

    for manifest_path in sorted(manifests, key=lambda path: str(path)):
        manifest = ShardManifest.from_path(manifest_path)
        if manifest.run_id != run_id:
            raise ValueError(
                f"manifest run_id mismatch for {manifest_path}: {manifest.run_id} != {run_id}"
            )
        if manifest.shard_count is None:
            raise ValueError(f"manifest shard_count missing for {manifest_path}")
        if manifest.shard_count < 1:
            raise ValueError(
                f"manifest shard_count must be >= 1 for {manifest_path}: {manifest.shard_count}"
            )
        if manifest.shard_index is None:
            raise ValueError(f"manifest shard_index missing for {manifest_path}")
        if not 0 <= manifest.shard_index < manifest.shard_count:
            raise ValueError(
                f"manifest shard_index out of range for {manifest_path}: "
                f"{manifest.shard_index} not in 0..{manifest.shard_count - 1}"
            )
        if shard_count is None:
            shard_count = manifest.shard_count
        elif manifest.shard_count != shard_count:
            raise ValueError(
                f"manifest shard_count mismatch for {manifest_path}: "
                f"{manifest.shard_count} != {shard_count}"
            )
        if manifest.shard_index in shard_indexes:
            raise ValueError(
                f"duplicate shard_index in shard manifests: {manifest.shard_index}"
            )

        shard_indexes.add(manifest.shard_index)
        loaded.append((manifest_path, manifest))

    expected_indexes = set(range(shard_count or 0))
    missing_indexes = sorted(expected_indexes - shard_indexes)
    if missing_indexes:
        missing = ", ".join(str(index) for index in missing_indexes)
        raise ValueError(f"missing shard manifests for shard_index values: {missing}")

    return loaded


def merge_shard_manifests(
    catalog: Catalog, run_id: str, manifests: list[Path]
) -> MergeResult:
    seen: set[str] = set()
    items_to_apply: list[ShardManifestItem] = []
    done = 0
    errors = 0
    skipped = 0

    for _manifest_path, manifest in _load_and_validate_shard_manifests(run_id, manifests):
        for item in sorted(manifest.items, key=lambda entry: entry.slug):
            if item.slug in seen:
                raise ValueError(f"duplicate slug in shard manifests: {item.slug}")
            if catalog.get(item.slug) is None:
                raise ValueError(f"manifest slug not found in catalog: {item.slug}")
            seen.add(item.slug)
            items_to_apply.append(item)

    with catalog.connect() as conn:
        for item in items_to_apply:
            if item.status == "done":
                _update_post_in_txn(
                    conn,
                    item.slug,
                    audio_path=item.audio_path,
                    audio_bytes=item.audio_bytes,
                    audio_etag=item.audio_etag,
                    audio_status="done",
                    audio_error=None,
                    duration_sec=item.duration_sec,
                    backfill_run_id=run_id,
                )
                done += 1
            elif item.status == "error":
                _update_post_in_txn(
                    conn,
                    item.slug,
                    audio_status="error",
                    audio_error=item.error,
                )
                errors += 1
            else:
                _update_post_in_txn(
                    conn,
                    item.slug,
                    audio_status="skip",
                    audio_error=item.error,
                )
                skipped += 1

    return MergeResult(run_id=run_id, done=done, errors=errors, skipped=skipped)
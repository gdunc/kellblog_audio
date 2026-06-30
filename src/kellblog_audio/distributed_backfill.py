"""Helpers for run-scoped distributed backfill coordination."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kellblog_audio.catalog import Catalog
from kellblog_audio.ingest import ingest_all
from kellblog_audio.config import R2_BUCKET, get_settings
from kellblog_audio.publish import backup_catalog, get_s3_client, restore_catalog, upload_file

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


@dataclass(frozen=True)
class ShardManifestSnapshot:
    run_id: str
    shard_count: int
    found_shards: list[int] = field(default_factory=list)
    missing_shards: list[int] = field(default_factory=list)
    unexpected_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BackfillRunPlan:
    run_id: str
    shard_count: int
    qa_first: int
    year: str | None = None
    local_helper_shards: list[int] = field(default_factory=list)
    completed_shards: list[int] = field(default_factory=list)
    missing_shards: list[int] = field(default_factory=list)
    gha_shards: list[int] = field(default_factory=list)
    resume_requested: bool = False


@dataclass(frozen=True)
class SeedBackfillBaselineResult:
    run_id: str
    baseline_key: str
    uploaded: int = 0
    requeued_errors: int = 0


@dataclass(frozen=True)
class BackfillAutoRestartPlan:
    should_dispatch: bool
    mode: str
    reason: str
    next_resume_depth: int
    gha_shards: list[int] = field(default_factory=list)
    missing_shards: list[int] = field(default_factory=list)
    resume_run_id: str | None = None
    seed_run_id: str | None = None


def baseline_catalog_key(run_id: str) -> str:
    return f"backfill/runs/{run_id}/baseline/catalog.sqlite"


def final_catalog_key(run_id: str) -> str:
    return f"backfill/runs/{run_id}/catalog/final.sqlite"


def _manifest_prefix(run_id: str) -> str:
    return f"backfill/runs/{run_id}/manifests/"


def shard_progress_key(run_id: str, shard_index: int, shard_count: int) -> str:
    return f"backfill/runs/{run_id}/progress/shard-{shard_index}-of-{shard_count}.json"


def create_backfill_baseline(catalog: Catalog, run_id: str) -> str:
    ingest_all(catalog)
    return backup_catalog(catalog, key=baseline_catalog_key(run_id))


def prepare_backfill_baseline(catalog: Catalog, run_id: str, *, resume: bool = False) -> str:
    key = baseline_catalog_key(run_id)
    if not resume:
        return create_backfill_baseline(catalog, run_id)
    if not restore_catalog(catalog, key=key):
        raise ValueError(f"no baseline catalog found for run_id: {run_id}")
    catalog.init_schema()
    return key


def requeue_error_posts(catalog: Catalog, *, status: str = "stale") -> int:
    if status not in {"pending", "stale"}:
        raise ValueError("status must be pending or stale")

    requeued = 0
    for post in catalog.list_by_filter(audio_status="error"):
        catalog.update_post(
            post.slug,
            audio_path=None,
            audio_bytes=None,
            audio_etag=None,
            audio_status=status,
            audio_error=None,
            duration_sec=None,
            feed_published_at=None,
            backfill_run_id=None,
        )
        requeued += 1
    return requeued


def seed_backfill_baseline_from_local_catalog(
    catalog: Catalog,
    run_id: str,
    *,
    retry_errors: bool = False,
) -> SeedBackfillBaselineResult:
    ingest_all(catalog)
    settings = get_settings()
    client = get_s3_client()
    uploaded = 0

    for post in catalog.list_by_filter(audio_status="done"):
        if not post.audio_path:
            raise ValueError(f"done post missing audio_path: {post.slug}")
        local_path = settings.root / post.audio_path
        if not local_path.exists():
            raise ValueError(f"done post missing local audio file: {post.slug}")
        audio_key = f"audio/{post.year or 1970}/{post.slug}.mp3"
        audio_etag = upload_file(client, local_path, audio_key, "audio/mpeg")
        update_fields: dict[str, Any] = {"backfill_run_id": run_id}
        if audio_etag is not None:
            update_fields["audio_etag"] = audio_etag
        catalog.update_post(post.slug, **update_fields)
        uploaded += 1

    requeued_errors = requeue_error_posts(catalog) if retry_errors else 0
    baseline_key = backup_catalog(catalog, key=baseline_catalog_key(run_id))
    return SeedBackfillBaselineResult(
        run_id=run_id,
        baseline_key=baseline_key,
        uploaded=uploaded,
        requeued_errors=requeued_errors,
    )


def seed_backfill_baseline_from_run_catalog(
    catalog: Catalog,
    run_id: str,
    source_run_id: str,
    *,
    source_kind: str = "final",
    retry_errors: bool = True,
) -> SeedBackfillBaselineResult:
    normalized_kind = source_kind.strip().lower()
    if normalized_kind == "final":
        source_key = final_catalog_key(source_run_id)
    elif normalized_kind == "baseline":
        source_key = baseline_catalog_key(source_run_id)
    else:
        raise ValueError("source_kind must be baseline or final")

    if not restore_catalog(catalog, key=source_key):
        raise ValueError(
            f"no {normalized_kind} catalog found for source_run_id: {source_run_id}"
        )
    catalog.init_schema()
    requeued_errors = requeue_error_posts(catalog) if retry_errors else 0
    baseline_key = backup_catalog(catalog, key=baseline_catalog_key(run_id))
    return SeedBackfillBaselineResult(
        run_id=run_id,
        baseline_key=baseline_key,
        uploaded=0,
        requeued_errors=requeued_errors,
    )


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


def read_backfill_manifest_state(run_id: str, shard_count: int) -> ShardManifestSnapshot:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")

    client = get_s3_client()
    prefix = _manifest_prefix(run_id)
    pattern = re.compile(rf"^{re.escape(prefix)}shard-([0-9]+)-of-([0-9]+)\.json$")
    paginator = client.get_paginator("list_objects_v2")
    found_shards: set[int] = set()
    unexpected_keys: list[str] = []

    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            match = pattern.match(key)
            if not match:
                unexpected_keys.append(key)
                continue
            shard_index = int(match.group(1))
            key_shard_count = int(match.group(2))
            if key_shard_count != shard_count or not 0 <= shard_index < shard_count:
                unexpected_keys.append(key)
                continue
            found_shards.add(shard_index)

    found = sorted(found_shards)
    missing = sorted(set(range(shard_count)) - found_shards)
    return ShardManifestSnapshot(
        run_id=run_id,
        shard_count=shard_count,
        found_shards=found,
        missing_shards=missing,
        unexpected_keys=sorted(unexpected_keys),
    )


def parse_local_helper_shards(raw: str | None, shard_count: int) -> list[int]:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    helper_shards: list[int] = []
    if not raw:
        return helper_shards

    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        shard = int(value)
        if not 0 <= shard < shard_count:
            raise ValueError(
                f"local_helper_shards contains out-of-range shard {shard}; expected 0..{shard_count - 1}"
            )
        helper_shards.append(shard)
    return sorted(set(helper_shards))


def _normalize_year(year: str | None) -> str | None:
    if year is None:
        return None
    value = year.strip()
    if not value:
        return None
    try:
        return str(int(value))
    except ValueError as exc:
        raise ValueError("year must be blank or an integer") from exc


def plan_backfill_run(
    *,
    shard_count: int,
    qa_first: int,
    year: str | None = None,
    local_helper_shards_raw: str | None = None,
    github_run_id: str | None = None,
    resume_run_id: str | None = None,
    now: datetime | None = None,
) -> BackfillRunPlan:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if qa_first < 0:
        raise ValueError("qa_first must be >= 0")

    normalized_year = _normalize_year(year)
    helper_shards = parse_local_helper_shards(local_helper_shards_raw, shard_count)
    normalized_resume_run_id = (resume_run_id or "").strip() or None
    resume_requested = normalized_resume_run_id is not None

    if resume_requested:
        run_id = normalized_resume_run_id
        manifest_state = read_backfill_manifest_state(run_id, shard_count)
        if manifest_state.unexpected_keys:
            raise ValueError(
                "unexpected manifest keys for resumed run: "
                + ", ".join(manifest_state.unexpected_keys)
            )
    else:
        if not github_run_id:
            raise ValueError("github_run_id is required for a fresh run")
        timestamp = now or datetime.now(timezone.utc)
        run_id = f"{timestamp:%Y%m%dT%H%M%SZ}-{github_run_id}"
        manifest_state = ShardManifestSnapshot(
            run_id=run_id,
            shard_count=shard_count,
            found_shards=[],
            missing_shards=list(range(shard_count)),
            unexpected_keys=[],
        )

    gha_shards = [
        shard for shard in manifest_state.missing_shards if shard not in helper_shards
    ]
    return BackfillRunPlan(
        run_id=run_id,
        shard_count=shard_count,
        qa_first=qa_first,
        year=normalized_year,
        local_helper_shards=helper_shards,
        completed_shards=manifest_state.found_shards,
        missing_shards=manifest_state.missing_shards,
        gha_shards=gha_shards,
        resume_requested=resume_requested,
    )


def plan_backfill_auto_restart(
    *,
    run_id: str,
    shard_count: int,
    qa_first: int,
    year: str | None = None,
    local_helper_shards_raw: str | None = None,
    auto_resume: bool = True,
    resume_depth: int = 0,
    max_auto_resumes: int = 10,
    summary_error_count: int | None = None,
) -> BackfillAutoRestartPlan:
    if resume_depth < 0:
        raise ValueError("resume_depth must be >= 0")
    if max_auto_resumes < 0:
        raise ValueError("max_auto_resumes must be >= 0")

    next_resume_depth = resume_depth + 1
    if not auto_resume:
        return BackfillAutoRestartPlan(
            should_dispatch=False,
            mode="none",
            reason="auto-resume disabled",
            next_resume_depth=next_resume_depth,
        )
    if resume_depth >= max_auto_resumes:
        return BackfillAutoRestartPlan(
            should_dispatch=False,
            mode="none",
            reason=f"resume limit reached ({resume_depth}/{max_auto_resumes})",
            next_resume_depth=next_resume_depth,
        )

    plan = plan_backfill_run(
        shard_count=shard_count,
        qa_first=qa_first,
        year=year,
        local_helper_shards_raw=local_helper_shards_raw,
        resume_run_id=run_id,
    )

    if plan.gha_shards:
        shard_list = ",".join(str(shard) for shard in plan.gha_shards)
        return BackfillAutoRestartPlan(
            should_dispatch=True,
            mode="resume",
            reason=f"missing non-helper shard manifests: {shard_list}",
            next_resume_depth=next_resume_depth,
            gha_shards=plan.gha_shards,
            missing_shards=plan.missing_shards,
            resume_run_id=run_id,
        )

    if summary_error_count and summary_error_count > 0:
        return BackfillAutoRestartPlan(
            should_dispatch=True,
            mode="retry-errors",
            reason=f"manifest set complete but {summary_error_count} error rows remain",
            next_resume_depth=next_resume_depth,
            gha_shards=[],
            missing_shards=plan.missing_shards,
            seed_run_id=run_id,
        )

    reason = "no missing non-helper shard manifests"
    if summary_error_count == 0:
        reason += " and no error rows remain"
    return BackfillAutoRestartPlan(
        should_dispatch=False,
        mode="none",
        reason=reason,
        next_resume_depth=next_resume_depth,
        gha_shards=[],
        missing_shards=plan.missing_shards,
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

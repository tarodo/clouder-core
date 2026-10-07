"""Task Lambda behind the backfill state machine (docs/ops/backfill.md).

Replays stored raw Beatport runs through the canonicalizer: `plan` lists the run
behind each raw object, `replay` canonicalizes one (dry run or apply), `summarize`
adds the results up. The Beatport token never reaches this path.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date
from typing import Any, Mapping, Sequence

from .canonicalize import Canonicalizer
from .contracts import screen_run
from .logging_utils import log_event
from .models import RunStatus
from .normalize import normalize_tracks
from .repositories import as_utc_datetime, create_clouder_repository_from_env, utc_now
from .settings import get_worker_settings
from .storage import S3Storage, create_default_s3_client
from .worker_handler import _enqueue_spotify_search_after_canonicalization

COUNT_FIELDS = (
    "tracks_total",
    "labels_created",
    "styles_created",
    "artists_created",
    "albums_created",
    "tracks_created",
    "tracks_changed",
    "tracks_stale",
)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    action = event.get("action")
    if action == "plan":
        return plan(event.get("input") or {}, _repository())
    if action == "replay":
        return replay(
            event["run"],
            dry_run=bool(event["dry_run"]),
            repository=_repository(),
            storage=_storage(),
        )
    if action == "summarize":
        return summarize(event.get("results") or [], dry_run=bool(event.get("dry_run", True)))
    raise ValueError(f"unknown backfill action: {action!r}")


PLAN_INPUT_KEYS = frozenset({"dry_run", "style_ids", "since", "until"})


def plan(params: Mapping[str, Any], repository: Any) -> dict[str, Any]:
    # A misspelt filter must fail, not widen an apply to every style.
    unknown = sorted(set(params) - PLAN_INPUT_KEYS)
    if unknown:
        raise ValueError(f"unknown backfill input: {', '.join(unknown)}")
    dry_run = params.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be true or false")
    style_ids = params.get("style_ids") or None
    if style_ids is not None and not (
        isinstance(style_ids, list)
        and all(isinstance(s, int) and not isinstance(s, bool) for s in style_ids)
    ):
        raise ValueError("style_ids must be a list of integers")
    rows = repository.list_replayable_runs(
        style_ids=style_ids,
        since=_date(params.get("since"), "since"),
        until=_date(params.get("until"), "until"),
    )
    runs = [
        {
            "run_id": str(row["run_id"]),
            "s3_key": str(row["raw_s3_key"]),
            "observed_at": as_utc_datetime(row["started_at"]).isoformat(),
            "status": str(row["status"]),
            "style_id": row["style_id"],
            "period_end": _iso(row["period_end"]),
        }
        for row in rows
    ]
    log_event("INFO", "backfill_planned", dry_run=dry_run, count=len(runs))
    return {"dry_run": dry_run, "runs": runs}


def replay(
    run: Mapping[str, Any], *, dry_run: bool, repository: Any, storage: Any
) -> dict[str, Any]:
    started = time.perf_counter()
    report = screen_run(
        storage.read_releases(run["s3_key"]),
        run_id=run["run_id"],
        storage=storage,
        write=not dry_run,
        correlation_id=run["run_id"],
    )
    bundle = normalize_tracks(report.valid)
    result = Canonicalizer(repository, dry_run=dry_run).process_run(
        run_id=run["run_id"], bundle=bundle, observed_at=as_utc_datetime(run["observed_at"])
    )
    if not dry_run:
        # A replay recovers a run that never completed; completed runs keep their history.
        if run["status"] != RunStatus.COMPLETED.value:
            repository.set_run_completed(
                run_id=run["run_id"],
                processed_count=result.tracks_processed,
                finished_at=utc_now(),
            )
        if result.tracks_created:
            _enqueue_spotify_search_after_canonicalization(
                settings=get_worker_settings(), correlation_id=run["run_id"]
            )
    out = {
        "run_id": run["run_id"],
        "style_id": run.get("style_id"),
        "period_end": run.get("period_end"),
        "dry_run": dry_run,
        **{f: getattr(result, f) for f in COUNT_FIELDS},
        "track_field_changes": dict(result.track_field_changes),
        "records_quarantined": len(report.quarantined),
        "drift_fields": list(report.drift_fields),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    log_event(
        "INFO",
        "backfill_run_replayed",
        run_id=run["run_id"],
        dry_run=dry_run,
        tracks_total=result.tracks_total,
        tracks_created=result.tracks_created,
        tracks_changed=result.tracks_changed,
        tracks_stale=result.tracks_stale,
        duration_ms=out["duration_ms"],
    )
    return out


def summarize(results: Sequence[Mapping[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    field_changes: Counter[str] = Counter()
    failed: list[str] = []
    drift: set[str] = set()
    for item in results:
        if item.get("failed"):
            failed.append(str(item.get("run_id")))
            continue
        totals.update({f: int(item.get(f) or 0) for f in COUNT_FIELDS})
        totals["records_quarantined"] += int(item.get("records_quarantined") or 0)
        field_changes.update(item.get("track_field_changes") or {})
        drift.update(item.get("drift_fields") or [])
    summary = {
        "dry_run": dry_run,
        "runs": len(results),
        "runs_failed": len(failed),
        "failed_run_ids": failed[:20],
        **{f: totals[f] for f in COUNT_FIELDS},
        "track_field_changes": dict(field_changes),
        "records_quarantined": totals["records_quarantined"],
        "drift_fields": sorted(drift),
    }
    log_event(
        "INFO",
        "backfill_summary",
        dry_run=dry_run,
        count=len(results),
        runs_failed=len(failed),
        tracks_total=totals["tracks_total"],
        tracks_created=totals["tracks_created"],
        tracks_changed=totals["tracks_changed"],
        tracks_stale=totals["tracks_stale"],
    )
    return summary


def _date(value: Any, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _repository():
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError("AURORA Data API configuration is required for backfill")
    return repository


def _storage() -> S3Storage:
    settings = get_worker_settings()
    return S3Storage(
        s3_client=create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )

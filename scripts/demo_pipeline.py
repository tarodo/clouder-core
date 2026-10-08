#!/usr/bin/env python3
"""Run the ingest pipeline on a local Postgres — no AWS account needed.

One synthetic Beatport week (plus two malformed records) goes through the
production code: contract screening, normalization, set-based canonicalization
and the nightly data-quality checks. Then the same week is replayed to show it
changes nothing. The Data API is replaced by tests/db/pg_data_api.py, which keeps
its visibility rules (ADR-0001: psycopg never enters src/collector).

    make local-db   # Postgres in Docker + migrations
    make demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "db"))
os.environ.setdefault("LOG_LEVEL", "WARNING")  # keep per-phase JSON logs out of the summary

from pg_data_api import (  # noqa: E402
    CANONICAL_TABLES,
    PgDataAPIClient,
    count_rows,
    seed_run,
    truncate_canonical,
)
from synthetic import synthetic_week  # noqa: E402

from collector.canonicalize import Canonicalizer  # noqa: E402
from collector.contracts import screen  # noqa: E402
from collector.data_quality import run_checks  # noqa: E402
from collector.models import CanonicalizationResult  # noqa: E402
from collector.normalize import normalize_tracks  # noqa: E402
from collector.repositories import ClouderRepository, utc_now  # noqa: E402

MALFORMED = [{"id": 0, "name": "no id"}, {"id": 999_999, "name": " "}]


def _ingest(repo: ClouderRepository, client: PgDataAPIClient, run_id: str,
            raw: list[dict[str, Any]]) -> tuple[dict[str, int], CanonicalizationResult]:
    seed_run(client, run_id)
    report = screen(raw)
    result = Canonicalizer(repo).process_run(run_id=run_id, bundle=normalize_tracks(report.valid))
    repo.set_run_completed(run_id=run_id, processed_count=result.tracks_processed, finished_at=utc_now())
    return {"valid": len(report.valid), "quarantined": len(report.quarantined)}, result


def run(database_url: str, tracks: int = 300) -> dict[str, Any]:
    client = PgDataAPIClient(database_url)
    try:
        truncate_canonical(client)  # refuses on a database that has users
        repo = ClouderRepository(client)
        raw = synthetic_week(tracks) + MALFORMED
        screened, first = _ingest(repo, client, "demo-week", raw)
        _, second = _ingest(repo, client, "demo-week-replay", raw)
        return {
            "screen": screened,
            "first_run": {k: getattr(first, k) for k in (
                "tracks_created", "artists_created", "albums_created", "labels_created", "styles_created")},
            "catalog": {table: count_rows(client, table) for table in CANONICAL_TABLES},
            "second_run": {k: getattr(second, k) for k in ("tracks_created", "tracks_changed", "artists_created")},
            "checks": [{"name": c.name, "value": c.value, "passed": c.passed}
                       for c in run_checks(client, date.today())],
        }
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pipeline on a local Postgres")
    parser.add_argument("--database-url", default=os.environ.get(
        "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:55433/postgres"))
    parser.add_argument("--tracks", type=int, default=300)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.database_url, args.tracks), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Count RDS Data API round-trips per canonicalization run and model their latency.

Runs the real Canonicalizer + ClouderRepository against a local Postgres through
tests/db/pg_data_api.py (a psycopg stand-in for the Data API) and counts every call
the repository makes. In production each call is an HTTPS round-trip, so
calls x per-call latency models the worker duration; local wall time is printed for
reference only.

  docker run -d --rm --name canon-pg -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
  PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/postgres \
      .venv/bin/alembic upgrade head
  PYTHONPATH=src .venv/bin/python scripts/bench_canonicalize.py \
      --database-url postgresql://postgres:postgres@localhost:55432/postgres
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "db"))
os.environ.setdefault("LOG_LEVEL", "WARNING")  # keep per-phase JSON logs out of the table

from pg_data_api import PgDataAPIClient, seed_run, truncate_canonical  # noqa: E402
from synthetic import synthetic_week  # noqa: E402

from collector.canonicalize import Canonicalizer  # noqa: E402
from collector.normalize import normalize_tracks  # noqa: E402
from collector.repositories import ClouderRepository  # noqa: E402

LATENCIES_MS = (30, 60, 100)


class CountingClient:
    """Counts each Data API call the repository makes (begin/commit are calls too)."""

    def __init__(self, inner: PgDataAPIClient) -> None:
        self._inner = inner
        self.calls: Counter[str] = Counter()

    def execute(self, sql: str, params: Any = None, transaction_id: str | None = None):
        self.calls["execute"] += 1
        return self._inner.execute(sql, params, transaction_id=transaction_id)

    def batch_execute(self, sql: str, parameter_sets: Any, transaction_id: str | None = None):
        self.calls["batch_execute"] += 1
        return self._inner.batch_execute(sql, parameter_sets, transaction_id=transaction_id)

    def begin_transaction(self) -> str:
        self.calls["begin_transaction"] += 1
        return self._inner.begin_transaction()

    def commit_transaction(self, transaction_id: str) -> None:
        self.calls["commit_transaction"] += 1
        self._inner.commit_transaction(transaction_id)

    def rollback_transaction(self, transaction_id: str) -> None:
        self.calls["rollback_transaction"] += 1
        self._inner.rollback_transaction(transaction_id)

    @contextmanager
    def transaction(self) -> Iterator[str]:
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
            self.commit_transaction(transaction_id)
        except Exception:
            self.rollback_transaction(transaction_id)
            raise


def run_once(client: PgDataAPIClient, raw: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    seed_run(client, run_id)  # FK target for source_entities; not a canonicalization call
    counting = CountingClient(client)
    bundle = normalize_tracks(raw)
    started = time.perf_counter()
    Canonicalizer(ClouderRepository(counting)).process_run(run_id=run_id, bundle=bundle)
    wall = time.perf_counter() - started
    total = sum(counting.calls.values())
    return {
        "tracks": len(bundle.tracks),
        "artists": len(bundle.artists),
        "labels": len(bundle.labels),
        "albums": len(bundle.albums),
        "calls": total,
        "calls_by_method": dict(counting.calls),
        "local_s": round(wall, 2),
        "modelled_s": {ms: round(total * ms / 1000, 1) for ms in LATENCIES_MS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=os.environ.get("TEST_DATABASE_URL"))
    parser.add_argument(
        "--tracks",
        type=int,
        nargs="+",
        default=[671, 3656],
        help="synthetic week sizes (default: prod mean and max run)",
    )
    parser.add_argument("--raw-file", type=Path, help="real releases.json.gz instead of synthetic")
    parser.add_argument("--json", type=Path, help="also write results as JSON")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or TEST_DATABASE_URL is required")

    if args.raw_file:
        datasets = [("snapshot", json.loads(gzip.decompress(args.raw_file.read_bytes())))]
    else:
        datasets = [(f"synthetic-{n}", synthetic_week(n)) for n in args.tracks]

    client = PgDataAPIClient(args.database_url)
    results: list[dict[str, Any]] = []
    try:
        for name, raw in datasets:
            truncate_canonical(client)
            for scenario in ("cold", "warm"):
                result = run_once(client, raw, run_id=f"bench-{name}-{scenario}")
                results.append({"dataset": name, "scenario": scenario, **result})
    finally:
        client.close()

    latencies = "/".join(str(ms) for ms in LATENCIES_MS)
    print(
        "| dataset | scenario | tracks | artists | labels | albums | Data API calls "
        f"| calls / 1k tracks | local s | modelled s @{latencies} ms |"
    )
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        per_1k = round(r["calls"] * 1000 / max(r["tracks"], 1))
        modelled = " / ".join(str(r["modelled_s"][ms]) for ms in LATENCIES_MS)
        print(
            f"| {r['dataset']} | {r['scenario']} | {r['tracks']} | {r['artists']} "
            f"| {r['labels']} | {r['albums']} | {r['calls']} | {per_1k} "
            f"| {r['local_s']} | {modelled} |"
        )
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

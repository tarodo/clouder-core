# Set-Based Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-entity RDS Data API round-trips in canonicalization with set-based, race-safe identity resolution and bulk writes, and document the measured before/after.

**Architecture:** Each canonicalization phase (and each 200-track chunk) resolves identities in two Data API calls: one `BatchExecuteStatement` that claims a fresh id for every external id with `ON CONFLICT DO NOTHING`, and one `IN (...)` lookup that reads the winners back. Canonical rows are then created and updated with one `BatchExecuteStatement` each. A real-Postgres harness (psycopg stand-in for the Data API, tests only) pins behaviour before and after the switch, and a benchmark counts Data API calls per run.

**Tech Stack:** Python 3.12, RDS Data API (`collector.data_api.DataAPIClient`), PostgreSQL 16 (Aurora in prod, Docker locally/CI), pytest, psycopg 3 (tests and benchmark only), GitHub Actions.

**Spec:** inline, see the "Spec" section below (source: hiring audit §15.3 "A", kept outside the repo).

## Global Constraints

- Runtime DB access only through the RDS Data API; `psycopg` may be imported only under `tests/db/` and `scripts/` — never from `src/collector/` (ADR-0001).
- The Data API cannot bind arrays (Python lists are sent as JSON), so list lookups use generated `:id0, :id1, …` placeholders — the pattern already used in `src/collector/curation/playlists_repository.py`.
- Every statement issued inside a transaction passes `transaction_id` (Data API calls without it run on another connection and cannot see uncommitted writes).
- Track chunk size stays 200; identity lookups are chunked at 500 ids per statement.
- Identity semantics are unchanged: new identities get `match_type='auto_create'`, `confidence=0.600`; canonicalization never rewrites an existing identity row.
- `log_event` keeps only fields in `ALLOWED_LOG_FIELDS` (`run_id`, `phase`, `item_count`, `duration_ms`, `chunk_*` are already allowed).
- No schema migrations.
- Branch `perf/set-based-canonicalization` from `origin/main`. Commits: Conventional Commits generated with `caveman:caveman-commit`, multi-line bodies via heredoc, author `tarodo`, no AI attribution.
- In a git worktree `.venv` lives at the main repo root: use `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/...` (written as `$VENV/...` below).

## Spec

**Problem.** `Canonicalizer` resolves every label, style, artist, album and track individually: `find_identity` (1 call) plus `create_*` or `conservative_update_track` (1 call) per entity, each an HTTPS round-trip to the Data API. A run is therefore *O(entities)* sequential calls. Production (CloudWatch `AWS/Lambda Duration`, `clouder-prod-canonicalization-worker`, 120 days to 2026-10-07, n=130, 1024 MB, timeout 900 s): **p50 104 s, p90 248 s, p99 342 s, max 360 s**. `ingest_runs` (2026-10-06): avg 671 tracks per run, max 3,656; median ingest→canonical 168 s.

A second, latent issue: new identities are written at the end of each phase with `ON CONFLICT … DO UPDATE SET clouder_id = EXCLUDED.clouder_id`. Two runs ingesting different styles in parallel that share an artist both miss the lookup, both create a canonical row, and the later commit repoints the identity — leaving an orphaned duplicate.

**Goals.**
1. Data API calls per run no longer scale with entity count: a constant number of calls per phase and per 200-track chunk.
2. Identical canonical output to the current implementation for cold runs, warm re-runs and conservative updates.
3. Race-safe identity resolution: a run that loses a claim reuses the winner's `clouder_id` and creates no canonical row for it.
4. A documented, reproducible before/after: benchmark (call counts, modelled latency) and production (worker duration percentiles), plus why and what it buys — in `docs/benchmarks/canonicalization.md` and ADR-0022.

**Non-goals.** Step Functions, data-quality checks, bulk load via `aws_s3`, changing chunk sizes, updating `last_seen_at` on existing identities, schema changes, a feature flag (rollback = revert the PR; no data migration is involved).

**Success criteria.** Benchmark shows ≥10× fewer Data API calls on both cold and warm runs; real-Postgres characterization tests pass unchanged before and after; the concurrency test fails on the old code and passes on the new; production p50 worker duration drops (measured on the first ≥3 weekly runs after deploy).

## Review Focus

1. **Two runs sharing an entity concurrently** (two styles, same artist) → one canonical row; both runs link to the same `clouder_id`. Pinned by `test_concurrent_run_reuses_identity_claimed_first` (Task 4).
2. **A phase with more than 500 entities** (lookup chunking) → every entity resolved. Pinned by the 1,200-track characterization run (Task 1, re-run in Task 4) and `test_find_identities_chunks_in_list_by_500` (Task 3).
3. **Empty phases** (tracks without release/genre/artists) → no claim/lookup/create calls with empty parameter sets. Pinned by `test_empty_phases_make_no_identity_calls` (Task 4).
4. **NULLs inside batched parameter sets** (conservative update with `bpm=None`, `mix_name=None`) → same results as the single-row SQL. Pinned by `test_batch_conservative_update_keeps_existing_values_on_null` (Task 3).
5. **A failure in the middle of a phase** → the failed chunk's identity claims and canonical rows roll back together; earlier chunks stay committed. Pinned by `test_failed_chunk_rolls_back_its_identity_claims` (Task 4).

---

### Task 0: Branch

**Files:** none (git only)

- [ ] **Step 1: Create the branch in a worktree from `origin/main`**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git fetch origin
git worktree add -b perf/set-based-canonicalization ../clouder-core-set-based origin/main
cp docs/superpowers/plans/2026-10-07-set-based-canonicalization.md ../clouder-core-set-based/docs/superpowers/plans/
cd ../clouder-core-set-based
export VENV=/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin
```

- [ ] **Step 2: Start a throwaway Postgres with the full schema**

```bash
docker run -d --rm --name canon-pg -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
until docker exec canon-pg pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/postgres $VENV/alembic upgrade head
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres
```

Expected: alembic ends at `20261004_33`.

- [ ] **Step 3: Commit the plan**

```bash
git add docs/superpowers/plans/2026-10-07-set-based-canonicalization.md
git commit -m "docs(plans): set-based canonicalization plan"
```

---

### Task 1: Real-Postgres harness and characterization tests

Pins today's canonical output against a real database before anything changes.

**Files:**
- Create: `tests/db/pg_data_api.py`
- Create: `tests/db/synthetic.py`
- Create: `tests/db/conftest.py`
- Create: `tests/db/test_canonicalize_pg.py`
- Modify: `.github/workflows/pr.yml` (job `alembic-check`, after "Run Alembic migrations")

**Interfaces:**
- Produces: `PgDataAPIClient(dsn)` with `execute(sql, params=None, transaction_id=None) -> list[dict]`, `batch_execute(sql, parameter_sets, transaction_id=None) -> None`, `begin_transaction() -> str`, `commit_transaction(tid)`, `rollback_transaction(tid)`, `transaction()` (context manager yielding a tid), `close()`; `CANONICAL_TABLES: tuple[str, ...]`; `truncate_canonical(client) -> None`; `synthetic_week(tracks: int, *, seed: int = 42, style_id: int = 1) -> list[dict]`; pytest fixture `pg` (a truncated `PgDataAPIClient`, skips when `TEST_DATABASE_URL` is unset); helper `count_rows(client, table) -> int`.

- [ ] **Step 1: Write the Data API stand-in**

`tests/db/pg_data_api.py`:

```python
"""Real-Postgres stand-in for collector.data_api.DataAPIClient (tests and benchmarks only).

Mirrors the Data API behaviour the repository relies on:
- `:name` bind parameters (`::type` casts are left alone);
- each transaction id is its own connection, and calls without a transaction id
  run on a separate autocommit connection, so they cannot see uncommitted writes
  — the visibility rule that makes `transaction_id` mandatory inside a transaction;
- dict/list parameters are sent as JSON (Data API `typeHint=JSON`).
psycopg stays out of src/collector (ADR-0001).
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Mapping

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

CANONICAL_TABLES = (
    "identity_map",
    "source_relations",
    "source_entities",
    "clouder_track_artists",
    "clouder_tracks",
    "clouder_albums",
    "clouder_artists",
    "clouder_labels",
    "clouder_styles",
)

_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def _to_pyformat(sql: str) -> str:
    return _PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


def _adapt(params: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        key: Json(value) if isinstance(value, (dict, list)) else value
        for key, value in (params or {}).items()
    }


class PgDataAPIClient:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._autocommit = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._tx: dict[str, psycopg.Connection] = {}

    def _conn(self, transaction_id: str | None) -> psycopg.Connection:
        return self._tx[transaction_id] if transaction_id else self._autocommit

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._conn(transaction_id).cursor() as cur:
            cur.execute(_to_pyformat(sql), _adapt(params))
            return list(cur.fetchall()) if cur.description else []

    def batch_execute(
        self,
        sql: str,
        parameter_sets: Iterable[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        sets = [_adapt(params) for params in parameter_sets]
        if not sets:
            return
        with self._conn(transaction_id).cursor() as cur:
            cur.executemany(_to_pyformat(sql), sets)

    def begin_transaction(self) -> str:
        transaction_id = str(uuid.uuid4())
        self._tx[transaction_id] = psycopg.connect(self._dsn, row_factory=dict_row)
        return transaction_id

    def commit_transaction(self, transaction_id: str) -> None:
        conn = self._tx.pop(transaction_id)
        conn.commit()
        conn.close()

    def rollback_transaction(self, transaction_id: str) -> None:
        conn = self._tx.pop(transaction_id)
        conn.rollback()
        conn.close()

    @contextmanager
    def transaction(self) -> Iterator[str]:
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
            self.commit_transaction(transaction_id)
        except Exception:
            self.rollback_transaction(transaction_id)
            raise

    def close(self) -> None:
        for conn in self._tx.values():
            conn.close()
        self._tx.clear()
        self._autocommit.close()


def truncate_canonical(client: PgDataAPIClient) -> None:
    client.execute(f"TRUNCATE {', '.join(CANONICAL_TABLES)} CASCADE")


def count_rows(client: PgDataAPIClient, table: str) -> int:
    return int(client.execute(f"SELECT count(*) AS n FROM {table}")[0]["n"])
```

- [ ] **Step 2: Write the synthetic data generator**

`tests/db/synthetic.py`:

```python
"""Deterministic Beatport-shaped raw tracks for canonicalization tests and benchmarks.

Shape follows one production week of a single style: ~1.22 artists per track
(115,330 links / 94,736 tracks in the 2026-10 catalog), ~2.2 tracks per release,
an artist pool of 0.6 x tracks and a label pool of 0.15 x tracks. The ratios are
assumptions, documented in docs/benchmarks/canonicalization.md.
"""

from __future__ import annotations

import random
from typing import Any


def synthetic_week(tracks: int, *, seed: int = 42, style_id: int = 1) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    n_releases = max(1, round(tracks / 2.2))
    n_labels = max(1, round(tracks * 0.15))
    n_artists = max(2, round(tracks * 0.6))
    label_of_release = [rng.randrange(n_labels) for _ in range(n_releases)]

    raw: list[dict[str, Any]] = []
    for track_id in range(1, tracks + 1):
        release = rng.randrange(n_releases)
        label = label_of_release[release]
        artists = rng.sample(range(n_artists), 2 if rng.random() < 0.22 else 1)
        raw.append(
            {
                "id": track_id,
                "name": f"Track {track_id}",
                "mix_name": "Original Mix",
                "isrc": f"QZ{track_id:010d}",
                "bpm": rng.randint(120, 175),
                "length_ms": rng.randint(180_000, 420_000),
                "publish_date": "2026-09-26",
                "artists": [{"id": 1_000_000 + a, "name": f"Artist {a}"} for a in artists],
                "genre": {"id": style_id, "name": f"Style {style_id}"},
                "release": {
                    "id": 2_000_000 + release,
                    "name": f"Release {release}",
                    "label": {"id": 3_000_000 + label, "name": f"Label {label}"},
                },
            }
        )
    return raw
```

- [ ] **Step 3: Write the fixture**

`tests/db/conftest.py`:

```python
"""Real-Postgres fixtures. Skipped unless TEST_DATABASE_URL points at a migrated DB.

Local: docker run -d --rm --name canon-pg -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
       then `alembic upgrade head` and
       export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres
CI:    the alembic-check job provides the database.
"""

from __future__ import annotations

import os

import pytest

from pg_data_api import PgDataAPIClient, truncate_canonical


@pytest.fixture
def pg():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    client = PgDataAPIClient(dsn)
    truncate_canonical(client)
    yield client
    client.close()
```

- [ ] **Step 4: Write the characterization tests**

`tests/db/test_canonicalize_pg.py`:

```python
"""Canonical output on a real Postgres. Must pass unchanged before and after the
set-based rewrite (docs/superpowers/plans/2026-10-07-set-based-canonicalization.md)."""

from __future__ import annotations

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

from pg_data_api import CANONICAL_TABLES, count_rows
from synthetic import synthetic_week

# 1,200 tracks -> ~720 artists and ~545 albums: phases larger than one 500-id lookup.
TRACKS = 1200


def _snapshot(pg) -> dict[str, int]:
    return {table: count_rows(pg, table) for table in CANONICAL_TABLES}


def test_cold_run_creates_one_canonical_row_per_source_entity(pg) -> None:
    bundle = normalize_tracks(synthetic_week(TRACKS))

    Canonicalizer(ClouderRepository(pg)).process_run(run_id="run-cold", bundle=bundle)

    assert count_rows(pg, "clouder_tracks") == len(bundle.tracks)
    assert count_rows(pg, "clouder_artists") == len(bundle.artists)
    assert count_rows(pg, "clouder_labels") == len(bundle.labels)
    assert count_rows(pg, "clouder_albums") == len(bundle.albums)
    assert count_rows(pg, "clouder_styles") == len(bundle.styles)
    assert count_rows(pg, "identity_map") == (
        len(bundle.tracks)
        + len(bundle.artists)
        + len(bundle.labels)
        + len(bundle.albums)
        + len(bundle.styles)
    )
    assert count_rows(pg, "clouder_track_artists") == sum(
        len(track.bp_artist_ids) for track in bundle.tracks
    )


def test_warm_rerun_reuses_identities_and_applies_conservative_updates(pg) -> None:
    raw = synthetic_week(TRACKS)
    repo = ClouderRepository(pg)
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(raw))
    before = _snapshot(pg)

    raw[0]["bpm"] = 99
    Canonicalizer(repo).process_run(run_id="run-2", bundle=normalize_tracks(raw))

    assert _snapshot(pg) == before
    rows = pg.execute(
        """
        SELECT t.bpm FROM clouder_tracks t
        JOIN identity_map i ON i.clouder_id = t.id
        WHERE i.source = 'beatport' AND i.entity_type = 'track' AND i.external_id = :ext
        """,
        {"ext": str(raw[0]["id"])},
    )
    assert rows[0]["bpm"] == 99


def test_album_points_at_its_label(pg) -> None:
    raw = synthetic_week(50)
    Canonicalizer(ClouderRepository(pg)).process_run(
        run_id="run-labels", bundle=normalize_tracks(raw)
    )

    rows = pg.execute(
        """
        SELECT count(*) AS n FROM clouder_albums a
        JOIN identity_map il ON il.clouder_id = a.label_id AND il.entity_type = 'label'
        """
    )
    assert rows[0]["n"] == count_rows(pg, "clouder_albums")
```

- [ ] **Step 5: Run against the current code**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/db -q`
Expected: `3 passed` (takes a few seconds: the current code issues thousands of single-row statements).

Run without the env var: `env -u TEST_DATABASE_URL PYTHONPATH=src $VENV/python -m pytest tests/db -q`
Expected: `3 skipped`.

- [ ] **Step 6: Run the real-Postgres tests in CI**

In `.github/workflows/pr.yml`, job `alembic-check`, append after the "Run Alembic migrations" step:

```yaml
      - name: Real-Postgres tests
        env:
          PYTHONPATH: src
          TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
        run: pytest -q tests/db
```

- [ ] **Step 7: Full suite, then commit**

Run: `PYTHONPATH=src $VENV/python -m pytest -q`
Expected: all pass (`tests/db` included when `TEST_DATABASE_URL` is set).

Generate the message with `caveman:caveman-commit`, then:

```bash
git add tests/db .github/workflows/pr.yml
git commit -m "test(db): real-Postgres harness for canonicalization"
```

---

### Task 2: Benchmark harness and the "before" baseline

**Files:**
- Create: `scripts/bench_canonicalize.py`
- Create: `docs/benchmarks/canonicalization.md`
- Modify: `scripts/prod_volumes.sh` (add one section before "Database size")

**Interfaces:**
- Consumes: `PgDataAPIClient`, `truncate_canonical`, `synthetic_week` (Task 1).
- Produces: `scripts/bench_canonicalize.py [--database-url URL] [--tracks N ...] [--raw-file releases.json.gz] [--json out.json]` printing a markdown table with columns `dataset | scenario | tracks | artists | labels | albums | Data API calls | calls / 1k tracks | local s | modelled s @30/60/100 ms`.

- [ ] **Step 1: Write the benchmark**

`scripts/bench_canonicalize.py`:

```python
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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "db"))

from pg_data_api import PgDataAPIClient, truncate_canonical  # noqa: E402
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
        "--tracks", type=int, nargs="+", default=[671, 3656],
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
```

- [ ] **Step 2: Smoke-run on a tiny dataset**

Run: `PYTHONPATH=src $VENV/python scripts/bench_canonicalize.py --tracks 20`
Expected: a two-row markdown table (cold, warm) with non-zero `Data API calls`.

- [ ] **Step 3: Record the baseline on the current code**

Run: `PYTHONPATH=src $VENV/python scripts/bench_canonicalize.py --json /tmp/bench-before.json`
Expected: four rows (synthetic-671 cold/warm, synthetic-3656 cold/warm). Keep the printed table — it goes into the doc in the next step.

- [ ] **Step 4: Create the benchmark doc with the "before" section**

`docs/benchmarks/canonicalization.md` — paste the table printed in Step 3 under "Benchmark (before)" and fill the implied-latency line with `104 s ÷ <calls of synthetic-671 cold>` and `104 s ÷ <calls of synthetic-671 warm>` (milliseconds, one decimal):

```markdown
# Canonicalization: per-entity calls → set-based

Status: in progress — "after" sections are filled once the change ships.

## Why

Canonicalization turns a weekly Beatport snapshot (avg 671 tracks, max 3,656 per run)
into canonical labels, styles, artists, albums and tracks in Aurora. It resolved every
entity individually through the RDS Data API — one lookup plus one write per entity, each
an HTTPS round-trip — so run time grew linearly with entity count and was dominated by
network latency, not by Postgres work.

## Production (before)

Source: CloudWatch `AWS/Lambda Duration`, `clouder-prod-canonicalization-worker`,
120 days to 2026-10-07 (n = 130 runs, 1024 MB, timeout 900 s).

| p50 | p90 | p99 | max |
|---:|---:|---:|---:|
| 104 s | 248 s | 342 s | 360 s |

`ingest_runs` (2026-10-06): median ingest → canonical 168 s (includes the Beatport fetch
and queueing), 156 runs, avg 671 tracks, max 3,656.

## Benchmark (before)

`scripts/bench_canonicalize.py` runs the real canonicalizer against Postgres 16 through a
psycopg stand-in for the Data API and counts every Data API call. Synthetic weeks:
1.22 artists per track, ~2.2 tracks per release, artist pool 0.6 × tracks, label pool
0.15 × tracks, one style (`tests/db/synthetic.py`). "cold" = empty catalog, "warm" =
the same week re-ingested.

<paste the Step 3 table here>

Implied production latency per call: 104 s ÷ calls(synthetic-671) ≈ <cold> ms (cold) /
<warm> ms (warm) — the right order of magnitude for an HTTPS round-trip, so call count
explains the observed duration.

## How to reproduce

```bash
docker run -d --rm --name canon-pg -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/postgres \
    .venv/bin/alembic upgrade head
PYTHONPATH=src .venv/bin/python scripts/bench_canonicalize.py \
    --database-url postgresql://postgres:postgres@localhost:55432/postgres
```

Production durations: `aws cloudwatch get-metric-statistics --namespace AWS/Lambda
--metric-name Duration --dimensions Name=FunctionName,Value=clouder-prod-canonicalization-worker
--start-time <from> --end-time <to> --period <seconds> --extended-statistics p50 p90 p99
--statistics Maximum SampleCount`; per-run numbers: `scripts/prod_volumes.sh`
("Recent canonicalization runs").
```

Replace the three `<…>` markers with the measured values before committing; no marker may remain (`grep -n "<paste\|<cold>\|<warm>" docs/benchmarks/canonicalization.md` must print nothing).

- [ ] **Step 5: Add per-run durations to the volumes script**

In `scripts/prod_volumes.sh`, insert before the `q "Database size"` line:

```bash
q "Recent canonicalization runs" "
SELECT to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started, style_id, item_count AS tracks,
       round(extract(epoch FROM finished_at - started_at))                      AS ingest_to_canonical_s,
       round(extract(epoch FROM finished_at - started_at) * 1000 / nullif(item_count, 0), 1) AS s_per_1k_tracks
FROM ingest_runs WHERE status = 'COMPLETED'
ORDER BY started_at DESC LIMIT 30"
```

Run: `PSQL_URL=$TEST_DATABASE_URL scripts/prod_volumes.sh | grep -A2 "Recent canonicalization"`
Expected: the header row prints with no `FAILED:` line; then `rm -f prod_volumes_*.txt`.

- [ ] **Step 6: Commit**

Generate the message with `caveman:caveman-commit`, then:

```bash
git add scripts/bench_canonicalize.py scripts/prod_volumes.sh docs/benchmarks/canonicalization.md
git commit -m "perf(canonicalize): benchmark Data API calls, record baseline"
```

---

### Task 3: Set-based repository methods

Adds the batch API next to the old single-row methods (removed in Task 4 once nothing calls them).

**Files:**
- Modify: `src/collector/repositories.py` (dataclasses near line 78; methods after `batch_upsert_identities` ~line 476)
- Create: `tests/unit/test_repositories_set_based.py`
- Create: `tests/db/test_repositories_set_based_pg.py`

**Interfaces:**
- Consumes: `UpsertIdentityCmd`, `CreateTrackCmd`, `ConservativeUpdateTrackCmd` (existing).
- Produces (on `ClouderRepository`):
  - `CreateNamedEntityCmd(entity_id: str, name: str, normalized_name: str, at: datetime)` (frozen dataclass)
  - `CreateAlbumCmd(album_id: str, title: str, normalized_title: str, release_date: date | None, label_id: str | None, at: datetime)` (frozen dataclass)
  - `find_identities(source: str, entity_type: str, external_ids: Iterable[str], transaction_id: str | None = None) -> dict[str, str]`
  - `claim_identities(commands: list[UpsertIdentityCmd], transaction_id: str | None = None) -> None`
  - `batch_create_labels / batch_create_styles / batch_create_artists(commands: list[CreateNamedEntityCmd], transaction_id: str | None = None) -> None`
  - `batch_create_albums(commands: list[CreateAlbumCmd], transaction_id: str | None = None) -> None`
  - `batch_create_tracks(commands: list[CreateTrackCmd], transaction_id: str | None = None) -> None`
  - `batch_conservative_update_tracks(commands: list[ConservativeUpdateTrackCmd], transaction_id: str | None = None) -> None`
  - every `batch_*`/`claim_*` method makes no call for an empty list.

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_repositories_set_based.py`:

```python
"""Round-trip counts of the set-based repository API (fake Data API)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from collector.repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateNamedEntityCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
)

AT = datetime(2026, 10, 7, tzinfo=timezone.utc)


class RecordingDataAPI:
    def __init__(self) -> None:
        self.executes: list[tuple[str, dict, str | None]] = []
        self.batches: list[tuple[str, list[dict], str | None]] = []

    def execute(self, sql, params=None, transaction_id=None):
        params = dict(params or {})
        self.executes.append((sql, params, transaction_id))
        ids = [value for key, value in params.items() if key.startswith("id")]
        return [{"external_id": ext, "clouder_id": f"c-{ext}"} for ext in ids]

    def batch_execute(self, sql, parameter_sets, transaction_id=None):
        self.batches.append((sql, list(parameter_sets), transaction_id))


def _identity(ext: str) -> UpsertIdentityCmd:
    return UpsertIdentityCmd(
        source="beatport", entity_type="artist", external_id=ext,
        clouder_entity_type="artist", clouder_id=f"new-{ext}",
        match_type="auto_create", confidence=Decimal("0.600"), observed_at=AT,
    )


def _track(track_id: str) -> CreateTrackCmd:
    return CreateTrackCmd(
        track_id=track_id, title="T", normalized_title="t", mix_name=None, isrc=None,
        bpm=None, length_ms=None, key_name=None, key_camelot=None, publish_date=None,
        album_id=None, style_id=None, at=AT,
    )


def test_find_identities_chunks_in_list_by_500() -> None:
    api = RecordingDataAPI()
    ids = [str(i) for i in range(1201)]

    found = ClouderRepository(api).find_identities("beatport", "artist", ids, transaction_id="tx")

    assert len(api.executes) == 3
    assert all(len(params) <= 502 for _, params, _ in api.executes)
    assert all(tx == "tx" for _, _, tx in api.executes)
    assert found == {ext: f"c-{ext}" for ext in ids}


def test_find_identities_dedups_and_skips_empty() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    assert repo.find_identities("beatport", "artist", []) == {}
    assert api.executes == []

    repo.find_identities("beatport", "artist", ["1", "1", "2"])
    _, params, _ = api.executes[0]
    assert sorted(v for k, v in params.items() if k.startswith("id")) == ["1", "2"]


def test_claim_identities_never_overwrites_existing_rows() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    repo.claim_identities([])
    assert api.batches == []

    repo.claim_identities([_identity("1"), _identity("2")], transaction_id="tx")
    sql, sets, tx = api.batches[0]
    assert "DO NOTHING" in sql and "DO UPDATE" not in sql
    assert len(sets) == 2 and tx == "tx"


def test_batch_writes_are_one_round_trip_each() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)
    named = [CreateNamedEntityCmd(entity_id=f"e{i}", name="N", normalized_name="n", at=AT) for i in range(3)]

    repo.batch_create_labels(named, transaction_id="tx")
    repo.batch_create_styles(named, transaction_id="tx")
    repo.batch_create_artists(named, transaction_id="tx")
    repo.batch_create_albums(
        [CreateAlbumCmd(album_id="a1", title="A", normalized_title="a",
                        release_date=date(2026, 9, 26), label_id=None, at=AT)],
        transaction_id="tx",
    )
    repo.batch_create_tracks([_track("t1"), _track("t2")], transaction_id="tx")
    repo.batch_conservative_update_tracks(
        [ConservativeUpdateTrackCmd(track_id="t1", mix_name=None, isrc=None, bpm=None,
                                    length_ms=None, key_name=None, key_camelot=None,
                                    publish_date=None, album_id=None, style_id=None, at=AT)],
        transaction_id="tx",
    )

    assert [len(sets) for _, sets, _ in api.batches] == [3, 3, 3, 1, 2, 1]
    assert {tx for _, _, tx in api.batches} == {"tx"}


def test_batch_writes_skip_empty_lists() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    for method in (
        repo.batch_create_labels, repo.batch_create_styles, repo.batch_create_artists,
        repo.batch_create_albums, repo.batch_create_tracks,
        repo.batch_conservative_update_tracks,
    ):
        method([])

    assert api.batches == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_repositories_set_based.py -q`
Expected: FAIL — `ImportError: cannot import name 'CreateAlbumCmd'`.

- [ ] **Step 3: Add the dataclasses**

In `src/collector/repositories.py`, add after `class ConservativeUpdateTrackCmd` (line ~108), and add `Iterable` to the `typing` import (`from typing import Any, Iterable, Mapping`):

```python
@dataclass(frozen=True)
class CreateNamedEntityCmd:
    entity_id: str
    name: str
    normalized_name: str
    at: datetime


@dataclass(frozen=True)
class CreateAlbumCmd:
    album_id: str
    title: str
    normalized_title: str
    release_date: date | None
    label_id: str | None
    at: datetime
```

Add next to the other module-level constants (top of the file, after the imports):

```python
# ponytail: ids per `IN (...)` identity lookup. 500 rows of (external_id, clouder_id)
# stay far under the Data API 1 MB response cap; raise only with a measured reason.
_LOOKUP_CHUNK = 500
```

- [ ] **Step 4: Add the methods**

In `ClouderRepository`, right after `batch_upsert_identities`:

```python
    def find_identities(
        self,
        source: str,
        entity_type: str,
        external_ids: Iterable[str],
        transaction_id: str | None = None,
    ) -> dict[str, str]:
        """external_id -> clouder_id for every id that has an identity.

        The Data API cannot bind arrays (lists go over the wire as JSON), so this
        is an IN list of generated placeholders, chunked to keep each statement
        and response small.
        """
        unique = list(dict.fromkeys(external_ids))
        found: dict[str, str] = {}
        for start in range(0, len(unique), _LOOKUP_CHUNK):
            chunk = unique[start : start + _LOOKUP_CHUNK]
            params: dict[str, Any] = {"source": source, "entity_type": entity_type}
            params.update({f"id{i}": ext for i, ext in enumerate(chunk)})
            placeholders = ", ".join(f":id{i}" for i in range(len(chunk)))
            rows = self._data_api.execute(
                f"""
                SELECT external_id, clouder_id
                FROM identity_map
                WHERE source = :source
                  AND entity_type = :entity_type
                  AND external_id IN ({placeholders})
                """,
                params,
                transaction_id=transaction_id,
            )
            found.update({str(row["external_id"]): str(row["clouder_id"]) for row in rows})
        return found

    def claim_identities(
        self,
        commands: list[UpsertIdentityCmd],
        transaction_id: str | None = None,
    ) -> None:
        """Insert identities that do not exist yet; an existing row always wins.

        Paired with find_identities this is race-safe: if a concurrent run claimed
        the same external id first, this INSERT waits for it, does nothing, and the
        follow-up lookup returns the winner's clouder_id.
        """
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO NOTHING
            """,
            [_identity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_labels(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_styles(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_artists(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_albums(
        self, commands: list[CreateAlbumCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_albums (
                id, title, normalized_title, release_date, label_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :release_date, :label_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                {
                    "id": cmd.album_id,
                    "title": cmd.title,
                    "normalized_title": cmd.normalized_title,
                    "release_date": cmd.release_date,
                    "label_id": cmd.label_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def batch_create_tracks(
        self, commands: list[CreateTrackCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_tracks (
                id, title, normalized_title, mix_name, isrc, bpm, length_ms,
                key_name, key_camelot,
                publish_date, album_id, style_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :mix_name, :isrc, :bpm, :length_ms,
                :key_name, :key_camelot,
                :publish_date, :album_id, :style_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                {
                    "id": cmd.track_id,
                    "title": cmd.title,
                    "normalized_title": cmd.normalized_title,
                    "mix_name": cmd.mix_name,
                    "isrc": cmd.isrc,
                    "bpm": cmd.bpm,
                    "length_ms": cmd.length_ms,
                    "key_name": cmd.key_name,
                    "key_camelot": cmd.key_camelot,
                    "publish_date": cmd.publish_date,
                    "album_id": cmd.album_id,
                    "style_id": cmd.style_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def batch_conservative_update_tracks(
        self,
        commands: list[ConservativeUpdateTrackCmd],
        transaction_id: str | None = None,
    ) -> None:
        """Fill newly present values without blanking existing ones (one round-trip)."""
        if not commands:
            return
        self._data_api.batch_execute(
            """
            UPDATE clouder_tracks
            SET mix_name = COALESCE(:mix_name, mix_name),
                isrc = CASE
                    WHEN :isrc IS NULL THEN isrc
                    WHEN isrc IS NULL THEN :isrc
                    WHEN isrc <> :isrc THEN :isrc
                    ELSE isrc
                END,
                bpm = CASE
                    WHEN :bpm IS NULL THEN bpm
                    WHEN bpm IS NULL THEN :bpm
                    WHEN bpm <> :bpm THEN :bpm
                    ELSE bpm
                END,
                length_ms = CASE
                    WHEN :length_ms IS NULL THEN length_ms
                    WHEN length_ms IS NULL THEN :length_ms
                    WHEN length_ms <> :length_ms THEN :length_ms
                    ELSE length_ms
                END,
                key_name = COALESCE(:key_name, key_name),
                key_camelot = COALESCE(:key_camelot, key_camelot),
                publish_date = COALESCE(:publish_date, publish_date),
                album_id = COALESCE(:album_id, album_id),
                style_id = COALESCE(:style_id, style_id),
                updated_at = :at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "mix_name": cmd.mix_name,
                    "isrc": cmd.isrc,
                    "bpm": cmd.bpm,
                    "length_ms": cmd.length_ms,
                    "key_name": cmd.key_name,
                    "key_camelot": cmd.key_camelot,
                    "publish_date": cmd.publish_date,
                    "album_id": cmd.album_id,
                    "style_id": cmd.style_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )
```

At module level (after the `ClouderRepository` class, next to the other private helpers):

```python
def _identity_params(cmd: UpsertIdentityCmd) -> dict[str, Any]:
    return {
        "source": cmd.source,
        "entity_type": cmd.entity_type,
        "external_id": cmd.external_id,
        "clouder_entity_type": cmd.clouder_entity_type,
        "clouder_id": cmd.clouder_id,
        "match_type": cmd.match_type,
        "confidence": cmd.confidence,
        "observed_at": cmd.observed_at,
    }


def _named_entity_params(cmd: CreateNamedEntityCmd) -> dict[str, Any]:
    return {
        "id": cmd.entity_id,
        "name": cmd.name,
        "normalized_name": cmd.normalized_name,
        "at": cmd.at,
    }
```

Replace the inline param dict in `batch_upsert_identities` with `[_identity_params(cmd) for cmd in commands]` (same keys, no behaviour change).

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_repositories_set_based.py tests/unit/test_raw_sql_parses.py -q`
Expected: PASS (the raw-SQL test parses the new literal statements with the PostgreSQL grammar).

- [ ] **Step 6: Write the real-Postgres tests**

`tests/db/test_repositories_set_based_pg.py`:

```python
"""Set-based repository SQL against a real Postgres."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from collector.repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
)

AT = datetime(2026, 10, 7, tzinfo=timezone.utc)


def _identity(ext: str, clouder_id: str) -> UpsertIdentityCmd:
    return UpsertIdentityCmd(
        source="beatport", entity_type="artist", external_id=ext,
        clouder_entity_type="artist", clouder_id=clouder_id,
        match_type="auto_create", confidence=Decimal("0.600"), observed_at=AT,
    )


def test_find_identities_resolves_more_than_one_chunk(pg) -> None:
    repo = ClouderRepository(pg)
    repo.claim_identities([_identity(str(i), f"c-{i}") for i in range(1201)])

    found = repo.find_identities("beatport", "artist", [str(i) for i in range(1201)])

    assert found == {str(i): f"c-{i}" for i in range(1201)}


def test_claim_keeps_the_existing_winner(pg) -> None:
    repo = ClouderRepository(pg)
    repo.claim_identities([_identity("1", "winner")])

    repo.claim_identities([_identity("1", "loser"), _identity("2", "fresh")])

    assert repo.find_identities("beatport", "artist", ["1", "2"]) == {"1": "winner", "2": "fresh"}


def test_claims_are_invisible_outside_their_transaction_until_commit(pg) -> None:
    repo = ClouderRepository(pg)
    with pg.transaction() as tx:
        repo.claim_identities([_identity("7", "c-7")], transaction_id=tx)
        assert repo.find_identities("beatport", "artist", ["7"], transaction_id=tx) == {"7": "c-7"}
        assert repo.find_identities("beatport", "artist", ["7"]) == {}
    assert repo.find_identities("beatport", "artist", ["7"]) == {"7": "c-7"}


def test_batch_conservative_update_keeps_existing_values_on_null(pg) -> None:
    repo = ClouderRepository(pg)
    base = dict(normalized_title="t", isrc=None, length_ms=None, key_camelot=None,
                publish_date=None, album_id=None, style_id=None, at=AT)
    repo.batch_create_tracks([
        CreateTrackCmd(track_id="t1", title="T1", mix_name="Original", bpm=120, key_name=None, **base),
        CreateTrackCmd(track_id="t2", title="T2", mix_name=None, bpm=None, key_name=None, **base),
    ])
    update = dict(isrc=None, length_ms=None, key_camelot=None, publish_date=None,
                  album_id=None, style_id=None, at=AT)

    repo.batch_conservative_update_tracks([
        ConservativeUpdateTrackCmd(track_id="t1", mix_name=None, bpm=None, key_name="1A", **update),
        ConservativeUpdateTrackCmd(track_id="t2", mix_name="Dub", bpm=128, key_name=None, **update),
    ])

    rows = {r["id"]: r for r in pg.execute("SELECT id, mix_name, bpm, key_name FROM clouder_tracks")}
    assert (rows["t1"]["mix_name"], rows["t1"]["bpm"], rows["t1"]["key_name"]) == ("Original", 120, "1A")
    assert (rows["t2"]["mix_name"], rows["t2"]["bpm"], rows["t2"]["key_name"]) == ("Dub", 128, None)
```

- [ ] **Step 7: Run them**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/db/test_repositories_set_based_pg.py -q`
Expected: `4 passed`.

- [ ] **Step 8: Full suite, then commit**

Run: `PYTHONPATH=src $VENV/python -m pytest -q`
Expected: all pass.

Generate the message with `caveman:caveman-commit`, then:

```bash
git add src/collector/repositories.py tests/unit/test_repositories_set_based.py tests/db/test_repositories_set_based_pg.py
git commit -m "perf(repositories): set-based identity and entity writes"
```

---

### Task 4: Switch the canonicalizer to set-based, race-safe resolution

**Files:**
- Modify: `src/collector/canonicalize.py` (phases and resolvers; lines ~1–660)
- Modify: `src/collector/repositories.py` (delete now-unused single-row methods)
- Modify: `tests/unit/test_canonicalize.py` (`FakeRepo`, new tests)
- Modify: `tests/unit/test_canonicalize_transactions.py`
- Modify: `tests/unit/test_worker_handler.py` (`FakeRepo` canonicalization stubs, lines ~38–80)
- Create: `tests/db/test_canonicalize_concurrency_pg.py`

**Interfaces:**
- Consumes: everything Task 3 produces.
- Produces: `Canonicalizer.process_run(run_id, bundle) -> CanonicalizationResult` (unchanged signature); phase log events `canonicalization_phase_completed` now carry `duration_ms` and a `tracks` phase event is added.
- Removes from `ClouderRepository`: `find_identity`, `create_label`, `create_style`, `create_artist`, `create_album`, `create_track`, `conservative_update_track`.

- [ ] **Step 1: Write the failing real-Postgres concurrency and rollback tests**

`tests/db/test_canonicalize_concurrency_pg.py`:

```python
"""Race safety and rollback of canonicalization on a real Postgres."""

from __future__ import annotations

import os
import threading

import pytest

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

from pg_data_api import PgDataAPIClient, count_rows
from synthetic import synthetic_week


def test_concurrent_run_reuses_identity_claimed_first(pg) -> None:
    """Another run holds an uncommitted claim on one artist; this run must wait,
    then reuse that artist instead of creating a duplicate canonical row."""
    bundle = normalize_tracks(synthetic_week(50))
    artist = bundle.artists[0]
    ext = str(artist.bp_artist_id)

    holder = PgDataAPIClient(os.environ["TEST_DATABASE_URL"])
    tx = holder.begin_transaction()
    holder.execute(
        """
        INSERT INTO identity_map (
            source, entity_type, external_id, clouder_entity_type, clouder_id,
            match_type, confidence, first_seen_at, last_seen_at
        ) VALUES ('beatport', 'artist', :ext, 'artist', 'winner-artist',
                  'auto_create', 0.6, now(), now())
        """,
        {"ext": ext},
        transaction_id=tx,
    )

    errors: list[BaseException] = []

    def run() -> None:
        try:
            Canonicalizer(ClouderRepository(pg)).process_run(run_id="run-b", bundle=bundle)
        except BaseException as exc:  # surfaced in the main thread below
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(timeout=1)
    holder.execute(
        """
        INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
        VALUES ('winner-artist', :name, :normalized_name, now(), now())
        """,
        {"name": artist.name, "normalized_name": artist.normalized_name},
        transaction_id=tx,
    )
    holder.commit_transaction(tx)
    worker.join(timeout=60)
    holder.close()

    assert not worker.is_alive()
    assert errors == []
    identity = pg.execute(
        "SELECT clouder_id FROM identity_map "
        "WHERE source = 'beatport' AND entity_type = 'artist' AND external_id = :ext",
        {"ext": ext},
    )
    assert identity[0]["clouder_id"] == "winner-artist"
    assert count_rows(pg, "clouder_artists") == len(bundle.artists)
    links = pg.execute(
        "SELECT count(*) AS n FROM clouder_track_artists WHERE artist_id = 'winner-artist'"
    )
    assert links[0]["n"] == sum(1 for t in bundle.tracks if artist.bp_artist_id in t.bp_artist_ids)


def test_failed_chunk_rolls_back_its_identity_claims(pg, monkeypatch) -> None:
    bundle = normalize_tracks(synthetic_week(250))  # two track chunks: 200 + 50
    repo = ClouderRepository(pg)
    original = repo.batch_create_tracks
    calls = {"n": 0}

    def fail_second_chunk(commands, transaction_id=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        original(commands, transaction_id=transaction_id)

    monkeypatch.setattr(repo, "batch_create_tracks", fail_second_chunk)

    with pytest.raises(RuntimeError):
        Canonicalizer(repo).process_run(run_id="run-x", bundle=bundle)

    assert count_rows(pg, "clouder_tracks") == 200
    tracks_identities = pg.execute(
        "SELECT count(*) AS n FROM identity_map WHERE entity_type = 'track'"
    )
    assert tracks_identities[0]["n"] == 200
```

- [ ] **Step 2: Run them to verify they fail on the current code**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/db/test_canonicalize_concurrency_pg.py -q`
Expected: both FAIL. `test_concurrent_run_reuses_identity_claimed_first` fails on `identity[0]["clouder_id"] == "winner-artist"` (the old end-of-phase `DO UPDATE` repoints the identity to a duplicate artist). `test_failed_chunk_rolls_back_its_identity_claims` fails with `Failed: DID NOT RAISE <class 'RuntimeError'>` because the old canonicalizer never calls `batch_create_tracks`.

- [ ] **Step 3: Rewrite the canonicalizer**

Replace `src/collector/canonicalize.py` from the module docstring through the end of `_resolve_track` with the code below; keep `_payload_hash`, `_source_entity_cmd`, `_identity_cmd` and `_chunks` unchanged and add `_log_phase` after them.

```python
"""Canonicalization workflow for Beatport entities.

Identities are resolved set-based: per phase (per 200-track chunk for tracks) one
batch claims a fresh id for every external id and one IN-list lookup reads the
winners back, instead of a Data API round-trip per entity. See ADR-0022.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from .logging_utils import log_event
from .models import CanonicalizationResult, EntityType
from .normalize import NormalizedBundle
from .repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateNamedEntityCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
    UpsertSourceEntityCmd,
    UpsertSourceRelationCmd,
    UpsertTrackArtistCmd,
    parse_iso_date,
    utc_now,
)

MATCH_IDENTITY = Decimal("1.000")
MATCH_AUTO_CREATE = Decimal("0.600")
TRACK_CHUNK_SIZE = 200

# (bp id, name, normalized name, raw payload)
NamedEntity = tuple[int, str, str, Mapping[str, Any]]


class Canonicalizer:
    def __init__(self, repository: ClouderRepository) -> None:
        self._repository = repository

    def process_run(
        self, run_id: str, bundle: NormalizedBundle
    ) -> CanonicalizationResult:
        observed_at = utc_now()
        log_event(
            "INFO",
            "canonicalization_process_started",
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            styles_total=len(bundle.styles),
            albums_total=len(bundle.albums),
            relations_total=len(bundle.relations),
        )

        completed_phases: list[str] = []
        try:
            label_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="labels",
                entity_type=EntityType.LABEL.value,
                entities=[
                    (label.bp_label_id, label.name, label.normalized_name, label.payload)
                    for label in bundle.labels
                ],
                create=self._repository.batch_create_labels,
            )
            completed_phases.append("labels")
            style_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="styles",
                entity_type=EntityType.STYLE.value,
                entities=[
                    (style.bp_genre_id, style.name, style.normalized_name, style.payload)
                    for style in bundle.styles
                ],
                create=self._repository.batch_create_styles,
            )
            completed_phases.append("styles")
            artist_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="artists",
                entity_type=EntityType.ARTIST.value,
                entities=[
                    (artist.bp_artist_id, artist.name, artist.normalized_name, artist.payload)
                    for artist in bundle.artists
                ],
                create=self._repository.batch_create_artists,
            )
            completed_phases.append("artists")
            album_ids = self._process_albums(
                run_id=run_id,
                bundle=bundle,
                observed_at=observed_at,
                label_ids=label_ids,
            )
            completed_phases.append("albums")
            self._process_relations(run_id=run_id, bundle=bundle)
            completed_phases.append("relations")
            track_ids = self._process_tracks(
                run_id=run_id,
                bundle=bundle,
                observed_at=observed_at,
                artist_ids=artist_ids,
                album_ids=album_ids,
                style_ids=style_ids,
            )
            completed_phases.append("tracks")
        except Exception as exc:
            log_event(
                "ERROR",
                "canonicalization_phase_failed",
                run_id=run_id,
                completed_phases=",".join(completed_phases),
                failed_after=completed_phases[-1] if completed_phases else "none",
                error_type=exc.__class__.__name__,
            )
            raise

        result = CanonicalizationResult(
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            tracks_processed=len(track_ids),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
            styles_total=len(bundle.styles),
        )
        log_event(
            "INFO",
            "canonicalization_process_completed",
            run_id=run_id,
            tracks_total=result.tracks_total,
            tracks_processed=result.tracks_processed,
            artists_total=result.artists_total,
            labels_total=result.labels_total,
            albums_total=result.albums_total,
            styles_total=result.styles_total,
        )
        return result

    def _resolve_identities(
        self,
        entity_type: str,
        external_ids: Sequence[str],
        observed_at: datetime,
        transaction_id: str,
    ) -> tuple[dict[str, str], set[str]]:
        """Map external ids to clouder ids in two Data API calls, race-safe.

        Claim a fresh id for every external id (ON CONFLICT DO NOTHING), then read
        the winners back. Ids whose winner is our candidate are new and need a
        canonical row; the rest already existed — or were just claimed by a
        concurrent run — and must not be created again.
        """
        candidates = {ext: str(uuid4()) for ext in dict.fromkeys(external_ids)}
        self._repository.claim_identities(
            [
                _identity_cmd(
                    entity_type=entity_type,
                    external_id=ext,
                    clouder_entity_type=entity_type,
                    clouder_id=clouder_id,
                    match_type="auto_create",
                    confidence=MATCH_AUTO_CREATE,
                    observed_at=observed_at,
                )
                for ext, clouder_id in candidates.items()
            ],
            transaction_id=transaction_id,
        )
        resolved = self._repository.find_identities(
            "beatport", entity_type, list(candidates), transaction_id=transaction_id
        )
        missing = candidates.keys() - resolved.keys()
        if missing:
            raise RuntimeError(
                f"identity claim did not resolve {len(missing)} {entity_type} ids"
            )
        created = {ext for ext, clouder_id in resolved.items() if clouder_id == candidates[ext]}
        return resolved, created

    def _process_named_entities(
        self,
        *,
        run_id: str,
        observed_at: datetime,
        phase: str,
        entity_type: str,
        entities: Sequence[NamedEntity],
        create: Callable[..., None],
    ) -> dict[int, str]:
        started = time.perf_counter()
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=entity_type,
                        external_id=str(bp_id),
                        name=name,
                        normalized_name=normalized_name,
                        payload=payload,
                        observed_at=observed_at,
                    )
                    for bp_id, name, normalized_name, payload in entities
                ],
                transaction_id=transaction_id,
            )
            resolved, created = self._resolve_identities(
                entity_type,
                [str(bp_id) for bp_id, _, _, _ in entities],
                observed_at=observed_at,
                transaction_id=transaction_id,
            )
            create(
                [
                    CreateNamedEntityCmd(
                        entity_id=resolved[str(bp_id)],
                        name=name,
                        normalized_name=normalized_name,
                        at=observed_at,
                    )
                    for bp_id, name, normalized_name, _ in entities
                    if str(bp_id) in created
                ],
                transaction_id=transaction_id,
            )
        ids = {bp_id: resolved[str(bp_id)] for bp_id, _, _, _ in entities}
        _log_phase(run_id, phase, len(ids), started)
        return ids

    def _process_albums(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        label_ids: dict[int, str],
    ) -> dict[int, str]:
        started = time.perf_counter()
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=EntityType.ALBUM.value,
                        external_id=str(album.bp_release_id),
                        name=album.title,
                        normalized_name=album.normalized_title,
                        payload=album.payload,
                        observed_at=observed_at,
                    )
                    for album in bundle.albums
                ],
                transaction_id=transaction_id,
            )
            resolved, created = self._resolve_identities(
                EntityType.ALBUM.value,
                [str(album.bp_release_id) for album in bundle.albums],
                observed_at=observed_at,
                transaction_id=transaction_id,
            )
            self._repository.batch_create_albums(
                [
                    CreateAlbumCmd(
                        album_id=resolved[str(album.bp_release_id)],
                        title=album.title,
                        normalized_title=album.normalized_title,
                        release_date=parse_iso_date(album.release_date),
                        label_id=(
                            label_ids.get(album.bp_label_id)
                            if album.bp_label_id is not None
                            else None
                        ),
                        at=observed_at,
                    )
                    for album in bundle.albums
                    if str(album.bp_release_id) in created
                ],
                transaction_id=transaction_id,
            )
        album_ids = {
            album.bp_release_id: resolved[str(album.bp_release_id)]
            for album in bundle.albums
        }
        _log_phase(run_id, "albums", len(album_ids), started)
        return album_ids

    def _process_relations(self, run_id: str, bundle: NormalizedBundle) -> None:
        started = time.perf_counter()
        # Kept in a transaction for symmetry with other phases; atomicity
        # would hold without it since this is a single batch call.
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_relations(
                [
                    UpsertSourceRelationCmd(
                        source="beatport",
                        from_entity_type=relation.from_entity_type,
                        from_external_id=relation.from_external_id,
                        relation_type=relation.relation_type,
                        to_entity_type=relation.to_entity_type,
                        to_external_id=relation.to_external_id,
                        last_run_id=run_id,
                    )
                    for relation in bundle.relations
                ],
                transaction_id=transaction_id,
            )
        _log_phase(run_id, "relations", len(bundle.relations), started)

    def _process_tracks(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        artist_ids: dict[int, str],
        album_ids: dict[int, str],
        style_ids: dict[int, str],
    ) -> dict[int, str]:
        started = time.perf_counter()
        track_ids: dict[int, str] = {}
        chunk_count = (
            max(1, math.ceil(len(bundle.tracks) / TRACK_CHUNK_SIZE)) if bundle.tracks else 0
        )

        for chunk_index, chunk in enumerate(
            _chunks(bundle.tracks, TRACK_CHUNK_SIZE), start=1
        ):
            chunk_started = time.perf_counter()
            log_event(
                "INFO",
                "canonicalization_chunk_started",
                run_id=run_id,
                phase="tracks",
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                chunk_size=len(chunk),
            )
            with self._repository.transaction() as transaction_id:
                self._repository.batch_upsert_source_entities(
                    [
                        _source_entity_cmd(
                            run_id=run_id,
                            entity_type=EntityType.TRACK.value,
                            external_id=str(track.bp_track_id),
                            name=track.title,
                            normalized_name=track.normalized_title,
                            payload=track.payload,
                            observed_at=observed_at,
                        )
                        for track in chunk
                    ],
                    transaction_id=transaction_id,
                )
                resolved, created = self._resolve_identities(
                    EntityType.TRACK.value,
                    [str(track.bp_track_id) for track in chunk],
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )

                new_tracks: list[CreateTrackCmd] = []
                updates: list[ConservativeUpdateTrackCmd] = []
                track_artist_commands: set[UpsertTrackArtistCmd] = set()
                for track in chunk:
                    clouder_track_id = resolved[str(track.bp_track_id)]
                    track_ids[track.bp_track_id] = clouder_track_id
                    album_id = (
                        album_ids.get(track.bp_release_id)
                        if track.bp_release_id is not None
                        else None
                    )
                    style_id = (
                        style_ids.get(track.bp_genre_id)
                        if track.bp_genre_id is not None
                        else None
                    )
                    publish_date = parse_iso_date(track.publish_date)
                    if str(track.bp_track_id) in created:
                        new_tracks.append(
                            CreateTrackCmd(
                                track_id=clouder_track_id,
                                title=track.title,
                                normalized_title=track.normalized_title,
                                mix_name=track.mix_name,
                                isrc=track.isrc,
                                bpm=track.bpm,
                                length_ms=track.length_ms,
                                key_name=track.key_name,
                                key_camelot=track.key_camelot,
                                publish_date=publish_date,
                                album_id=album_id,
                                style_id=style_id,
                                at=observed_at,
                            )
                        )
                    else:
                        updates.append(
                            ConservativeUpdateTrackCmd(
                                track_id=clouder_track_id,
                                mix_name=track.mix_name,
                                isrc=track.isrc,
                                bpm=track.bpm,
                                length_ms=track.length_ms,
                                key_name=track.key_name,
                                key_camelot=track.key_camelot,
                                publish_date=publish_date,
                                album_id=album_id,
                                style_id=style_id,
                                at=observed_at,
                            )
                        )
                    for bp_artist_id in track.bp_artist_ids:
                        artist_id = artist_ids.get(bp_artist_id)
                        if artist_id:
                            track_artist_commands.add(
                                UpsertTrackArtistCmd(
                                    track_id=clouder_track_id,
                                    artist_id=artist_id,
                                    role="main",
                                )
                            )

                self._repository.batch_create_tracks(
                    new_tracks, transaction_id=transaction_id
                )
                self._repository.batch_conservative_update_tracks(
                    updates, transaction_id=transaction_id
                )
                self._repository.batch_upsert_track_artists(
                    list(track_artist_commands), transaction_id=transaction_id
                )

            log_event(
                "INFO",
                "canonicalization_chunk_completed",
                run_id=run_id,
                phase="tracks",
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                chunk_size=len(chunk),
                tracks_processed=len(track_ids),
                duration_ms=int((time.perf_counter() - chunk_started) * 1000),
            )

        _log_phase(run_id, "tracks", len(track_ids), started)
        return track_ids
```

Append after `_chunks`:

```python
def _log_phase(run_id: str, phase: str, item_count: int, started: float) -> None:
    log_event(
        "INFO",
        "canonicalization_phase_completed",
        run_id=run_id,
        phase=phase,
        item_count=item_count,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
```

`batch_upsert_track_artists` already returns early on an empty list, so the per-chunk `if track_artist_commands:` guard is gone; `batch_upsert_identities` is no longer called by canonicalization (identities are claimed up front).

- [ ] **Step 4: Delete the single-row methods nothing calls any more**

Confirm they are unused outside canonicalization: `grep -rn "\.find_identity(\|\.create_label(\|\.create_style(\|\.create_artist(\|\.create_album(\|\.create_track(\|\.conservative_update_track(" src scripts`
Expected: no output. Then delete `find_identity`, `create_artist`, `create_label`, `create_style`, `create_album`, `create_track` and `conservative_update_track` from `ClouderRepository` in `src/collector/repositories.py`. Keep `upsert_identity`, `batch_upsert_identities` (used by `spotify_handler.py`) and `IdentityMapEntry` (used by tests).

- [ ] **Step 5: Run the concurrency and characterization tests**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/db -q`
Expected: all pass, including the three Task 1 characterization tests unchanged.

- [ ] **Step 6: Update `tests/unit/test_canonicalize.py`**

Replace the whole `FakeRepo` class with:

```python
class FakeRepo:
    def __init__(self) -> None:
        self.identities: dict[tuple[str, str, str], IdentityMapEntry] = {}
        self.lose_claims: dict[tuple[str, str], str] = {}  # (entity_type, ext) -> winner id
        self.calls: Counter[str] = Counter()
        self.created_labels: list[str] = []
        self.created_styles: list[str] = []
        self.created_artists: list[str] = []
        self.created_albums: list[str] = []
        self.created_tracks: list[str] = []
        self.created_track_cmds: list[CreateTrackCmd] = []
        self.updated_tracks: list[str] = []
        self.track_artists: set[tuple[str, str, str]] = set()

    def batch_upsert_source_entities(self, commands, transaction_id=None) -> None:
        self.calls["batch_upsert_source_entities"] += 1

    def batch_upsert_source_relations(self, commands, transaction_id=None) -> None:
        self.calls["batch_upsert_source_relations"] += 1

    def claim_identities(self, commands, transaction_id=None) -> None:
        if not commands:
            return
        self.calls["claim_identities"] += 1
        for cmd in commands:
            key = (cmd.source, cmd.entity_type, cmd.external_id)
            winner = self.lose_claims.get((cmd.entity_type, cmd.external_id))
            if winner is not None:
                self.identities.setdefault(key, IdentityMapEntry(cmd.clouder_entity_type, winner))
            self.identities.setdefault(
                key, IdentityMapEntry(cmd.clouder_entity_type, cmd.clouder_id)
            )

    def find_identities(self, source, entity_type, external_ids, transaction_id=None):
        external_ids = list(external_ids)
        if not external_ids:
            return {}
        self.calls["find_identities"] += 1
        return {
            ext: self.identities[(source, entity_type, ext)].clouder_id
            for ext in external_ids
            if (source, entity_type, ext) in self.identities
        }

    def batch_create_labels(self, commands, transaction_id=None) -> None:
        self.created_labels.extend(cmd.entity_id for cmd in commands)

    def batch_create_styles(self, commands, transaction_id=None) -> None:
        self.created_styles.extend(cmd.entity_id for cmd in commands)

    def batch_create_artists(self, commands, transaction_id=None) -> None:
        self.created_artists.extend(cmd.entity_id for cmd in commands)

    def batch_create_albums(self, commands, transaction_id=None) -> None:
        self.created_albums.extend(cmd.album_id for cmd in commands)

    def batch_create_tracks(self, commands, transaction_id=None) -> None:
        self.created_tracks.extend(cmd.track_id for cmd in commands)
        self.created_track_cmds.extend(commands)

    def batch_conservative_update_tracks(self, commands, transaction_id=None) -> None:
        self.updated_tracks.extend(cmd.track_id for cmd in commands)

    def batch_upsert_track_artists(self, commands, transaction_id=None) -> None:
        for cmd in commands:
            self.track_artists.add((cmd.track_id, cmd.artist_id, cmd.role))

    @contextmanager
    def transaction(self):
        yield "tx"
```

Replace the import block at the top with:

```python
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import CreateTrackCmd, IdentityMapEntry
```

Keep the four existing tests unchanged and append:

```python
def test_identity_calls_scale_with_chunks_not_entities() -> None:
    repo = FakeRepo()
    raw = [
        {**_raw_track(track_id=i, artist_id=10_000 + i, artist_name=f"A{i}")[0]}
        for i in range(1, 451)
    ]

    Canonicalizer(repo).process_run(run_id="run-scale", bundle=normalize_tracks(raw))

    # labels, styles, artists, albums + 3 track chunks (200 + 200 + 50)
    assert repo.calls["claim_identities"] == 7
    assert repo.calls["find_identities"] == 7
    assert len(repo.created_tracks) == 450


def test_lost_claims_reuse_the_winner_and_create_nothing() -> None:
    repo = FakeRepo()
    repo.lose_claims[("artist", "713053")] = "artist-winner"
    repo.lose_claims[("track", "1")] = "track-winner"

    Canonicalizer(repo).process_run(run_id="run-race", bundle=normalize_tracks(_raw_track()))

    assert repo.created_artists == []
    assert repo.created_tracks == []
    assert repo.updated_tracks == ["track-winner"]
    assert ("track-winner", "artist-winner", "main") in repo.track_artists


def test_empty_phases_make_no_identity_calls() -> None:
    repo = FakeRepo()
    raw = [{"id": 1, "name": "Lonely Track", "artists": []}]

    Canonicalizer(repo).process_run(run_id="run-empty", bundle=normalize_tracks(raw))

    assert repo.calls["claim_identities"] == 1  # the single track chunk only
    assert repo.calls["find_identities"] == 1
    assert repo.created_labels == repo.created_styles == repo.created_artists == []
    assert len(repo.created_tracks) == 1
```

- [ ] **Step 7: Update `tests/unit/test_canonicalize_transactions.py`**

Replace the three tests (keep `_bundle_with_one_label` and `_full_bundle`) with:

```python
def _echo_repo() -> MagicMock:
    """MagicMock repo whose identity lookups return what was just claimed."""
    repo = MagicMock()
    repo.transaction.return_value.__enter__.return_value = "tx-1"
    claimed: dict[tuple[str, str], str] = {}

    def claim(commands, transaction_id=None):
        for cmd in commands:
            claimed.setdefault((cmd.entity_type, cmd.external_id), cmd.clouder_id)

    def find(source, entity_type, external_ids, transaction_id=None):
        return {
            ext: claimed[(entity_type, ext)]
            for ext in external_ids
            if (entity_type, ext) in claimed
        }

    repo.claim_identities.side_effect = claim
    repo.find_identities.side_effect = find
    return repo


@pytest.mark.parametrize(
    "method",
    [
        "batch_upsert_source_entities",
        "claim_identities",
        "find_identities",
        "batch_create_labels",
        "batch_create_styles",
        "batch_create_artists",
        "batch_create_albums",
        "batch_create_tracks",
        "batch_conservative_update_tracks",
        "batch_upsert_track_artists",
    ],
)
def test_every_phase_call_passes_transaction_id(method):
    repo = _echo_repo()

    Canonicalizer(repo).process_run(run_id="r", bundle=_full_bundle())

    calls = getattr(repo, method).call_args_list
    assert calls, f"{method} was never called"
    for call in calls:
        assert call.kwargs.get("transaction_id") == "tx-1", f"{method}: {call}"


def test_transaction_rolled_back_on_failure():
    repo = _echo_repo()
    txn_cm = MagicMock()
    repo.transaction.return_value = txn_cm
    txn_cm.__enter__.return_value = "tx-fail"
    repo.batch_create_labels.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        Canonicalizer(repo).process_run(run_id="r", bundle=_bundle_with_one_label())

    assert txn_cm.__exit__.called
    assert txn_cm.__exit__.call_args[0][0] is RuntimeError
```

- [ ] **Step 8: Update `tests/unit/test_worker_handler.py`**

Check nothing presets identities: `grep -n "identities\[" tests/unit/test_worker_handler.py` (expected: no output). In `FakeRepo`, replace the `find_identity`, `create_label`, `create_style`, `create_artist`, `create_album`, `create_track` and `conservative_update_track` stubs with:

```python
    def claim_identities(self, commands, transaction_id=None):
        for cmd in commands:
            self.identities.setdefault(
                (cmd.source, cmd.entity_type, cmd.external_id), cmd.clouder_id
            )

    def find_identities(self, source, entity_type, external_ids, transaction_id=None):
        return {
            ext: self.identities[(source, entity_type, ext)]
            for ext in external_ids
            if (source, entity_type, ext) in self.identities
        }

    def batch_create_labels(self, commands, transaction_id=None):
        pass

    def batch_create_styles(self, commands, transaction_id=None):
        pass

    def batch_create_artists(self, commands, transaction_id=None):
        pass

    def batch_create_albums(self, commands, transaction_id=None):
        pass

    def batch_create_tracks(self, commands, transaction_id=None):
        pass

    def batch_conservative_update_tracks(self, commands, transaction_id=None):
        pass
```

- [ ] **Step 9: Full suite**

Run: `PYTHONPATH=src $VENV/python -m pytest -q`
Expected: all pass (unit + `tests/db`).

- [ ] **Step 10: Commit**

Generate the message with `caveman:caveman-commit` (body: why — per-entity round-trips and the end-of-phase `DO UPDATE` race), then:

```bash
git add src/collector/canonicalize.py src/collector/repositories.py tests/unit/test_canonicalize.py tests/unit/test_canonicalize_transactions.py tests/unit/test_worker_handler.py tests/db/test_canonicalize_concurrency_pg.py
git commit -m "$(cat <<'EOF'
perf(canonicalize): resolve identities set-based

<body from caveman-commit>
EOF
)"
```

---

### Task 5: "After" benchmark, ADR and docs

**Files:**
- Modify: `docs/benchmarks/canonicalization.md`
- Create: `docs/adr/0022-set-based-canonicalization.md`
- Modify: `docs/adr/README.md` (index row, next free number → `0023`)
- Modify: `docs/data/canonicalization.md` (sections "Phase 2 — canonicalize" and "identity_map")
- Modify: any other doc that names the removed methods (found in Step 4)
- Modify: `graphify-out/` (regenerated)

**Interfaces:**
- Consumes: Task 2 baseline (`/tmp/bench-before.json` and the table in the doc), Task 4 code.

- [ ] **Step 1: Run the benchmark on the new code**

Run: `PYTHONPATH=src $VENV/python scripts/bench_canonicalize.py --json /tmp/bench-after.json`
Expected: four rows; `Data API calls` at least 10× lower than the "before" table for every row. If not, stop and investigate before writing docs.

- [ ] **Step 2: Fill in the benchmark doc**

In `docs/benchmarks/canonicalization.md`: change `Status:` to `shipped in PR #<n>` (number known after Task 6 Step 1 — leave `in review` until then); add a "Benchmark (after)" section with the new table; add the comparison and the "What changed" / "What it buys" sections below, computing every ratio from the two JSON files (`calls_before / calls_after`, `modelled_s` at 60 ms):

```markdown
## Benchmark (after)

<table printed in Step 1>

| dataset | scenario | calls before | calls after | reduction | modelled @60 ms before → after |
|---|---|---:|---:|---:|---:|
| synthetic-671 | cold | … | … | …× | … s → … s |
| synthetic-671 | warm | … | … | …× | … s → … s |
| synthetic-3656 | cold | … | … | …× | … s → … s |
| synthetic-3656 | warm | … | … | …× | … s → … s |

## What changed

- **Identity resolution:** per phase (per 200-track chunk for tracks) one batch claims a fresh
  id for every external id with `ON CONFLICT DO NOTHING`, and one `IN (...)` lookup reads the
  winners back. Before: one lookup per entity.
- **Writes:** canonical rows and conservative track updates go out as one
  `BatchExecuteStatement` per phase/chunk. Before: one statement per entity.
- **Race safety:** an existing identity always wins. Before, new identities were written with
  `ON CONFLICT … DO UPDATE SET clouder_id = …`, so two runs sharing an artist could repoint it
  and orphan a duplicate canonical row (`tests/db/test_canonicalize_concurrency_pg.py` fails
  on the old code).
- **Observability:** every `canonicalization_phase_completed` / `canonicalization_chunk_completed`
  log event carries `duration_ms`.

## What it buys

- **Time to catalog:** a typical weekly run is modelled to drop from ~… s to ~… s
  (production numbers below once measured).
- **Timeout headroom:** the worker runs inside a 900 s Lambda timeout. Before, the largest
  run (3,656 tracks) took 360 s — a week ~2.5× larger would have timed out. After, the same
  run is modelled at ~… s; call count grows with chunks (200 tracks), not with entities.
- **Correctness under concurrency:** weekly ingests for several styles run back to back and
  share artists and labels; duplicates from racing runs are no longer possible.
- **Less load on Aurora:** … statements per average run instead of …; Aurora Serverless v2
  scales on activity and auto-pauses when idle, so shorter runs keep it busy for less time.
  At the current volume the gain is
  latency, headroom and correctness, not cost.

## Limitations

- The benchmark uses a psycopg stand-in, not the Data API; modelled time assumes a constant
  per-call latency (30–100 ms band, calibrated against production p50 above).
- Synthetic weeks approximate production ratios; pass `--raw-file` with a real
  `releases.json.gz` for exact numbers.
```

No `…` or `<…>` may remain once Step 2 is complete except the two production rows, which Task 6 fills: `grep -n "…\|<table" docs/benchmarks/canonicalization.md` must print only lines inside "What it buys" that reference production.

- [ ] **Step 3: Write ADR-0022**

`docs/adr/0022-set-based-canonicalization.md`:

```markdown
# ADR-0022: Set-based, claim-then-read canonicalization
Status: Accepted
Date: 2026-10-07

## Context

Canonicalization resolved each Beatport label, style, artist, album and track with its own
RDS Data API round-trips (`find_identity`, then `create_*` or `conservative_update_track`).
The Data API is HTTP-based (ADR-0001), so a run cost O(entities) sequential requests:
production worker p50 104 s, max 360 s for 3,656 tracks against a 900 s Lambda timeout.
New identities were written at the end of each phase with
`ON CONFLICT … DO UPDATE SET clouder_id = EXCLUDED.clouder_id`; two runs sharing an entity
could both create a canonical row and the later commit would repoint the identity, orphaning
a duplicate.

Alternatives considered:
- **Batch the lookup only** (one `IN (...)` read, then create misses): same call count, keeps
  the race.
- **Bulk load into a staging table via `aws_s3.table_import_from_s3`, then set-based SQL**:
  fastest at 100×, but adds an extension, IAM for Aurora→S3 and a second code path; not
  needed at the current volume (`docs/benchmarks/canonicalization.md`).
- **`INSERT … RETURNING` multi-row VALUES**: one call fewer per phase, but
  `BatchExecuteStatement` returns no rows and a single statement with thousands of
  generated parameters is harder to keep under Data API limits.

## Decision

Per phase, and per 200-track chunk for tracks:
1. `claim_identities`: one `BatchExecuteStatement` inserting a fresh candidate id for every
   external id with `ON CONFLICT (source, entity_type, external_id) DO NOTHING`.
2. `find_identities`: one `IN (...)` lookup (generated placeholders, 500 ids per statement —
   the Data API cannot bind arrays) that reads the winning ids.
3. Candidates that won are new: create their canonical rows in one batch. Everything else
   already existed or was claimed by a concurrent run: tracks get one batched conservative
   update, other entity types are left untouched.

All steps share the phase's transaction (`transaction_id` on every call).

## Consequences

- Data API calls per run scale with phases and chunks, not entities (numbers in
  `docs/benchmarks/canonicalization.md`).
- An existing identity is never overwritten by canonicalization; a concurrent claim blocks
  until the other transaction ends, then reads its id. Existing identities' `last_seen_at`
  is not refreshed — unchanged from before.
- `ClouderRepository.find_identity`, `create_*` and `conservative_update_track` are gone;
  the "pass `transaction_id` to `find_identity`" gotcha now applies to `find_identities`.
  This supersedes the `find_identity` bullet in ADR-0001's consequences.
- A real-Postgres harness (`tests/db/`, psycopg stand-in for the Data API, tests only) runs
  in CI's `alembic-check` job and pins canonical output, race safety and rollback.

**Cross-references:** ADR-0001, `docs/data/canonicalization.md`,
`docs/benchmarks/canonicalization.md`.
```

Add the index row to `docs/adr/README.md` and change "The next free number is `0022`" to `0023`:

```markdown
| 0022 | [Set-based, claim-then-read canonicalization](0022-set-based-canonicalization.md) |
```

- [ ] **Step 4: Update the docs that describe the old flow**

Find every reference: `grep -rn "find_identity\b\|find_identity(\|create_label\|create_artist\|create_album\|create_track\|conservative_update_track\|_resolve_" docs src --include=*.md`
(in zsh quote the glob: `--include='*.md'`). For each hit outside `docs/archive/`, `docs/superpowers/` and `docs/adr/0001*` (ADRs are append-only):
- In `docs/data/canonicalization.md`, replace the "Each `_resolve_*` method follows the same pattern" list with:

```markdown
Each phase resolves identities set-based (ADR-0022):
1. `claim_identities` — one batch inserting a candidate UUID for every external id, `ON CONFLICT DO NOTHING`.
2. `find_identities` — one `IN (...)` lookup (500 ids per statement) returning the winning `clouder_id`s.
3. Candidates that won are new → one batch creates their canonical rows (confidence=0.600, match_type=`auto_create`). The rest already existed (or were claimed by a concurrent run) → tracks get one batched `ConservativeUpdateTrackCmd` update.
```

  and replace the identity_map "Write path"/"Read path" paragraphs with `claim_identities` / `find_identities`, keeping the "pass `transaction_id`" warning (now for `find_identities`).
- In `docs/backend/*.md`, rename `find_identity` to `find_identities` where the transaction-visibility gotcha is described.
- In `docs/backend/testing.md`, add `tests/db/` to the layout block: `db/  # Real Postgres via a psycopg stand-in for the Data API; skipped unless TEST_DATABASE_URL is set (CI: alembic-check job).`

- [ ] **Step 5: Refresh the knowledge graph**

Run: `graphify update .`
Expected: `graphify-out/` updated, including a dated backup directory.

- [ ] **Step 6: Commit docs, then graph**

Generate both messages with `caveman:caveman-commit`, then:

```bash
git add docs/benchmarks/canonicalization.md docs/adr/0022-set-based-canonicalization.md docs/adr/README.md docs/data docs/backend
git commit -m "docs(canonicalize): before/after benchmark and ADR-0022"
git add graphify-out
git commit -m "chore(graphify): refresh graph after set-based canonicalization"
```

---

### Task 6: Ship and measure in production

**Files:**
- Modify: `docs/benchmarks/canonicalization.md` (production "after" + status)

- [ ] **Step 1: Pull request**

```bash
git push -u origin perf/set-based-canonicalization
```

Generate the PR title and body with `caveman:caveman-commit` (what changed, why, how verified — no template headings), then `gh pr create --base main --head perf/set-based-canonicalization --title "<title>" --body "<body>"`. Wait for `gh pr checks <n> --watch`: `tests`, `alembic-check` (now also runs `tests/db`) must pass.

- [ ] **Step 2: Merge and wait for the deploy**

```bash
gh pr merge <n> --merge
```

Find the `Deploy` run for the merge commit (`gh run list --workflow deploy.yml --branch main -L 5`) and `gh run watch <id> --exit-status`. Expected: success.

Rollback if anything below fails: `git revert -m 1 <merge-sha>` on a new branch, PR, merge — the deploy ships the old code. No schema change is involved; raw snapshots stay in S3 and can be replayed by re-sending a `CanonicalizationMessage`.

- [ ] **Step 3: Production run (manual checkpoint — needs the owner)**

Ask the owner to run the next weekly ingest (Saturday-week 40, the usual styles) from the admin UI. Then:
- confirm every run reached `COMPLETED`: owner runs `scripts/prod_volumes.sh` and shares the "Recent canonicalization runs" section;
- read worker durations since the deploy timestamp:

```bash
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=clouder-prod-canonicalization-worker \
  --start-time <deploy-time-UTC> --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 86400 --extended-statistics p50 p90 --statistics Maximum SampleCount
```

  and errors over the same window (`--metric-name Errors --statistics Sum`, expected 0).

- [ ] **Step 4: Record production "after"**

Add to `docs/benchmarks/canonicalization.md`:

```markdown
## Production (after)

Runs since <deploy date> (n = …): p50 … s, p90 … s, max … s (before: 104 / 248 / 360 s);
… s per 1k tracks (before: … from "Recent canonicalization runs").
```

Fill the remaining production references in "What it buys", set `Status: shipped in PR #<n>`, and ship it as a docs-only PR (message and PR text via `caveman:caveman-commit`; merge after checks; deploy runs but changes nothing at runtime).

- [ ] **Step 5: Clean up**

```bash
docker stop canon-pg
cd /Users/roman/Projects/clouder-projects/clouder-core
git worktree remove ../clouder-core-set-based
git fetch --prune && git merge --ff-only origin/main
git branch -d perf/set-based-canonicalization
```

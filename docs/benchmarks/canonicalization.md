# Canonicalization: per-entity calls → set-based

Status: shipped in PR #248 (deployed 2026-10-07); production numbers from the first two runs after deploy.

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

| dataset | scenario | tracks | artists | labels | albums | Data API calls | calls / 1k tracks | local s | modelled s @30/60/100 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synthetic-671 | cold | 671 | 343 | 95 | 273 | 2805 | 4180 | 0.6 | 84.2 / 168.3 / 280.5 |
| synthetic-671 | warm | 671 | 343 | 95 | 273 | 2085 | 3107 | 0.46 | 62.5 / 125.1 / 208.5 |
| synthetic-3656 | cold | 3656 | 1937 | 509 | 1467 | 15254 | 4172 | 3.17 | 457.6 / 915.2 / 1525.4 |
| synthetic-3656 | warm | 3656 | 1937 | 509 | 1467 | 11317 | 3095 | 2.44 | 339.5 / 679.0 / 1131.7 |

Almost all of it is single-row `ExecuteStatement` calls (2,766 of 2,805 for the cold
671-track week): one identity lookup per entity plus one insert or update.

Implied production latency per call: 104 s ÷ calls(synthetic-671) ≈ 37.1 ms (cold) /
49.9 ms (warm); for the largest run, 360 s ÷ calls(synthetic-3656) ≈ 23.6 ms (cold) /
31.8 ms (warm). Tens of milliseconds is the right order for an HTTPS round-trip, so the
call count explains the observed duration — Postgres itself does this work in 0.5–3 s
locally.

## Benchmark (after)

Same harness, same synthetic weeks, set-based canonicalization (ADR-0022):

| dataset | scenario | tracks | artists | labels | albums | Data API calls | calls / 1k tracks | local s | modelled s @30/60/100 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synthetic-671 | cold | 671 | 343 | 95 | 273 | 55 | 82 | 0.21 | 1.6 / 3.3 / 5.5 |
| synthetic-671 | warm | 671 | 343 | 95 | 273 | 51 | 76 | 0.18 | 1.5 / 3.1 / 5.1 |
| synthetic-3656 | cold | 3656 | 1937 | 509 | 1467 | 166 | 45 | 0.9 | 5.0 / 10.0 / 16.6 |
| synthetic-3656 | warm | 3656 | 1937 | 509 | 1467 | 162 | 44 | 0.91 | 4.9 / 9.7 / 16.2 |

| dataset | scenario | calls before | calls after | reduction | modelled @60 ms before → after |
|---|---|---:|---:|---:|---:|
| synthetic-671 | cold | 2,805 | 55 | 51× | 168.3 s → 3.3 s |
| synthetic-671 | warm | 2,085 | 51 | 41× | 125.1 s → 3.1 s |
| synthetic-3656 | cold | 15,254 | 166 | 92× | 915.2 s → 10.0 s |
| synthetic-3656 | warm | 11,317 | 162 | 70× | 679.0 s → 9.7 s |

The average cold week now makes 8 `ExecuteStatement` + 29 `BatchExecuteStatement` calls plus
9 transactions, instead of 2,766 single-row statements. Local Postgres time also drops ~3×
(0.6 s → 0.21 s): fewer, larger statements are cheaper for the database too.

## Production (after)

Two ingests on 2026-10-07, right after the deploy; zero worker errors. Durations are
`canonicalization_process_started` → `canonicalization_process_completed` from the worker
logs; the "before" side uses the same measure over the last 30 days of logs (87 runs — log
retention is 30 days; older events carry no `duration_ms`, so they are timed by their
timestamps).

| | Before (30 days, 33 runs ≥ 500 tracks) | After (2 runs) |
|---|---:|---:|
| Seconds per 1,000 tracks | median **241 s** (213–263 s) | **14.8 s** / **9.9 s** |
| A run of ~1,250 tracks | 228–359 s for runs of 1,000–1,560 tracks (1,198 tracks: 255 s) | **18.4 s** (1,244 tracks) / **12.3 s** (1,250 tracks) |
| Lambda `Duration` (CloudWatch) | p50 104 s, max 360 s (120 days, all run sizes) | 19.5 s / 12.7 s |

**16–24× faster per track in production.** That is less than the 41–51× call reduction in the
benchmark, as the limitations below anticipate: each remaining call carries a larger batch.
Phase timings of the second run (`duration_ms` in the phase logs): labels 0.7 s, styles 0.1 s,
artists 1.6 s, albums 1.3 s, relations 3.1 s (one unchanged batch of ~4,400 rows), tracks
5.6 s (7 chunks of up to 200). The first run was slower in labels/artists, consistent with the
first invocation after the deploy.

Downstream, the Spotify ISRC search for the same tracks took 290 s and 308 s (~4 tracks/s,
93.7–98.5 % found — in line with its 30-day median of 3.5 tracks/s and 97.4 %). It searches
one track per request, so it — not canonicalization — now sets the time until a week is fully
enriched.

## Scale (after, 2026-10-08)

The same benchmark at 10× and 100× the mean (671) and largest (3,656) production week
(`scripts/bench_canonicalize.py --tracks 6710 36560 67100 365600`, local Postgres 16):

| dataset | scenario | tracks | artists | labels | albums | Data API calls | calls / 1k tracks | local s | modelled s @30/60/100 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synthetic-6710 | cold | 6710 | 3503 | 945 | 2700 | 278 | 41 | 2.39 | 8.3 / 16.7 / 27.8 |
| synthetic-6710 | warm | 6710 | 3503 | 945 | 2700 | 274 | 41 | 8.24 | 8.2 / 16.4 / 27.4 |
| synthetic-36560 | cold | 36560 | 19115 | 5081 | 14750 | 1385 | 38 | 20.51 | 41.5 / 83.1 / 138.5 |
| synthetic-36560 | warm | 36560 | 19115 | 5081 | 14750 | 1381 | 38 | 10.23 | 41.4 / 82.9 / 138.1 |
| synthetic-67100 | cold | 67100 | 34991 | 9356 | 27165 | 2520 | 38 | 23.62 | 75.6 / 151.2 / 252.0 |
| synthetic-67100 | warm | 67100 | 34991 | 9356 | 27165 | 2516 | 37 | 21.11 | 75.5 / 151.0 / 251.6 |
| synthetic-365600 | cold | 365600 | 190610 | 51121 | 147626 | 13601 | 37 | 156.6 | 408.0 / 816.1 / 1360.1 |
| synthetic-365600 | warm | 365600 | 190610 | 51121 | 147626 | 13597 | 37 | 120.51 | 407.9 / 815.8 / 1359.7 |

Calls grow linearly (~38 per 1,000 tracks) — no per-entity term left. The modelled
seconds assume small calls; production batches are large, and the measured production rate
after the change is 9.9–14.8 s per 1,000 tracks. At that rate 10× the largest week
(36,560 tracks) needs about 6–9 minutes and fits the 900 s Lambda timeout; 100× the largest
week (365,600) needs over an hour and does not — what changes there is in
[scalability notes](../scalability.md).

## What changed

- **Identity resolution:** per phase (per 200-track chunk for tracks) one batch claims a fresh
  id for every external id with `ON CONFLICT DO NOTHING`, and one `IN (...)` lookup reads the
  winners back. Before: one lookup per entity.
- **Writes:** canonical rows and conservative track updates go out as one
  `BatchExecuteStatement` per phase/chunk. Before: one statement per entity.
- **Race safety:** an existing identity always wins. Before, new identities were written with
  `ON CONFLICT … DO UPDATE SET clouder_id = …`, so two runs sharing an artist could repoint it
  and orphan a duplicate canonical row. `tests/db/test_canonicalize_concurrency_pg.py`
  reproduces this on Postgres: on the old code the identity ends up pointing at the second
  run's new UUID; on the new code it keeps the winner.
- **Latent NULL bug fixed:** the conservative update compared `:isrc`, `:bpm`, `:length_ms`
  in `CASE` branches without a type, so an untyped NULL (a track without ISRC/BPM/length)
  made Postgres deduce `text` for one branch and the column type for another and reject the
  statement. The Data API sends NULLs untyped (the Spotify updater's
  `COALESCE(:nullable_date, date_col)` only works that way), and with an untyped NULL the old
  statement fails with `could not determine data type of parameter`. It has not been observed
  in production because every track so far has an ISRC; the casts make the statement valid
  for any NULL.
- **Observability:** every `canonicalization_phase_completed` / `canonicalization_chunk_completed`
  log event carries `duration_ms`.

## What it buys

- **Time to catalog:** a ~1,250-track week now reaches the canonical catalog in 12–19 s
  instead of roughly 4–5 minutes (production numbers above).
- **Timeout headroom:** the worker runs inside a 900 s Lambda timeout. Before, the largest
  run (3,656 tracks) took 360 s, so a week ~2.5× larger would have timed out. After, the same
  run is ~166 round-trips (~10 s at 60 ms); calls grow with 200-track chunks (~45 per 1,000
  tracks), so the next limit is batch payload size, not call count.
- **Correctness under concurrency:** weekly ingests for several styles run back to back and
  share artists and labels; duplicates from racing runs are no longer possible.
- **Less load on Aurora:** 55 Data API calls per average run instead of 2,805 (18 of them
  begin/commit; inside each batch Postgres still runs one statement per parameter set, so the
  ~3× drop in local Postgres time is the honest measure of database work). Aurora Serverless
  v2 scales on activity and auto-pauses when idle, so shorter runs keep it busy for less time.
  At the current volume the gain is latency, headroom and correctness rather than cost.

## Limitations

- The benchmark uses a psycopg stand-in, not the Data API; modelled time assumes a constant
  per-call latency (30–100 ms band, calibrated against production p50 above). Larger batch
  payloads cost more server time than a single-row call, so production will not shrink by the
  full call ratio — the production section is the real measure.
- Synthetic weeks approximate production ratios; pass `--raw-file` with a real
  `releases.json.gz` for exact numbers.

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

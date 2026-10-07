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

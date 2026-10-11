# Engineering highlights

Where to look first in the code, and why each piece is there. Every entry links the
implementation and the document that measured or decided it.

1. **Set-based canonicalization** — [`src/collector/canonicalize.py`](../src/collector/canonicalize.py).
   Resolves identities and upserts a whole week in a handful of batched Data API calls instead
   of two calls per entity: 41–92× fewer round-trips, 16–24× faster per track in production.
   [Benchmark](benchmarks/canonicalization.md), [ADR-0022](adr/0022-set-based-canonicalization.md).

2. **Replay-safe writes** — `read_track_state` in [`src/collector/repositories/catalog_writes.py`](../src/collector/repositories/catalog_writes.py).
   Writes carry the observation time; an older observation never overwrites a newer one, so
   any stored raw run can be replayed — dry run first — and a second replay changes nothing.
   [Backfill](ops/backfill.md), [ADR-0024](adr/0024-replayable-canonicalization-backfill.md).

3. **Data contract with quarantine** — `screen` / `screen_run` in [`src/collector/contracts.py`](../src/collector/contracts.py).
   The contract is data (fields, JSON types, NULL limits); bad records go to S3 quarantine with
   reasons, drift becomes a log metric and an alarm.
   [Contracts](data/contracts.md), [ADR-0026](adr/0026-raw-data-contract.md).

4. **Data-quality checks as plain SQL** — `CHECKS` / `run_checks` in [`src/collector/data_quality.py`](../src/collector/data_quality.py).
   Eleven read-only checks with SLOs, each tested against Postgres with its false-alarm cases
   ([`tests/db/test_data_quality_pg.py`](../tests/db/test_data_quality_pg.py)).
   [Data quality](data/data-quality.md), [ADR-0023](adr/0023-sql-data-quality-checks.md).

5. **Scheduled ingest without stored tokens** — [`auto_ingest_plan.py`](../src/collector/auto_ingest_plan.py)
   (due week first, then even backfill), [`auto_ingest_schedule.py`](../src/collector/auto_ingest_schedule.py)
   (one-time EventBridge schedules) and `acquire_lease` in
   [`auto_ingest_repository.py`](../src/collector/auto_ingest_repository.py) (one run at a time
   without reserved concurrency). [Auto-ingest](data/auto-ingest.md), [ADR-0027](adr/0027-auto-ingest.md).

6. **Measured entity resolution** — [`src/collector/vendor_match/scorer.py`](../src/collector/vendor_match/scorer.py)
   and the evaluator [`scripts/eval_vendor_match.py`](../scripts/eval_vendor_match.py): precision
   per threshold against human decisions and a labelled sample, with an error-cost model.
   [Entity resolution](data/entity-resolution.md).

7. **Data API retry policy** — [`src/collector/data_api_retry.py`](../src/collector/data_api_retry.py).
   Full-jitter retries for statements, a narrower policy for commit/rollback (a retried commit
   must not run twice), and the Aurora auto-pause wake-up.
   [Data API](backend/data-api.md), [ADR-0001](adr/0001-data-api-runtime.md).

8. **Lakehouse models** — [`dbt/models/silver/events.sql`](../dbt/models/silver/events.sql)
   (incremental MERGE, deduplication of at-least-once delivery) and
   [`dbt/models/silver/dim_track_history.sql`](../dbt/models/silver/dim_track_history.sql) (SCD2),
   tested on DuckDB in CI and built on Athena nightly. [Lakehouse](data/lakehouse.md),
   [ADR-0025](adr/0025-iceberg-dbt-lakehouse.md).

9. **Two-phase deploy and guarded IAM** — [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)
   applies the migration Lambda, runs migrations, then the rest (after a measured 2 min 40 s of
   500s); [`infra/lambda_roles.tf`](../infra/lambda_roles.tf) gives each Lambda its own role,
   pinned by [`tests/unit/test_iam_per_function_infra.py`](../tests/unit/test_iam_per_function_infra.py).
   [Deploy](ops/deploy.md).

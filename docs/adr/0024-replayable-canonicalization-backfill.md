# ADR-0024: Replayable canonicalization and a Step Functions backfill
Status: Accepted
Date: 2026-10-07

## Context

The raw zone keeps every ingested Beatport week (154 style × week objects), but replaying one
was unsafe: source rows were stamped with the processing time, the source upsert overwrote
unconditionally, and the track update overwrote any field the replayed payload carried. A
replay of an older run reverted newer values and rewrote `updated_at` on every track. New
canonicalization logic reached history through SQL copies of the parser in migrations
(`20260531_30`) or through re-ingests from Beatport, which need a user's token per style × week.
Nothing showed what a reprocessing would change.

Measured: failed runs already recover through the SQS retry (5 transient failures in 30 days,
0 permanent), and the slowest ingest download took 16 s of the 29 s API Gateway limit.

Options for reprocessing:
- **Re-ingest from Beatport** — needs a token, re-fetches upstream, mixes logic and data changes.
- **SQL backfills in migrations** — a second implementation of the parser per change.
- **Replay the raw zone through the canonicalizer** — one implementation; needs replay-safe writes.

Options for orchestration:
- **A local script** — no history, no retries, runs on a laptop with production credentials.
- **SQS fan-out** — retries, but no single view of a backfill, no end state, no concurrency bound
  beyond the consumer's.
- **Step Functions** — a bounded, inspectable batch: per-item retries and catch, a concurrency
  limit, a final state, and the execution history.

## Decision

Replay the raw zone through the canonicalizer, with:

1. **Event time.** The observation time is `ingest_runs.started_at`; source and identity rows
   carry it, canonical rows' audit columns keep the processing time.
2. **Guarded source upsert.** Update only when the stored row is from the same run or not newer.
   The same-run exception lets a replay of the latest data apply new logic even over rows stamped
   with a later processing time.
3. **Stale observations fill gaps only.** A newer stored observation from another run makes this
   run stale for the track; its values fill NULLs and overwrite nothing.
4. **Changed rows only.** Tracks are read after the source upsert (which locks their source
   rows), changes are computed in Python, and only changed tracks are updated. Every run returns
   created / changed / stale counts and changes per field.
5. **Dry run.** The same code against a read-only repository view that drops every write.
6. **Step Functions backfill.** A STANDARD state machine: Plan (latest run per raw object) →
   Map over runs (MaxConcurrency 2, retries, failures caught) → Summarize → on apply, the
   data-quality Lambda as a post-check. One task Lambda with its own least-privilege role.

Ingest is not orchestrated by Step Functions: the execution history keeps every state's input
for 90 days, and the Beatport token must never be persisted. Ingest stays synchronous in the API
Lambda; with a 16 s maximum against 29 s there is no timeout to engineer around.

## Consequences

- Replays are idempotent and order-independent for the same set of runs (tested on Postgres).
  Known limit: if the newest observation drops a value, an out-of-order replay of an older run
  can restore it; per-field observation times would close this.
- `updated_at` on tracks now means "changed"; it no longer moves on every ingest.
- One extra Data API read per 200-track chunk; a dry run reads as much as an apply.
- The data-quality step reports, it does not roll back; the dry run is the gate before writing.
- No `canonicalizer_version` column yet: a full replay is one execution. Revisit when replays
  get expensive enough to want selective ones.

**Cross-references:** ADR-0001, ADR-0022, ADR-0023, `docs/ops/backfill.md`,
`docs/data/canonicalization.md`.

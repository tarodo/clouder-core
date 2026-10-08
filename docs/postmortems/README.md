# Postmortems

Blameless write-ups of what went wrong, why the tests did not catch it, and what now stops it from happening again. Each one has the same parts: summary, impact, timeline, root cause, fix, detection gap, follow-ups. Times are commit times (UTC+4) unless stated.

| Date | Incident | Lesson |
|---|---|---|
| 2026-04-15 | [Lookups outside the transaction could duplicate canonical rows](2026-04-15-identity-lookup-outside-transaction.md) (caught before merge) | A test double without the real visibility rules hides transaction bugs |
| 2026-09-20 | [API code shipped before its migration: `GET /styles` returned 500 for 2 min 40 s](2026-09-20-deploy-before-migration.md) | Ordering that matters must be enforced by the pipeline, not by memory |
| 2026-10-07 | [Data API rejected a 4 MiB batch during the first backfill (HTTP 413)](2026-10-07-data-api-413.md) | Production-sized inputs find limits that fixtures never reach |
| 2026-10-07 | [Backfill never converged on tracks merged by ISRC](2026-10-07-backfill-merged-tracks.md) | A replay must be idempotent across every source of a row, not per source |
| 2026-10-08 | [Artist enricher logs dropped for months under the shared role](2026-10-08-artist-enricher-logs-dropped.md) | Hand-kept allow-lists drift; tie permissions to the resource that needs them |

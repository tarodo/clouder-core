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
- The batched conservative update casts its `CASE` parameters (`isrc`, `bpm`, `length_ms`) to their column types: an untyped NULL made `:p IS NULL` and `col <> :p` deduce different types and fail the statement.
- A real-Postgres harness (`tests/db/`, psycopg stand-in for the Data API, tests only) runs
  in CI's `alembic-check` job and pins canonical output, race safety and rollback.

**Cross-references:** ADR-0001, `docs/data/canonicalization.md`,
`docs/benchmarks/canonicalization.md`.

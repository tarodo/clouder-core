# 2026-04-15 — Identity lookups ran outside the transaction (near miss)

## Summary

Canonicalization phases were wrapped in RDS Data API transactions, but the identity lookup (`find_identity`) inside them was called without the `transaction_id`. The Data API runs such a call outside the transaction, so it cannot see identities the same phase has just written. A Beatport id seen twice in one phase would look new the second time and get a second canonical row. The bug was found on the branch five minutes after it was written and never reached production.

## Impact

None recorded: no duplicate rows, no data fix. The risk was duplicate canonical tracks, artists, albums, labels or styles whenever a bundle repeated an entity within one phase.

## Timeline (UTC+4)

- 08:56 — `4f36b17` wraps every canonicalization phase in a Data API transaction; the five `_resolve_*` helpers still call `find_identity` without the transaction id.
- 09:01 — `bec0b5b` passes `transaction_id` through `find_identity` and parametrizes a phase-transaction test over all entity phases.
- 09:31 — the branch is merged (`036f470`).

## Root cause

Data API visibility: every statement without `transactionId` runs on its own autocommit connection. The rule "inside `transaction()` every call passes the transaction id" was implicit, and the unit tests used in-memory fakes with one shared view of the data, where a call without the id still saw uncommitted writes.

## Fix

`bec0b5b`: `find_identity` takes and forwards `transaction_id`; the canonicalizer passes it in every phase; a log event marks a phase that fails after earlier phases committed.

## Detection gap

The fakes had no transaction semantics. Only reading the diff caught it.

## Follow-ups

- Done (`ce84933`, 2026-10-07): a real-Postgres test harness (`tests/db/pg_data_api.py`) where each transaction id is its own connection and calls without one run on a separate autocommit connection — the same visibility rule as the Data API, so this class of bug now fails a test.
- Done (`992d237`, 2026-10-07, [ADR-0022](../adr/0022-set-based-canonicalization.md)): set-based canonicalization replaced per-row lookups with `claim_identities` (`ON CONFLICT DO NOTHING`) plus `find_identities`, both inside the transaction; a concurrency test in `tests/db` proves two runs cannot orphan a duplicate.
- Done: the rule is written down in [`docs/backend/data-api.md`](../backend/data-api.md).

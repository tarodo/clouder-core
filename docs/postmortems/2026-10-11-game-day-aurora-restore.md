# 2026-10-11 — Game day: Aurora point-in-time restore

A planned drill, not an incident. Times are UTC.

## Goal

Run the documented recovery for "Aurora data lost or corrupted" — a point-in-time restore into a new cluster — once, measure how long it takes and how much data it would lose, and check that the copy is complete. Until now the failure-modes table said "not rehearsed yet" and the RTO was an estimate.

## Setup

- Source: `clouder-prod-aurora`, Aurora PostgreSQL 16 Serverless v2 (0–2 ACU, auto-pause), 7-day point-in-time recovery; about 143k canonical tracks and 388k identity-map rows.
- Tool: `scripts/restore_drill.py` — `restore` (latest restorable time → `clouder-prod-aurora-drill` in the production subnets and security group, a writer, the RDS-managed master secret and the Data API), `verify` (row counts and newest timestamps of seven tables on both clusters, through the Data API), `teardown` (deletes only a `*-drill` cluster).
- Production kept serving throughout; nothing was repointed.

## Timeline

- 13:33:08 — restore requested; latest restorable time 13:29:53.
- 13:42:16 — drill cluster available (9 min 8 s).
- 13:48:21 — writer instance available (+6 min 5 s).
- 13:49:54 — managed master secret and Data API ready (+1 min 33 s). **RTO to a queryable copy: 16 min 46 s.**
- 15:50 — `verify` by the owner. Both clusters had paused; the Data API answered after about 30 s of `DatabaseResumingException` retries.
- 15:51 — `teardown` started (writer, then cluster, no final snapshot).

## Result

| Table | Production rows | Restored rows | Newest timestamp gap |
|---|---:|---:|---:|
| `clouder_tracks` | 143,048 | 143,048 | 0 s |
| `clouder_artists` | 46,419 | 46,419 | 0 s |
| `identity_map` | 388,092 | 388,092 | 0 s |
| `ingest_runs` | 210 | 210 | 0 s |
| `users` | 2 | 2 | 0 s |
| `categories` | 26 | 26 | 0 s |
| `playlists` | 36 | 36 | 0 s |

**RPO 3 min 14 s**: the gap between the request and the latest restorable time. Nothing had been written to these tables after the restore point (the newest row on the copy is from 05:03), so the copy was identical.

## What surprised us

- **The restore call cannot turn on the managed secret or the Data API** in the CLI used here, so they are two separate calls after the writer exists — 1.5 minutes of the RTO.
- **The writer is a separate step of about six minutes** after the cluster becomes available; together the two are most of the RTO.
- **A paused cluster answers after about 30 seconds.** With `min_acu = 0` the first request after a quiet period waits for the resume (ADR-0014); in an incident that adds to the RTO for the first request, and the Data API retry absorbs it.

## Not rehearsed

The **repoint** — making production use the restored data — was not run. The plan, in [`docs/ops/aurora.md`](../ops/aurora.md#data-protection): rename the damaged cluster and its writer out of the way, restore under the production identifiers, and let the next deploy pick up the new master secret. Until it is rehearsed, the full RTO is "16–17 minutes plus the repoint and one deploy".

## Follow-ups

- Rehearse the repoint on a copy (a second drill that renames the drill cluster instead of production).
- Measure whether creating the writer while the cluster is still `creating` is accepted; if so the RTO drops by most of the six minutes.

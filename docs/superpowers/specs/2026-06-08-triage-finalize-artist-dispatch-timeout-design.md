# Triage-finalize artist auto-dispatch timeout — design

**Date:** 2026-06-08
**Status:** Approved (approach), pending implementation plan
**Area:** `src/collector/curation`, `src/collector/{label,artist}_enrichment`, `infra/`

## Problem

When a user finalizes a triage week-block, the automatic enrichment **label** search
dispatches, but the **artist** search does not. Single-track curation actions dispatch
both labels and artists correctly — only the triage-block path drops artists.

## Root cause (confirmed from CloudWatch)

`_finalize_triage_block` (`curation_handler.py:1529-1530`) runs both dispatches
**inline, serially, in one API request**:

```python
try_dispatch_for_triage_block(block_id=..., user_id=...)          # labels  (line 1529)
try_dispatch_artists_for_triage_block(block_id=..., user_id=...)  # artists (line 1530)
```

Each dispatch performs **N sequential RDS Data API round-trips**:
`claim_*` (1–2 statements per id), a per-item resolve loop (`get_*_by_id`, plus
`derive_style_for_label` for labels), a per-item `attach_run` UPDATE, then a per-message
`sqs.send_message` loop.

Evidence — `/aws/lambda/beatport-prod-curation`, RequestId `e271eced`,
block `c14d9c1b` (199 promoted tracks):

```
17:29:14  triage_block_finalized   (promoted_count 199)
17:29:36  auto_enrich_dispatched   (labels — done after ~22s)
          END
          REPORT  Duration: 30000.00 ms  Status: timeout      ← Lambda killed at 30s
```

There is **no** `auto_enrich_artists_dispatched` and **no**
`auto_enrich_artists_dispatch_error`. The label pass alone consumed ~22s; the artist pass
(running **second**) was cut off by the 30s Lambda timeout. A Lambda timeout is not a
Python exception, so the `_safe` wrapper never catches it and never logs — the failure is
silent. Labels "always pass" because they run first; artists "never pass" because they run
second. Single-track curation is fast enough that both passes finish, so single-track
artist dispatch works.

Two contributing factors:
1. **Architecture:** heavy, size-proportional fan-out runs on the synchronous API path
   (API Gateway caps at 29s; Lambda at 30s).
2. **Observability:** `log_event` drops any field not in `ALLOWED_LOG_FIELDS`
   (`logging_utils.py`), so `claimed` / `skipped` / `candidate_*` / `source_hint` never
   reached the logs — which is why this failure was invisible in metrics.

## Approach (chosen: both, sequential)

### Phase 1 — Optimize the inline dispatch (ship first, unblocks prod, no new infra)

Eliminate the per-item round-trip explosion in both `label_enrichment.auto_dispatch` and
`artist_enrichment.auto_dispatch` (and the repository methods they call):

- **Resolve set-based.** Replace the per-id `get_label_by_id` / `get_artist_by_id` loop
  (and `derive_style_for_label`) with a single query that returns all `(id, name[, style])`
  for the claimed ids, using the established parametric `IN (:t0, :t1, …)` placeholder
  pattern (`repositories.py:846`, `playlists_repository.py:85`) chunked at ≤500 ids — Data
  API cannot bind arrays / `ANY()`.
- **Claim set-based.** Convert `claim_labels` / `claim_artists` from a per-id loop to
  set-based statements (reclaim UPDATE + insert-where-not-exists), preserving the existing
  race-safety semantics (`ON CONFLICT DO NOTHING`, attempt cap, stale-queued recovery) and
  `RETURNING` the claimed ids. Chunk at ≤500.
- **`attach_run` set-based.** One UPDATE with `IN (…)` instead of per-id.
- **Batch SQS.** Replace the per-message `send_message` loop with `send_message_batch`
  (≤10 entries per call). `send_message_batch` is not yet used in the codebase; introduce
  it here.

Expected effect: ~22s → ~1–2s per dispatch; both passes finish well inside 30s and the 29s
API-GW cap for realistic block sizes.

### Phase 2 — Move dispatch off the request path (durability)

Decouple the fan-out from the user-facing finalize request so block size can never time it
out, matching the stated design intent ("curation never waits"):

- New SQS queue `auto_enrich_dispatch` + DLQ (`infra/sqs.tf`), mirroring the existing
  enrichment-queue + DLQ pairs.
- `_finalize_triage_block` enqueues **one lightweight message** `{block_id, user_id}`
  (instead of calling the two dispatch functions inline) and returns immediately.
- New small worker Lambda consumes the queue and calls the (now-optimized, Phase 1)
  `try_dispatch_for_triage_block` + `try_dispatch_artists_for_triage_block`. The worker
  then enqueues per-item messages onto the existing `label_enrichment` /
  `artist_enrichment` queues exactly as today — the downstream enricher workers are
  unchanged.
- Terraform: queue, DLQ, worker Lambda, IAM (SQS consume + send to the two enrichment
  queues + Data API), event-source mapping, and `AUTO_ENRICH_DISPATCH_QUEUE_URL` wired into
  the curation Lambda (`infra/curation.tf`).

Phase 1's optimized dispatch code is reused verbatim inside the Phase 2 worker — no wasted
work.

### Observability fix (with Phase 1)

- Add `claimed`, `skipped`, `candidate_labels`, `candidate_artists`, and `source_hint` to
  `ALLOWED_LOG_FIELDS` so dispatch counts actually appear in logs.
- Emit a `*_dispatch_started` marker at the top of each dispatch so a future timeout shows
  "started without finished" rather than nothing.

## Components & data flow

```
finalize request
  └─ _finalize_triage_block
       Phase 1:  try_dispatch_for_triage_block + try_dispatch_artists_for_triage_block (inline, optimized)
       Phase 2:  enqueue {block_id,user_id} → auto_enrich_dispatch queue → return
                      │
                      ▼
                 auto-enrich-dispatch worker
                   └─ try_dispatch_for_triage_block + try_dispatch_artists_for_triage_block
                        └─ enqueue per-item → label_enrichment / artist_enrichment queues
                             └─ existing enricher workers (unchanged)
```

## Error handling

- Dispatch stays best-effort: `_safe` swallows + logs, so enrichment problems never break
  finalize (Phase 1) or block message redrive (Phase 2 — failures land in the DLQ).
- Set-based claim must preserve the current invariants: capped attempts, stale-queued
  recovery, and "skip labels/artists that already have an info row or a fresh queued row".
- SQS batch: handle `Failed` entries in the `send_message_batch` response (log + leave
  state queued for stale-recovery); never assume all-or-nothing.

## Testing strategy (TDD)

1. **Reproduce first (failing test):** a unit test over the dispatch that asserts artists
   are dispatched for a multi-item block — today's behavior under the old loops can be
   pinned via a fake Data API counting round-trips.
2. **Repository unit tests:** set-based `claim_*`, resolve, and `attach_run` return the same
   ids/rows as the per-item versions for 0/1/N ids and across chunk boundaries (>500).
3. **Dispatch unit tests:** `send_message_batch` called with correct batching (≤10),
   partial-failure handling, disabled-config short-circuit, empty-input short-circuit.
4. **Phase 2:** finalize enqueues exactly one dispatch message; worker handler invokes both
   dispatch functions and enqueues per-item messages; DLQ wiring asserted in terraform plan.
5. Full `pytest -q` green; `scripts/generate_openapi.py` only if routes change (they do not).

## Rollout

Phase 1 → deploy → verify a real triage finalize emits both `auto_enrich_dispatched` and
`auto_enrich_artists_dispatched` with non-zero `claimed`. Then Phase 2 → deploy → verify
finalize REPORT duration drops to ms and dispatch happens in the new worker's logs.

## Out of scope

- Changing the enricher workers or the vendor-search logic.
- Re-running the artists missed by the 2026-06-07 finalize — the stale-queued recovery in
  `claim_*` re-enables them on the next dispatch; a manual re-finalize or targeted backfill
  can be decided separately.

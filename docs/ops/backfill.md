# Backfill: replaying the raw zone

Status: deployed; measured on production on 2026-10-07.

## Why

Every Beatport week that was ever ingested is still in the raw zone, but nothing could safely
use it. Re-running canonicalization over a stored run reverted newer data, so new
canonicalization logic reached history only through hand-written SQL in a migration or through
a re-ingest from Beatport — which needs a user's Beatport token, one manual request per
style × week, and mixes "our logic changed" with "upstream changed". There was also no way to
see what a reprocessing would change before it changed it.

Backfill makes "run the pipeline again over what we already have" a safe, previewable,
one-command operation.

## Before (2026-10-07)

| | |
|---|---|
| Raw zone | 154 Beatport style × week objects across 11 styles, 27.0 MB gzip; S3 versioning on, 15 objects overwritten by re-ingests |
| Replaying a stored run | unsafe. Measured on the test database with the old code: replaying an older run after a newer one set a track's BPM back from 124 to the older 120, and replaying any run rewrote `updated_at` on 200 of 200 tracks it touched |
| Applying new logic to history | SQL in a migration that re-implements the parser (`20260531_30` extracts musical keys from `source_entities.payload`), or a re-ingest from Beatport |
| Preview of a reprocessing | none |
| Canonicalization failures, last 30 days | 89 runs, 5 failures — all transient (deadlocks and transaction timeouts before ADR-0022), all recovered by the SQS retry; 0 permanent |
| Ingest download time, last 30 days | median 4.8 s, p90 12.5 s, max 16.0 s against the 29 s API Gateway limit |

The last two rows set the scope: failed runs already recover on their own, and ingest is far
from its time limit, so neither recovery nor asynchronous ingest is the reason for this work —
safe, previewable reprocessing is.

## What changed

**Event time.** A run's observation time is `ingest_runs.started_at` — when Beatport was read.
Source and identity rows carry it (`first_seen_at`, `last_seen_at`); canonical rows'
`created_at`/`updated_at` stay the processing time. The live worker and the backfill use the
same rule.

**Older observations cannot overwrite newer ones.** The source upsert only updates when the
stored row is from the same run or not newer:

```sql
ON CONFLICT (source, entity_type, external_id) DO UPDATE SET ...
WHERE source_entities.last_run_id = EXCLUDED.last_run_id
   OR source_entities.last_seen_at <= EXCLUDED.last_seen_at
```

The same run always re-applies, so replaying the latest data picks up new logic even where old
rows carry a later processing-time stamp. A track whose stored observation is newer and from
another run is *stale* for this run: its values only fill columns that are still NULL. The
same holds across Beatport ids that feed one canonical track (an early ISRC heuristic merged an
EP track with the same recording on a compilation): the newest observation among them wins,
the larger id within one run. Replays of the same runs therefore converge whatever their order.

**Only real changes are written.** Inside each track chunk the canonicalizer reads the current
row (after the source upsert, which locks the source rows for the transaction), computes which
fields change, and updates only those tracks — `updated_at` now means "changed". Every run
reports what it did: entities created per type, tracks created / changed / stale, and changes
per field. The live worker logs these counts on `canonicalization_completed`.

**Dry run.** `Canonicalizer(repo, dry_run=True)` runs the same code against a read-only view of
the repository: reads pass through, every other call is dropped, no transaction is opened, and
ids without an identity are reported as "would be created". Per run, its counts match what an
apply of that run does; summed over many runs, an entity that is new to several of them is
counted once per run, while an apply creates it once.

**Backfill Lambda and state machine.** `clouder-prod-backfill` (one Lambda, three actions) and
the `clouder-prod-backfill` Step Functions state machine:

```
Plan ──▶ Replay (Map, 2 runs at a time) ──▶ Summarize ──▶ any run failed? ──yes──▶ ReplayFailed
                                                              │no
                                                         dry run? ──yes──▶ Done
                                                              │no
                                                         QualityGate (data-quality Lambda)
                                                              │
                                              failed checks? ──yes──▶ DataQualityGateFailed
                                                              │no
                                                             Done
```

- **Plan** lists the run behind each raw object — the latest one written to its key, because a
  re-ingest overwrites the object — optionally narrowed by style and by the period's end date, in
  observation order (oldest Beatport read first): replaying in that order converges in one pass,
  also over rows written before event time existed. Unknown input keys are rejected, so a
  misspelt filter cannot widen an apply to every style.
- **Replay** canonicalizes one run from S3. Lambda errors are retried; a run that still fails is
  caught and recorded, and the others continue. On apply, a run that never completed is marked
  completed and the Spotify search is enqueued when tracks were created.
- **Summarize** adds the counts up; the execution fails if any run failed, and its error cause
  lists the failed run ids.
- **QualityGate** (apply only) runs the nightly data-quality checks
  ([data-quality.md](../data/data-quality.md)) and fails the execution if one fails — including
  a check that was already red before the backfill, so look at the nightly result first. It is a
  post-check, not a rollback: the dry run is the gate before writing.

## How to run

```bash
SM=$(cd infra && terraform output -raw backfill_state_machine_arn)

# Preview everything (dry_run defaults to true)
aws stepfunctions start-execution --state-machine-arn "$SM" \
  --name "dry-$(date +%Y%m%d-%H%M)" --input '{}'

# Apply one style over a date range
aws stepfunctions start-execution --state-machine-arn "$SM" \
  --name "apply-$(date +%Y%m%d-%H%M)" \
  --input '{"dry_run": false, "style_ids": [1], "since": "2026-08-01", "until": "2026-09-30"}'

aws stepfunctions describe-execution --execution-arn <arn> \
  --query '{status: status, start: startDate, stop: stopDate, output: output}'
```

| Input | Meaning |
|---|---|
| `dry_run` | `true` (default) previews; `false` writes |
| `style_ids` | list of Beatport style ids; all styles when omitted |
| `since`, `until` | ISO dates compared with the run's period end |

The output's `summary` has `runs`, `runs_failed`, `failed_run_ids`, `tracks_total`,
`labels_created`, `styles_created`, `artists_created`, `albums_created`, `tracks_created`,
`tracks_changed`, `tracks_stale`, `track_field_changes`, `records_quarantined` and `drift_fields`
(the raw data contract, `docs/data/contracts.md`; a dry run writes no quarantine object). Per-run results are in the Replay
map's output and in the `backfill_run_replayed` log events of `/aws/lambda/clouder-prod-backfill`.
A failed execution has no output: `describe-execution` shows the error and a cause with the failed
run ids, and `aws stepfunctions get-execution-history` has each run's error.

One execution keeps every run's result in its state, which Step Functions caps at 256 KiB: about
500 runs per execution (154 today). Beyond that, split the replay by `since`/`until`; the upgrade
path is a Distributed Map that writes results to S3.

Typical uses: preview and apply a canonicalization change to all history; recover a run stuck
in `FAILED` or `RAW_SAVED` (apply with its style and week) — if it is still the latest run for its
raw object; a run whose object a later re-ingest overwrote is superseded, has no data of its own
and is closed by hand; check that production data is what the raw zone says (a dry run that
reports nothing).

The Beatport token is never part of this path: the state machine's input and every state's
input stay in the execution history for 90 days, so ingest is not orchestrated here (ADR-0024).

## After (production, 2026-10-07)

| Run | Duration | Result |
|---|---|---|
| Full dry run — 153 raw objects, 100,268 tracks | 1 min 56 s | nothing to create; 26 tracks would change (album 26, publish date 22, mix name 3, length 2, BPM 1); 373 older observations skipped |
| First full apply | 8 min 20 s | 152 of 153 runs replayed; the largest week failed with HTTP 413 — one Data API request carried all of its relations. Fixed by splitting batch requests under 4 MiB (the live worker had the same latent bug) |
| Dry run after it | 1 min 38 s | still ~26 changes, varying between passes: 25 canonical tracks are fed by two Beatport ids (the March 2026 ISRC heuristic merged an EP track with the same recording on a compilation) and alternated between the two releases. Fixed: the newest observation among a track's sources wins |
| Apply after both fixes | 7 min 56 s | 153 of 153 runs replayed; the 6 tracks the dry run predicted were corrected |
| Dry run after that | 1 min 36 s | **0 changes** — replaying all history is idempotent on production data (399 older observations skipped) |

Both applies ended `DataQualityGateFailed` on a check that was already red before them
(`styles_behind = 2`: two active styles had not ingested their last closed week) — the gate
reported it; the backfill itself completed.

## What it buys

- New canonicalization logic reaches all history with one command, after a preview, from data
  already stored — no Beatport token, no re-fetch, no SQL copy of the parser.
- Replays are idempotent and order-independent: tested on Postgres
  (`tests/db/test_canonicalize_replay_pg.py`, `tests/db/test_canonicalize_dry_run_pg.py`).
- `updated_at` moves only when a track changes, and every live run reports what it created and
  changed instead of only how many tracks it saw.
- A run that never completed can be recovered from the raw zone without a re-ingest.
- The first full replay found two production bugs that ingest alone would not show: a Data API
  request-size limit on large weeks and canonical tracks merged from two releases.

## Not done, and why

- **Ingest in Step Functions.** The execution history keeps every state's input; the Beatport
  token must never be persisted.
- **Asynchronous ingest.** The slowest download in 30 days took 16 s of the 29 s limit.
- **A `canonicalizer_version` column.** A full replay of the raw zone is a single execution
  (up to about 500 runs); selective replays by version are worth adding when replays get
  expensive.
- **Diffs of relations and track–artist links, and removal counts.** Both are append-only;
  canonicalization never deletes.
- **Known limit of gap filling.** If the newest observation drops a value an older one had, a
  replay of the older run out of order can bring the old value back. Per-field observation
  times would close it.

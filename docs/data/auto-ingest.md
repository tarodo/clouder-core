# Auto-ingest

Status: deployed disabled; enabled from the admin after the first login check. "After" is
filled from the first scheduled runs.

## Why

The catalog was filled only by hand: the owner opened the coverage page, pasted a Beatport
token and ingested one style × week at a time. A week nobody clicked never reached the
catalog, and history before the first manual ingest stayed empty. Auto-ingest keeps every
visible style current and backfills history evenly, with no token pasted by a person.

## Before

- Manual only (`POST /admin/beatport/ingest` from the coverage matrix).
- On 2026-10-07 the data-quality check `styles_behind` was 2: Funky House was missing weeks
  34–39 and Mainstage weeks 32–39 of 2026 (due week: 39).

## How it chooses

The unit is a (style, Saturday-week) pair; styles are the visible ones with a Beatport id.

- **Loaded**: a non-custom run for the pair that is `COMPLETED`, or `RAW_SAVED` started within
  the last 6 hours (canonicalization pending). ISO-week runs from March 2026 (no `week_year`)
  do not count; those weeks are re-ingested as Saturday-weeks, which is safe since
  canonicalization is replay-safe (ADR-0024).
- **Due week**: the latest Saturday-week whose Friday is at least 3 days before today (UTC), so
  Beatport has published the week's releases.
- **Stuck**: a pair whose last 3 auto-ingest attempts of the past 7 days all failed — the fetch
  failed, or the run it created later failed in canonicalization or stayed `RAW_SAVED` past
  6 hours — and that no run has completed. It is skipped and listed in the admin; a manual
  ingest from the coverage matrix clears it, and it is retried on its own once its attempts are
  a week old.
- **Choice** for a run with budget `periods_per_run` (default 3): first every style missing the
  due week; then missing, non-stuck pairs from the due week back to the backfill floor, newest
  week first, then by style — all styles descend together, week by week. When every style has
  reached the floor, only new due weeks are ingested.

Code: `src/collector/auto_ingest_plan.py` (pure), the SQL in
`src/collector/auto_ingest_repository.py` (tested against Postgres).

## Schedule

Settings live in one Aurora row (`auto_ingest_settings`) and are edited on the admin coverage
page: enabled, mode, fixed times (local to a timezone) or runs per day, periods per run,
backfill floor (default 2026-01-03, week 1 of 2026).

- A Terraform-managed EventBridge Scheduler schedule (`plan-daily`, 00:05 UTC) runs the
  planner. It deletes the pending one-time schedules (`run-*` in group
  `clouder-prod-auto-ingest`) and creates one `at(...)` schedule per run until the next
  00:05 UTC: the configured local times in **fixed** mode; N uniform random times at least
  60 minutes apart in **random** mode (when replanning mid-day, N is scaled by the share of
  the day left, rounded up). Each one deletes itself after it fires.
- Saving the settings replans at once (the API invokes the planner asynchronously).
- Disabled: the planner deletes pending runs and plans nothing.
- Runs never overlap: a run takes a 15-minute lease on the settings row and skips if another
  run holds it. There is no reserved concurrency (the account quota is 10).

## A run

1. Load settings; stop if disabled (unless started by "Run now").
2. Read the credentials from SSM and log in to Beatport (API v4 login → authorize → token,
   `src/collector/beatport_auth.py`). A failure ends the run and logs
   `auto_ingest_run_failed` with the step and HTTP status.
3. Choose the pairs; for each, call the same ingest core as the admin endpoint
   (`handler.collect_period`): fetch, raw to S3, `ingest_runs` row (`meta.trigger = "auto"`),
   enqueue canonicalization. A failing pair is recorded in `auto_ingest_attempts` and the run
   moves on. If the catalog rejects the token (401/403), the run stops with `failed_step =
   catalog_auth` and charges no pair.
4. Save `last_run` (per-pair outcome) and log `auto_ingest_run_completed` (`count`,
   `runs_failed`); a run whose every pair failed also logs `auto_ingest_run_failed`.

While it works, the run keeps a progress record in `last_run` (`in_progress`, the period being
fetched, done/total); `GET /admin/auto-ingest` reports `running` while the lease is held, and
the admin panel polls every 10 s then (and for 90 s after "Run now") to show it. A progress
record without a lease is shown as an interrupted run.

## Security

- Credentials: GitHub environment `production` secrets `BEATPORT_USERNAME` /
  `BEATPORT_PASSWORD` → deploy step → SSM SecureString `/clouder/beatport/username` and
  `/clouder/beatport/password`. The auto-ingest role may read exactly those two parameters.
  The OAuth client id is public (the JS of Beatport's API docs page) and is not in code: the
  secret `BEATPORT_CLIENT_ID` reaches the Lambda env at deploy, so a rotated id is fixed with
  a secret and a manual deploy.
- The token lives in the run's memory only: it is obtained per run, passed to the fetch, and
  never written to a log, S3, SQS, the database or a return value (CLAUDE.md #5). Login
  errors carry the step and HTTP status, never a body.
- The scheduler role may only invoke the auto-ingest function; the auto-ingest role may only
  manage schedules in its own group.

## Operating it

| Task | How |
|---|---|
| Check the login from AWS | `aws lambda invoke --function-name clouder-prod-auto-ingest --cli-binary-format raw-in-base64-out --payload '{"action":"auth_check"}' out.json && cat out.json` → `{"ok": true}` |
| Enable / change the schedule | Admin → Coverage → Auto-ingest → Save |
| Run once now | "Run now" in the admin, or the same invoke with `{"action":"run","manual":true}` |
| Disable | Switch off and Save (pending runs are deleted). Emergency stop until the next deploy: `aws lambda put-function-concurrency --function-name clouder-prod-auto-ingest --reserved-concurrent-executions 0` |
| Re-sync credentials | Update the GitHub secrets, then run the Deploy workflow by hand (`workflow_dispatch`) |
| Alarm | `clouder-prod-auto-ingest-failed` (≥ 1 failed run per day) — runbook "Auto-ingest run failed" |

End-to-end check: the nightly data-quality check `styles_behind` stays 0.

## After

Pending the first scheduled runs: runs per day, periods ingested, `styles_behind`.

## What it buys

- The catalog stays current without anyone online on Monday; freshness is enforced by the
  schedule, not by memory.
- History fills evenly across styles instead of wherever the owner last clicked.
- The ingest path is the one the admin uses, so a manual and an automatic run produce the same
  raw objects, runs and canonical rows.

See also [ADR-0027](../adr/0027-auto-ingest.md), [raw ingestion](raw-ingestion.md),
[data quality](data-quality.md).

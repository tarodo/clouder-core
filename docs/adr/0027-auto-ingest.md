# ADR-0027: Auto-ingest with a per-run Beatport login and EventBridge Scheduler
Status: Accepted
Date: 2026-10-07

## Context

Ingest needed a Beatport token pasted into the admin page, so the catalog grew only when the
owner clicked. A login flow without a browser (API v4 login → authorize → token) was proven in
a separate sandbox. The owner wants runs a few times a day at times set in the admin — fixed,
or N random times — each ingesting a few periods: due weeks first, then an even backfill.

Options considered:
- **Where it runs**: GitHub Actions cron (credentials stay in GitHub, but schedules live in a
  workflow file, not the admin, and a run reaches Aurora only through the public API); a Lambda
  ticking every 15 minutes that decides whether it is time (simple, but ~96 invocations a day
  to do 3 runs, and "random" becomes a dice roll per tick); **Lambda + EventBridge Scheduler**
  with one-time `at()` schedules written by a daily planner from the admin settings.
- **Token**: log in on every run, or cache a refresh token (fewer logins, but a long-lived
  secret written somewhere — against the rule that `bp_token` is never persisted).
- **Overlap**: reserved concurrency 1 (impossible: the account's concurrency quota is 10 and
  AWS keeps 10 unreserved), or a lease on the settings row.
- **Failed pairs**: fake `FAILED` rows in `ingest_runs` (its `raw_s3_key` is NOT NULL and the
  backfill planner reads it), or a separate attempts table.

## Decision

- A `clouder-prod-auto-ingest` Lambda with actions `auth_check`, `plan` and `run`. A recurring
  schedule runs `plan` at 00:05 UTC; `plan` replaces the group's pending `run-*` one-time
  schedules from the settings row; saving settings in the admin invokes `plan` at once.
- Credentials flow GitHub secrets → SSM SecureString; each run logs in and keeps the token in
  memory only.
- A run takes a 15-minute lease on the settings row; random runs are at least 60 minutes apart.
- A run calls the admin endpoint's ingest core (`collect_period`), so both paths write the
  same raw objects and `ingest_runs` rows (`meta.trigger` tells them apart).
- Failed attempts go to `auto_ingest_attempts`; an attempt also counts as failed when its run
  later fails in canonicalization. Three failures in a row within a week, with no completed run,
  mark a pair stuck. A token the catalog rejects stops the run without charging any pair.

## Consequences

- Freshness no longer depends on a person; `styles_behind` is the end-to-end check.
- A Beatport login change stops auto-ingest at the login step (alarm
  `clouder-prod-auto-ingest-failed`); manual ingest with a pasted token keeps working.
- The account's password is in SSM. The role can read only those two parameters, and the token
  never leaves the run.
- Schedules are per day: a settings change applies to the rest of today immediately and to
  later days through the planner.
- A stuck pair waits a week before it is tried again, or for a manual ingest from the coverage
  matrix; an outage of a day can park the pairs it hit for that week.

**Cross-references:** ADR-0003 (Saturday-week), ADR-0023 (data quality), ADR-0024 (replay-safe
canonicalization), `docs/data/auto-ingest.md`.

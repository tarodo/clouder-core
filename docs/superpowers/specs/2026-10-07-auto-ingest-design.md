# Auto-ingest — design

Date: 2026-10-07. Status: approved in conversation (sections 1–2 by the owner; the owner
delegated the rest: "дальше без меня до деплоя на прод").

## Purpose

CLOUDER's catalog is filled only when the owner opens the admin page, pastes a Beatport token
and ingests a style × week by hand. The portfolio claims automatic ingestion; this makes it
true: the catalog keeps every visible style current and backfills history evenly, with no
token pasted by a person.

Success: for several days without a manual ingest, the data-quality check `styles_behind`
stays 0, and the coverage matrix fills deeper into the past evenly across styles.

## What the owner decided

- Credentials come from GitHub (environment `production` secrets `BEATPORT_USERNAME`,
  `BEATPORT_PASSWORD`).
- Token by the approach tested in `HP/bp_t/bp_token_api.py`: Beatport API v4 login →
  authorize (code) → token, no browser.
- A run ingests 3 periods (configurable); runs happen at configurable times — fixed times, or
  N random times a day spread over the whole 24 hours.
- Styles = all visible styles (`clouder_styles.is_hidden = false`); no separate toggle.
- Backfill floor configurable in the admin, default the start of 2026.
- Runtime: AWS (approach A) — Lambda + EventBridge Scheduler, configured from the admin.

## Constraints

- `bp_token` is never logged or persisted (CLAUDE.md #5): log in on every run, keep the token in
  memory for that run only; no refresh-token cache (the `bp_t` cache file does not carry over).
- Runtime DB access only through the RDS Data API (ADR-0001).
- The manual admin ingest stays unchanged in behaviour.
- Least-privilege IAM for every new role; no money figures in docs.

## 1. Credentials and token

- Deploy workflow: a step writes `BEATPORT_USERNAME` / `BEATPORT_PASSWORD` to SSM SecureString
  `/clouder/beatport/username` and `/clouder/beatport/password` (the existing GitHub → SSM
  pattern used for Gemini/Spotify). The step is skipped while the secrets are empty, so
  deploys keep working before the owner adds them.
- `src/collector/beatport_auth.py` — `fetch_access_token(username, password, *, opener=None) ->
  str`, stdlib only (`urllib.request` with a cookie jar):
  1. `POST https://api.beatport.com/v4/auth/login/` JSON `{username, password}` (session cookie);
  2. `GET /v4/auth/o/authorize/?response_type=code&client_id=…&redirect_uri=…` without
     following the redirect → `code` from `Location`;
  3. `POST /v4/auth/o/token/` form `grant_type=authorization_code, code, redirect_uri,
     client_id` → `access_token`.
  `client_id` is the public one from Beatport's API docs (`BEATPORT_CLIENT_ID` env override),
  `redirect_uri = …/v4/auth/o/post-message/`. Errors raise `BeatportAuthError(step, status)`;
  messages carry the step and HTTP status only, never bodies or tokens.
- Credentials are read at run time via the existing `secrets._fetch_ssm_parameter` (the role
  may read exactly those two parameters).
- **Spike (gate):** the first deploy ships the Lambda with an `auth_check` action that logs in
  and returns `{"ok": true}` or `{"ok": false, "step": …, "status": …}` — no token in the
  output. Everything else is built only if a login from AWS works.

## 2. Which periods to ingest

Unit: (style, Saturday-week). Styles: visible, with a Beatport identity.

- **Ingested** = a non-custom run for the (style, week_year, week_number) with status
  `COMPLETED`, or `RAW_SAVED` started within the last 6 hours (canonicalization pending).
  ISO-week runs from March (no `week_year`) do not count; those weeks are re-ingested as
  Saturday-weeks — safe since replay-safe canonicalization (ADR-0024).
- **Due week** = the latest Saturday-week whose Friday is at least 3 days before today
  (UTC). It is not ingested before then.
- **Stuck** = a pair whose last 3 runs all failed and that has no `COMPLETED` run; skipped by
  the planner, listed in the admin.
- **Choice** for a run with budget `periods_per_run` (default 3):
  1. every style missing the due week gets it (styles ordered by Beatport id);
  2. the rest of the budget goes to missing, non-stuck pairs from the due week down to the
     backfill floor (weeks starting on or after the floor date), ordered newest week first,
     then by style — so all styles descend together, week by week.
- When the floor is reached for every style, only new due weeks are ingested.

## 3. Scheduling

- **Settings** (Aurora table `auto_ingest_settings`, one row, `id = 1`):
  `enabled` (default false), `mode` (`fixed` | `random`, default `random`), `fixed_times`
  (JSON list of `HH:MM`, default `["09:00","15:00","21:00"]`), `runs_per_day` (1–12, default
  3), `timezone` (IANA name, default `UTC`; fixed times are local to it), `periods_per_run`
  (1–10, default 3), `backfill_floor` (date, default `2026-01-03`), `planned_runs` (JSON list of
  UTC ISO times, written by the planner), `last_run` (JSON summary), `updated_at`,
  `updated_by_user_id`.
- **Planner** (action `plan`): a Terraform-managed recurring EventBridge Scheduler schedule runs
  it at 00:05 UTC daily. It plans the window [now, next 00:05 UTC):
  - `fixed`: every configured local time that falls in the window (converted with `zoneinfo`);
  - `random`: `runs_per_day` uniform random times in the window, at least 60 minutes apart
    (fewer if the window is too short); when replanning mid-window the count is scaled by the
    remaining share of the day, rounded up;
  - deletes the pending one-time schedules it created before (names `run-*` in the schedule
    group `clouder-prod-auto-ingest`) and creates one `at(...)` schedule per time with
    `ActionAfterCompletion = DELETE`, target = the auto-ingest Lambda, input
    `{"action": "run"}`; writes the times to `planned_runs`;
  - disabled → deletes pending schedules, plans nothing.
- **Saving settings** in the admin replans immediately: the API Lambda saves the row and invokes
  the auto-ingest Lambda asynchronously with `{"action": "plan"}`.
- **Concurrency:** the auto-ingest Lambda has reserved concurrency 1; a throttled invocation is
  retried by the scheduler. The 60-minute gap keeps random runs apart.

## 4. Running

Action `run` (also `{"action": "run", "manual": true}` from an admin "Run now" button):

1. Load settings; skip if disabled (unless manual).
2. Read the credentials, log in (`beatport_auth`). A login failure ends the run:
   `auto_ingest_run_failed` (step, status) — no ingest.
3. Choose the periods (section 2).
4. For each pair, call the same ingest core as the admin endpoint (refactored out of
   `handler._run_beatport_ingest` into `collect_period(params, correlation_id, …)`): fetch
   from Beatport, write raw to S3, create the `ingest_runs` row (`meta.trigger = "auto"`),
   enqueue canonicalization. A pair that fails records a `FAILED` run for that (style, week)
   (`error_code = auto_ingest_failed`, message = error type and HTTP status) so the coverage
   matrix and the stuck rule see it; the run continues with the next pair.
5. Write `last_run` (time, pairs with outcome) and log `auto_ingest_run_completed`
   (`count`, `runs_failed`).

The token is passed in memory to `collect_period`; it never enters a queue, a log, S3 or the DB.

## 5. Admin

- API (collector API Lambda, admin-only): `GET /admin/auto-ingest` (settings, planned runs, last
  run, stuck pairs, due week), `PUT /admin/auto-ingest` (validated settings → save → replan),
  `POST /admin/auto-ingest/run` (async run now). Registered in the three places routes live
  (handler route table, `scripts/generate_openapi.py`, API Gateway Terraform); OpenAPI and the
  frontend schema regenerated.
- UI: an "Auto-ingest" section on the admin coverage page (pattern of `AdminAutoEnrichPage`):
  enabled switch; mode (fixed times / N random per day); times or N; timezone (default the
  browser's); periods per run; backfill floor; Save; "Run now"; status: next planned runs, last
  run with per-pair outcome, stuck pairs. i18n keys in both locales.

## 6. Observability, docs, rollout

- Log metric filters on the auto-ingest log group: `AutoIngestRunFailed` (login failure or all
  pairs failed) → alarm `clouder-prod-auto-ingest-failed` (daily sum ≥ 1). `styles_behind` (DQ)
  is the end-to-end check.
- Docs: `docs/data/auto-ingest.md` (why / before / after / how it chooses / how to run / what
  it buys), ADR-0027, runbook entries (login failure, stuck pairs), env vars, architecture,
  CLAUDE.md.
- Rollout: (A) credentials + `beatport_auth` + Lambda with `auth_check` → deploy → spike;
  (B) the rest, deployed with `enabled = false`; enable from the admin, Run now once, watch the
  first scheduled runs; fill "After" (runs, periods ingested, `styles_behind`).

## Testing

- `beatport_auth`: a fake opener for the three-step flow, each failure step, no token in errors.
- Planner: due-week arithmetic around Friday/Monday boundaries; priority of due weeks; even
  descent; floor; stuck skipping; RAW_SAVED pending; real-Postgres test of the SQL.
- Scheduling: fixed times across timezones (incl. a DST date), random spacing ≥ 60 min, replan
  scaling, deletion of pending schedules — with a fake scheduler client.
- Runner: login failure; one pair failing records a FAILED run and the others continue; the
  token is absent from every log event.
- API: validation, admin-only, replan invoke; frontend: form, save, run now, status rendering.

## Out of scope

Proxying or browser automation if AWS logins are blocked (decided after the spike); per-style
toggles; refresh-token caching; ISO-week re-ingest semantics beyond "they do not count".

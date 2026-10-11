# Auto-ingest Phase B (planner, scheduler, runner, admin) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest visible Beatport styles automatically on an admin-configured schedule — the due week first, then history, newest first, evenly across styles — with the token obtained per run.

**Architecture:** Settings and attempt history in Aurora (`auto_ingest_settings`, `auto_ingest_attempts`). Pure modules decide what to ingest (`auto_ingest_plan`) and when (`auto_ingest_schedule`). The `clouder-prod-auto-ingest` Lambda gains `plan` (daily at 00:05 UTC via a Terraform-managed EventBridge Scheduler schedule, and on every settings save) and `run` (one-time `at()` schedules created by `plan`, or "Run now"): lease → login → choose periods → the shared ingest core per period → attempts and summary. Admin API on the collector Lambda; a panel on the admin coverage page.

**Tech Stack:** Python 3.12 (stdlib `zoneinfo`, `random`), RDS Data API, Alembic, EventBridge Scheduler, Lambda, Terraform, React 19 + Mantine 9 + TanStack Query, vitest, pytest + real Postgres.

**Spec:** `docs/superpowers/specs/2026-10-07-auto-ingest-design.md` (sections 2–6), with the Phase A ruling: no reserved concurrency — a lease on the settings row.

## Global Constraints

- The token never leaves the `run` invocation's memory: not in logs, attempts, `last_run`, queues, S3 or exceptions stored anywhere.
- Runtime DB only through the Data API; date literals for Athena do not apply here.
- Manual admin ingest behaves exactly as before (same response, same `ingest_runs` rows); auto runs add `meta.trigger = "auto"`.
- Least-privilege IAM; the collector role gains only `lambda:InvokeFunction` on the auto-ingest function.
- New routes in all three places (handler, `scripts/generate_openapi.py`, `infra/api_gateway.tf`); regenerate `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts`.
- Frontend gates: `pnpm typecheck`, `pnpm lint`, `pnpm test`.
- Ships disabled (`enabled = false`); no money figures in docs.
- `$VENV=<repo>/.venv/bin`; PG tests `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres` (migrate the container to head first); commits via caveman-commit rules.

## Review Focus

1. **Two runs overlap** (random times, a manual "Run now" during a scheduled run) → the second skips; nobody ingests the same pair twice. Test: `test_second_run_skips_while_the_lease_is_held` (Task 5).
2. **A Beatport failure on one period** → recorded as a failed attempt without the token, the run continues; three failed attempts make the pair stuck and the planner skips it. Tests: `test_failed_period_is_recorded_and_the_run_continues`, `test_three_failed_attempts_make_a_pair_stuck` (Tasks 5, 1).
3. **Timezones and DST** for fixed times; random times at least 60 minutes apart. Tests: `test_fixed_times_follow_the_timezone_across_dst`, `test_random_times_are_spaced` (Task 3).
4. **The due week on its boundary days** (Friday close, Monday after the 3-day grace, year boundary). Test: `test_due_week_boundaries` (Task 2).
5. **Settings saved with invalid values** (bad time, unknown timezone, floor in the future) → 400, nothing saved, no replan. Test: `test_put_rejects_invalid_settings` (Task 6).

---

### Task 1: Tables and repository

**Files:** Create `alembic/versions/20261007_34_auto_ingest.py`, `src/collector/auto_ingest_repository.py`, `tests/db/test_auto_ingest_repository_pg.py`.

**Produces:** tables `auto_ingest_settings` (one row `id = 1`: `enabled bool false`, `mode text 'random'` check fixed|random, `fixed_times jsonb ["09:00","15:00","21:00"]`, `runs_per_day int 3`, `timezone text 'UTC'`, `periods_per_run int 3`, `backfill_floor date '2026-01-03'`, `planned_runs jsonb []`, `last_run jsonb null`, `running_until timestamptz null`, `updated_at timestamptz`, `updated_by_user_id varchar(36)`) and `auto_ingest_attempts` (`id bigserial`, `style_id int`, `week_year int`, `week_number int`, `attempted_at timestamptz`, `ok bool`, `run_id varchar(36) null`, `error text null`; index `(style_id, week_year, week_number, attempted_at)`). `AutoIngestRepository(data_api)` with `get_settings() -> dict`, `save_settings(values: Mapping, *, user_id: str | None, now: datetime) -> dict`, `set_plan(planned: list[str], now)`, `set_last_run(summary: Mapping)`, `acquire_lease(now, minutes=15) -> bool`, `release_lease()`, `record_attempt(style_id, week_year, week_number, *, ok, run_id, error, at)`, `planning_state(now) -> PlanningState(styles: tuple[int, ...], loaded: frozenset[tuple[int,int,int]], stuck: frozenset[...])`, `stuck_pairs() -> list[dict]`.

- [ ] Failing PG tests: settings default row and save round-trip (jsonb times, date floor); `acquire_lease` true then false until expired; `planning_state` — visible styles only (a hidden style excluded), `loaded` counts COMPLETED and RAW_SAVED younger than 6 h but not FAILED, older RAW_SAVED, custom ranges or ISO-only runs; `test_three_failed_attempts_make_a_pair_stuck` (2 failures → not stuck; 3 → stuck; a later success → not stuck).
- [ ] Migration + repository; `alembic upgrade head` on the test container; tests green; commit `feat(auto-ingest): settings and attempts tables`.

### Task 2: What to ingest — `auto_ingest_plan`

**Files:** Create `src/collector/auto_ingest_plan.py`, `tests/unit/test_auto_ingest_plan.py`.

**Produces:** `GRACE_DAYS = 3`; `due_week(today: date) -> tuple[int, int]` (Saturday-week whose Friday is ≤ today − 3 days); `choose_periods(styles, loaded, stuck, *, due, floor, budget) -> list[tuple[int, int, int]]` — weeks from `due` backwards (due always included, older weeks only while their start ≥ `floor`), styles ascending within a week, skipping loaded and stuck pairs, until `budget`.

- [ ] Failing tests: `test_due_week_boundaries` (Mon after a Friday close = that week; Sun = previous; across New Year with `saturday_week`), `test_due_week_comes_first_for_every_style`, `test_history_descends_evenly_across_styles` (two styles, budget 3 over several runs → weeks fill pairwise newest first), `test_floor_stops_backfill_but_not_the_due_week`, `test_loaded_and_stuck_are_skipped`.
- [ ] Implement with `saturday_week.week_of_date` / `saturday_week_range`; commit `feat(auto-ingest): choose periods, due week first`.

### Task 3: When to ingest — `auto_ingest_schedule`

**Files:** Create `src/collector/auto_ingest_schedule.py`, `tests/unit/test_auto_ingest_schedule.py`.

**Produces:** `MIN_GAP = timedelta(minutes=60)`; `window_end(now) -> datetime` (next 00:05 UTC); `plan_times(settings, now, *, rng) -> list[datetime]` (UTC, sorted; `fixed`: local times in `timezone` falling in (now, window_end]; `random`: `ceil(runs_per_day × remaining/24 h)` times in (now + 5 min, window_end) at least `MIN_GAP` apart, fewer if they do not fit; disabled → `[]`); `apply_schedule(client, *, group, target_arn, role_arn, times) -> list[str]` (deletes `run-*` schedules in the group, creates `run-YYYYMMDDTHHMM` with `at(YYYY-MM-DDTHH:MM:SS)` UTC, `ActionAfterCompletion="DELETE"`, input `{"action": "run"}`, retry 2 / 1 h).

- [ ] Failing tests: `test_fixed_times_follow_the_timezone_across_dst` (Europe/Berlin on the 2026-10-25 switch), `test_fixed_times_outside_the_window_are_dropped`, `test_random_times_are_spaced` (seeded rng, 50 draws: all ≥ 60 min apart and inside the window), `test_replan_mid_window_scales_the_count`, `test_disabled_plans_nothing`, `test_apply_replaces_pending_run_schedules` (fake client: deletes only `run-*`, creates with the exact `at()` and target).
- [ ] Implement; commit `feat(auto-ingest): plan run times and schedules`.

### Task 4: Shared ingest core

**Files:** Modify `src/collector/handler.py`; Test `tests/unit/test_handler_collect_period.py` (create).

**Produces:** `IngestParams` (the existing `_IngestParams`, public alias kept), `collect_period(params, correlation_id, *, api_request_id: str, lambda_request_id: str, trigger: str = "manual") -> dict` — the body of `_run_beatport_ingest` returning the response dict, adding `meta["trigger"]`; `_run_beatport_ingest` = `_json_response(200, collect_period(...))`.

- [ ] Failing test: `collect_period(..., trigger="auto")` with fakes (Beatport client registry, S3, repository, SQS) writes `meta.trigger = "auto"` to `create_ingest_run` and returns the same keys as the endpoint; existing handler tests unchanged and green.
- [ ] Refactor; full suite; commit `refactor(ingest): shared collect_period core`.

### Task 5: Lambda actions `plan` and `run`

**Files:** Modify `src/collector/auto_ingest_handler.py`, `src/collector/logging_utils.py`; Test `tests/unit/test_auto_ingest_handler.py`.

**Consumes:** Tasks 1–4, Phase A `fetch_access_token`.

- [ ] Failing tests (fakes for repository, scheduler client, `collect_period`, `fetch_access_token`): `plan` writes `planned_runs` and calls `apply_schedule` with `context.invoked_function_arn`; `run` skips when disabled (not manual) or `test_second_run_skips_while_the_lease_is_held`; login failure → `auto_ingest_run_failed` logged, no `collect_period`, lease released; `test_failed_period_is_recorded_and_the_run_continues` (second of three periods raises → attempts ok/failed/ok, `last_run` lists outcomes, error text = exception type only); the token appears in no log event, attempt or `last_run`.
- [ ] Implement; log fields allowed; commit `feat(auto-ingest): plan and run actions`.

### Task 6: Admin API

**Files:** Modify `src/collector/handler.py`, `src/collector/schemas.py` (`AutoIngestSettingsIn`), `scripts/generate_openapi.py`, `infra/api_gateway.tf`, `docs/api/openapi.yaml` (generated), `frontend/src/api/schema.d.ts` (generated); Test `tests/unit/test_handler_auto_ingest.py`.

**Produces:** `GET /admin/auto-ingest` → `{settings, planned_runs, last_run, due_week: {week_year, week_number}, stuck: [{style_id, week_year, week_number, attempts}]}`; `PUT /admin/auto-ingest` (validated: times `HH:MM` 1–12 unique, `runs_per_day` 1–12, IANA timezone, `periods_per_run` 1–10, floor ≥ 2000-01-01 and ≤ today) → saved settings, then async invoke `{"action": "plan"}`; `POST /admin/auto-ingest/run` → 202 after async invoke `{"action": "run", "manual": true}`. Env `AUTO_INGEST_FUNCTION_NAME`.

- [ ] Failing tests: GET shape; `test_put_rejects_invalid_settings` (each invalid field → 400, no save, no invoke); PUT valid → save + invoke plan; POST run → invoke run; admin-only (non-admin 403).
- [ ] Implement, register routes in all three places, regenerate OpenAPI (`PYTHONPATH=src $VENV/python scripts/generate_openapi.py`) and `cd frontend && pnpm api:types`; commit `feat(api): admin auto-ingest settings and run now`.

### Task 7: Infra

**Files:** Modify `infra/auto_ingest.tf`, `infra/iam.tf` (collector invoke), `infra/lambda.tf` (API env); Test `tests/unit/test_auto_ingest_infra.py`.

- [ ] Failing infra tests: schedule group + daily planner schedule `cron(5 0 * * ? *)` UTC with input `{"action":"plan"}`; scheduler role may only invoke the auto-ingest function; auto-ingest role gains Data API + cluster secret + `s3:PutObject` on the raw prefix + `sqs:SendMessage` on the canonicalization queue + `scheduler:CreateSchedule/DeleteSchedule/GetSchedule` on the group's schedules, `scheduler:ListSchedules`, `iam:PassRole` on the scheduler role; Lambda env (raw bucket/prefix, canonicalization queue, Aurora, group, scheduler role); collector role `lambda:InvokeFunction` on the auto-ingest function and API env `AUTO_INGEST_FUNCTION_NAME`; metric filter `auto_ingest_run_failed` → alarm `clouder-prod-auto-ingest-failed`.
- [ ] Implement; `terraform fmt`; commit `feat(infra): auto-ingest scheduling and permissions`.

### Task 8: Admin panel

**Files:** Create `frontend/src/api/autoIngest.ts`, `frontend/src/features/admin/hooks/useAutoIngest.ts`, `useSaveAutoIngest.ts`, `useRunAutoIngest.ts`, `frontend/src/features/admin/components/AutoIngestPanel.tsx`, `frontend/src/features/admin/components/__tests__/AutoIngestPanel.test.tsx`; Modify `AdminCoveragePage.tsx`, `frontend/src/i18n/en.json`.

- [ ] Failing vitest: renders settings from the hook; switching mode shows times vs N; Save sends the edited body; invalid time disables Save with a message; Run now calls the mutation; status shows next planned runs (local time), last run outcomes, stuck pairs.
- [ ] Implement (Mantine `Switch`, `SegmentedControl`, `TagsInput` for times, `NumberInput`, `Select` timezone from `Intl.supportedValuesOf('timeZone')`, `DateInput` floor); `pnpm typecheck && pnpm lint && pnpm test`; commit `feat(admin): auto-ingest panel on the coverage page`.

### Task 9: Docs

**Files:** Create `docs/data/auto-ingest.md`, `docs/adr/0027-auto-ingest.md`; Modify `docs/adr/README.md`, `docs/data/README.md`, `docs/ops/runbook.md` (login failure, stuck pairs, disable), `docs/ops/env-vars.md`, `docs/architecture.md`, `CLAUDE.md` (Where things are + gotcha #5 note: auto-ingest logs in per run).

- [ ] `auto-ingest.md`: Why, Before (manual only; `styles_behind = 2` on 2026-10-07: Funky House weeks 34–39 and Mainstage 32–39 missing), how it chooses, schedule, how to run/disable, security (credentials path, token lifetime), After (pending first runs), What it buys. ADR-0027: AWS + Scheduler vs tick vs GitHub cron; login per run vs refresh cache; lease vs reserved concurrency. Doc checks; full suite; commit `docs(auto-ingest): guide and ADR-0027`; graph refresh.

## After merge

1. Deploy; `auth_check` still ok; enable in the admin with defaults (random, 3/day, 3 periods); "Run now" once → expect the due weeks of Funky House and Mainstage first.
2. Watch the first scheduled runs; fill "After" (runs, periods ingested, `styles_behind` → 0) in `docs/data/auto-ingest.md` and the audit.

# Phase 1 — Pre-Execution Fix Ledger

> Companion to the five increment plans (`...phase1-1..5-*.md`). Every item below is a **real defect confirmed against the live repo** by the adversarial review of the v2 plans. Apply each fix when its increment is executed (the subagent-driven-development loop will also surface them against the real toolchain — this ledger ensures none is missed). Severity: **blocker** = the increment cannot pass its own gates without it; **major** = ships wrong/unverified behaviour; **note** = accepted scope decision.

Cross-increment contracts are already reconciled in the plans (bronze table names `bronze_events` / `bronze_catalog_export` / `bronze_ops`; `context`/`props` are JSON **strings** parsed with Athena `json_extract`; `track_ids` **is** in the Increment-2 `PROP_ALLOWLIST`; `dbt-athena-community==1.9.2`). The items here are the residuals.

---

## Increment 1 — Telemetry SDK

- **[blocker] Telemetry tests must mock `usePlayback`/`useAuth`, not mount real providers.** `BucketDetailPage.telemetry.test.tsx` and `useCurateSession.telemetry.test.tsx` render components that call `usePlayback()` (BucketDetailPage.tsx:73) / `useAuth()` (PlaybackProvider first line); both throw without a provider. Follow the existing pattern: `vi.mock('../../playback/usePlayback', ...)` (see `BucketDetailPage.integration.test.tsx`, `useCurateSession.test.tsx`). Do **not** mount real `<PlaybackProvider>`/`<AuthProvider>`.
- **[blocker] MSW move-handler URL is fabricated.** Tests register `http.post('http://localhost/triage/blocks/blk1/tracks/move', …)`; the real endpoint is `/triage/blocks/${blockId}/move` (`useMoveTracks.ts:114,144`). With `onUnhandledRequest:'error'` the real POST is unhandled, `onSuccess` never runs, and the `track_categorized` emit it wraps never fires. Use the real URL.
- **[major] Task ordering.** `sdk.ts` calls `api(..., { suppressAuthFailure:true })`, a property that only exists after the `client.ts` change. Ship the `client.ts` `{suppressAuthFailure}` task **before** the SDK task, or the SDK task's `pnpm typecheck` gate fails (TS2353).
- **[major] Missing YtMusic publish test.** File structure + run step promise `PublishYtMusicButton.telemetry.test.tsx` ("run all three"), but only two test files are written. Add the third (render `PublishYtMusicButton`, fire publish, assert `playlist_publish` with `target:'ytmusic'`).
- **[note] `track_view` wired on triage rows only.** Categories (`CategoryDetailPage`) and playlists (`PlaylistTracksList`) rows are an identical `useTrackView()` add, explicitly deferred to "Increment 1b". Accepted (flag is off; one-line follow-up per row).

## Increment 2 — Ingest landing

- **[major] Serialize `context`/`props` as JSON strings in the Firehose record.** `bronze_events` declares `context` and `props` as Glue type `string`, but the handler must not emit them as nested JSON objects (OpenX JSON SerDe format-conversion would fail and `bronze/events/` would stay empty). Build the record as `{…envelope, "context": json.dumps(context), "props": json.dumps(props)}` (string columns, cast in dbt — matches §3/§8 schema-on-read). Add a unit test pinning the record's `props` shape to `str`.

## Increment 3 — Catalog + ops export

- **[major] `_PAGE = 5000` can exceed the RDS Data API result cap.** A 5000-row page of a wide dim (`clouder_tracks`, ~15 cols) likely tops the ~1 MB `ExecuteStatement` response limit → `Database response exceeded size limit` at runtime. Drop to ~500 (or chunk by response size), test paging at the real default, and update the ponytail note to name the **response-size** cap (not just OFFSET scan cost).

## Increment 4 — dbt + orchestration

> This file is the recovered full **draft**; the four fixes below were found by its review and are not yet applied.

- **[blocker] `assert_dim_date_known_weeks.sql`: wrong literal for `2026-01-02`.** The canonical `week_of_date(2026-01-02)` is **`(2025, 52)`**, not `(2025, 53)` — 2025 has 52 Saturday-weeks (verified by running `src/collector/saturday_week.py`). As written, this singular test fails every run and routes the Step Functions DAG to `NotifyFailure` permanently. Change the expected `saturday_week_number` to `52`.
- **[major] Gold facts overwrite ALL dt partitions → Athena 100-partition limit.** The 5 gold facts are `incremental` + `insert_overwrite` + `partitioned_by=[dt]` but lack the `{% if is_incremental() %}` dt-lookback predicate the silver models have. Each run re-reads all of silver and overwrites every historical `dt`; past ~100 distinct days this raises `HIVE_TOO_MANY_OPEN_PARTITIONS`. Add the lookback predicate to each gold fact. **`fact_playback` caveat:** filter only the *written* partitions on the final `select` — never a `dt>=today-N` filter on `stg_playback`, which would drop the play row of a play whose terminal lands on a different day and break cross-day terminal grouping. (The regen's `fact_playback.sql` already encodes this pattern — graft it.)
- **[major] `fact_playback` has no live backstop.** Only the Python mirror (`playback_terminal_mirror.py`) is asserted; nothing live exercises the shipped SQL's running-count grouping + priority terminal selection, so `not_null`/`unique`/`relationships` stay green while the SQL is wrong. Add a dbt `unit_tests.yml` seeding 6 `(session,track)` play streams (pause→remote-resume→ended ⇒ ended; pause→local-resume→ended ⇒ 2 rows; play→skip ⇒ skipped; play→pause ⇒ pause terminal; ratio-only; etc.) asserting `terminal`/`skipped`/`played_ms` — content is in the regen output.
- **[major] `gh -C <dir>` is not a valid flag.** `gh` has no global `-C`/working-dir flag (unlike `git -C`); the PR step aborts with `unknown shorthand flag: 'C'`. Run `gh` from the worktree cwd (no `-C`).
- **[prerequisite] Inc-4 infra depends on Inc 1–3.** `analytics_dbt.tf` / the `dbt_runner` / the SFN reference `aws_lambda_function.catalog_export`, `…ops_log_export`, `aws_s3_bucket.analytics_lake`, and the bronze Glue tables — all created by Increments 1–3. State explicitly: **Increments 1–3 must be applied before Increment 4's `terraform validate`/`apply`.**

## Increment 5 — Serving + dashboards

- **[major] Correlation join drops `user_key`.** `_ROUTE_QUERIES["playback"]["by_category"]` joins `fact_playback → fact_track_decision` on `track_key` only. Under the multi-tenant constraint (facts carry `user_key`) this cross-joins one user's plays against every user's categorization of the same track, corrupting the listen-ratio-vs-category correlation. Join on **`track_key` AND `user_key`** (§11 calls this out explicitly).
- **[confirmed ok]** `/v1` is registered in CloudFront `api_gw_pure_path_patterns` + the Vite proxy (done in Increment 2); every §11 dashboard metric has a query (undo rate, label affinity, listen-ratio×category, seek heatmap, Saturday-week rollup, p50/p95).

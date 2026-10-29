# AI Reputation of Labels and Artists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Labels and artists caught releasing AI tracks carry a 1–3 AI level, shown as a monochrome badge next to their names, and a triage block can send their tracks to NOT from a chosen level.

**Architecture:** Counts live on `clouder_labels` / `clouder_artists` (`ai_total`, `ai_checked`, `ai_tracks`) with a generated `ai_level`. A migration backfills them; `record_analysis_results` recounts the labels and artists of the tracks a results POST touches. API rows carry an `ai` object built by one SQL helper; the SPA renders it with one `AiRepBadge`. Block creation adds an AI-label/artist branch to the NOT tier of the existing classify `CASE`.

**Tech Stack:** Python 3.12 Lambdas, Aurora PostgreSQL via RDS Data API, Alembic, pytest (+ `tests/db` on local Postgres 16); React 19 + Mantine 9, vitest (jsdom + browser).

**Spec:** `docs/superpowers/specs/2026-10-29-ai-label-artist-reputation-design.md`

## Global Constraints

- Share = `ai / checked`; `checked` = tracks with an `ok` row from `ai_lofcz` or `ai_deezer`; `ai` = `AI_FLAGGED_SQL`.
- Levels: none `ai = 0`; 1 `ai ≥ 1` and share < 25%; 2 25% ≤ share ≤ 50%; 3 share > 50%.
- Artist counts take every role in `clouder_track_artists`; label counts go through `clouder_albums.label_id`.
- Badge: text "AI"; L1 white fill, black text, black border; L2 `#6b6b6b` fill, white text; L3 black fill, white text. Light theme only.
- Tooltip copy (exact): `AI: {ai} of {checked} checked · {total} in CLOUDER` (hover; tap on touch).
- Create dialog copy (exact): "Send AI-label tracks to NOT", "Send AI-artist tracks to NOT"; options "Off", "From level 1", "From level 2", "From level 3"; default Off.
- Classify order: AI-flagged → DISCARD (if `ai_to_discard`), liked → FAV (if `include_favorites`), disliked **or AI label/artist** → NOT, dates, compilations, NEW. Only at creation.
- Runtime DB access only through the Data API (no psycopg in `src/collector`).
- API object shape everywhere: `{"level": 1|2|3, "ai": int, "checked": int, "total": int}` or `null`.

## Review Focus

1. Level boundaries: 1 of 4 → 2, 2 of 4 → 2, 3 of 5 → 3, 1 of 5 → 1 (Task 1 test).
2. A result that is `ok` and **not** AI must still recount (checked grows, level can drop 3 → 2) (Task 2 test).
3. Liked label/artist beats the AI rule (FAV), and an AI-flagged track still goes to DISCARD (Task 4 test).
4. A featured/remixer artist (non-main role) at the level sends the track to NOT (Task 4 test).
5. A track with no label (`album_id`/`label_id` NULL) gets `label_ai = null` and never breaks the classify or the row mapping (Tasks 3, 4 tests).

---

### Task 1: Migration — counts, generated level, block options, backfill

**Files:**
- Create: `alembic/versions/20261029_46_ai_reputation.py` (revision `20261029_46`, down `20261023_45`)
- Modify: `src/collector/db_models.py` (ClouderLabel, ClouderArtist, TriageBlock columns)
- Test: `tests/db/test_ai_reputation_pg.py`

**Interfaces:**
- Produces: columns `ai_total INT NOT NULL DEFAULT 0`, `ai_checked INT NOT NULL DEFAULT 0`, `ai_tracks INT NOT NULL DEFAULT 0`, `ai_level SMALLINT GENERATED ALWAYS AS (CASE WHEN ai_tracks = 0 THEN NULL WHEN ai_tracks * 2 > ai_checked THEN 3 WHEN ai_tracks * 4 >= ai_checked THEN 2 ELSE 1 END) STORED` on `clouder_labels` and `clouder_artists`; `triage_blocks.ai_labels_min_level SMALLINT NULL`, `triage_blocks.ai_artists_min_level SMALLINT NULL`, each `CHECK (… BETWEEN 1 AND 3)`.

- [ ] **Step 1: failing test** `test_level_boundaries`: insert a label, `UPDATE clouder_labels SET ai_tracks=:a, ai_checked=:c`, read `ai_level` for `(0,4)→None, (1,5)→1, (1,4)→2, (2,4)→2, (3,5)→3, (1,1)→3`.
- [ ] **Step 2:** `TEST_DATABASE_URL=… .venv/bin/pytest tests/db/test_ai_reputation_pg.py -q` → FAIL (column missing).
- [ ] **Step 3:** write the migration; its upgrade also backfills both tables in one `UPDATE … FROM (aggregate)` each (counts as in Global Constraints, `checked`/`ai` via `EXISTS` on `track_analyses`), and the `CHECK` constraints. Mirror the columns in `db_models.py` (`Computed(..., persisted=True)`).
- [ ] **Step 4:** add `test_backfill_counts`: seed 1 label, 2 artists, 4 tracks with analyses (one ok+flagged, one ok clean, one failed, one none), run the migration's backfill SQL (import the module's SQL constants), assert label `(total 4, checked 2, ai 1, level 2)` and the featured artist counted. `alembic upgrade head` on local PG, rerun → PASS.
- [ ] **Step 5:** commit `feat(db): add AI reputation counts and block levels`.

### Task 2: Recount on detector results

**Files:**
- Modify: `src/collector/repositories/analysis.py`
- Test: `tests/db/test_ai_reputation_pg.py`, `tests/unit/test_analysis_repository.py` (fake Data API call order, if that file exists; else db test only)

**Interfaces:**
- Consumes: Task 1 columns.
- Produces: `AnalysisMixin.recount_ai_reputation(self, *, track_ids: list[str]) -> None` — recounts every label and artist of `track_ids` from all their tracks (two statements, one placeholder per id). `record_analysis_results` calls it with the accepted pair-analyzer items of status `ok` (flagged or not).

- [ ] **Step 1: failing tests** `test_results_recount_labels_and_artists` (record an ok+flagged result under a lease → label/artist `ai_tracks` 1, level 3) and `test_clean_result_lowers_level` (then an ok clean result for a second track of the same label → `checked` 2, level 2).
- [ ] **Step 2:** run → FAIL (counts stay 0).
- [ ] **Step 3:** implement; no call when no accepted ok pair item.
- [ ] **Step 4:** run Task 1+2 db tests and `tests/unit -k analysis` → PASS.
- [ ] **Step 5:** commit `feat(analysis): recount AI reputation on results`.

### Task 3: `ai` in API rows

**Files:**
- Modify: `src/collector/repositories/analysis.py` (helper), `src/collector/curation/triage_repository.py` (bucket tracks), `src/collector/curation/categories_repository.py`, `src/collector/curation/playlists_repository.py`, `src/collector/curation/routes_triage.py` / `routes_playlists.py` serializers, `src/collector/label_enrichment/repository.py` (`list_labels`, `get_label_info_for_user`), `src/collector/artist_enrichment/repository.py` (`list_artists`, `get_artist_info_for_user`), `scripts/generate_openapi.py`; regenerate `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`
- Test: `tests/db/test_ai_reputation_pg.py`, existing unit tests touched by row dicts

**Interfaces:**
- Produces: `ai_rep_sql(alias: str) -> str` in `repositories/analysis.py` — a SQL expression yielding the object or `NULL` when `{alias}.ai_level IS NULL`. Fields: triage `BucketTrackRowOut.label_ai: dict | None` and each `artists[i]["ai"]`; categories/playlists `label["ai"]` and `artists[i]["ai"]`; library list items and detail `ai`. Python side parses the JSON string like `artists`.

- [ ] **Step 1: failing db test** `test_rows_carry_ai_reputation`: a level-3 label + level-1 artist + a clean artist on one track in a NEW bucket, a category and a playlist; assert bucket row `label_ai == {"level":3,…}`, artist `ai` set/None; same through categories and playlists repos; `list_labels` and `get_label_info_for_user` item `ai`; artist counterparts. Include a track with no album → `label_ai is None`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement; add `ai` (nullable object, `level` enum 1–3) to the OpenAPI schemas of those responses; regenerate both files.
- [ ] **Step 4:** full `pytest -q` with DB → PASS; fix exact-dict unit expectations by adding the new keys.
- [ ] **Step 5:** commit `feat(api): expose AI reputation of labels and artists`.

### Task 4: Block creation rule

**Files:**
- Modify: `src/collector/curation/schemas.py` (`CreateTriageBlockIn`: `ai_labels_min_level: int | None = Field(default=None, ge=1, le=3)`, same for artists), `src/collector/curation/routes_triage.py` (pass through, serialize), `src/collector/curation/triage_repository.py` (`create_block` kwargs, INSERT, NOT tier, `TriageBlockRow` fields, `_fetch_block_detail`), `scripts/generate_openapi.py` + regen
- Test: `tests/db/test_ai_reputation_pg.py`, `tests/unit/test_triage_repository.py`, `tests/unit/test_routes_triage*.py` (whichever covers create)

**Interfaces:**
- Consumes: Task 1 `ai_level`.
- Produces: API create body + block JSON fields `ai_labels_min_level`, `ai_artists_min_level` (`1|2|3|null`).

- [ ] **Step 1: failing db tests** `test_ai_label_level_sends_to_not` (label level 2, block `ai_labels_min_level=2` → NOT; `=3` → NEW), `test_ai_artist_any_role` (remixer at level 3, `ai_artists_min_level=1` → NOT), `test_likes_and_discard_win` (liked label → FAV; AI-flagged track with `ai_to_discard` → DISCARD), `test_off_by_default` (no levels → date rules), `test_no_label_track` (album NULL → classified by date).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement — terms join the existing `disliked_terms` list (one bound param per enabled level, nothing bound when Off); validation 422 outside 1–3.
- [ ] **Step 4:** db + unit tests → PASS.
- [ ] **Step 5:** commit `feat(triage): send AI labels/artists to NOT at creation`.

### Task 5: `AiRepBadge` across the SPA

**Files:**
- Create: `frontend/src/features/library/components/AiRepBadge.tsx`, its `__tests__/AiRepBadge.test.tsx` and `AiRepBadge.browser.test.tsx`
- Modify: types (`features/triage/hooks/useBucketTracks.ts`, categories/playlists track types, library list/detail types), `features/triage/components/BucketTrackRow.tsx`, `features/curate/components/CurateCard.tsx`, `features/categories/components/TrackRow.tsx`, `features/playlists/components/PlaylistTrackRow.tsx`, `features/library/components/{LabelTile,ArtistTile,LabelsTable,ArtistsTable,LabelDetailHeader,ArtistDetailHeader}.tsx`, `frontend/src/demo/db.ts` (a few labels/artists with each level)

**Interfaces:**
- Consumes: Task 3 `ai` objects.
- Produces: `export type AiRep = { level: 1 | 2 | 3; ai: number; checked: number; total: number }`; `export function AiRepBadge({ rep }: { rep?: AiRep | null }): JSX.Element | null` — Mantine `Tooltip` (`events={{ hover: true, focus: true, touch: true }}`) over a focusable badge, `data-level`, `aria-label="AI level {n}"`, tooltip copy from Global Constraints (numbers via `toLocaleString`).

- [ ] **Step 1: failing tests** — unit: renders nothing for null; `data-level` and aria per level; tooltip text `AI: 80 of 87 checked · 869 in CLOUDER`. Browser: L1 bg white/border black, L2 bg rgb(107,107,107)/text white, L3 bg black/text white. One render test per surface asserting `AI level 3` appears next to the label and an artist (bucket row desktop + mobile, CurateCard, categories row, playlist row, LabelTile, ArtistTile, LabelsTable, ArtistsTable, both headers).
- [ ] **Step 2:** `pnpm test` / `pnpm test:browser` on those files → FAIL.
- [ ] **Step 3:** implement component and placements (badge right after each name; per artist, not after the joined string).
- [ ] **Step 4:** `pnpm typecheck && pnpm lint && pnpm test && pnpm test:browser` → PASS; demo screenshot at 390 and 1280 of a bucket and the library.
- [ ] **Step 5:** commit `feat(web): show AI reputation badges`.

### Task 6: Create dialog selects

**Files:**
- Modify: `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx`, `features/triage/hooks/useCreateTriageBlock.ts`, `features/triage/lib/triageSchemas.ts`, `frontend/src/i18n/en.json`, `frontend/src/demo/handlers.ts`/`db.ts` if create is mocked
- Test: `features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`

**Interfaces:**
- Consumes: Task 4 API fields.

- [ ] **Step 1: failing tests** — both selects present under Advanced options with value "Off"; submit sends `ai_labels_min_level: null, ai_artists_min_level: null`; choosing "From level 2" for labels sends `2`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement (Mantine `Select`, `allowDeselect={false}`, placed after the disliked-artists switch).
- [ ] **Step 4:** frontend gates → PASS.
- [ ] **Step 5:** commit `feat(web): pick AI levels when creating a block`.

### Task 7: Docs and ship

**Files:**
- Modify: `docs/data/data-model.md` (new columns, migration 46), `docs/architecture.md` (Curation bullet), `docs/frontend/features.md` if it lists triage options

- [ ] **Step 1:** docs; `pytest -q` (with `TEST_DATABASE_URL`), ruff, format, mypy, frontend gates — all green.
- [ ] **Step 2:** commit `docs: AI reputation of labels and artists`; PR via caveman-commit; checks → merge → Deploy (two-phase: migration before API Lambda).
- [ ] **Step 3:** prod check (read-only role): level counts match the spec's ballpark (labels ~146/108/438, artists ~74/181/2 084); no `ERROR` in `clouder-prod-collector-api` logs after deploy.

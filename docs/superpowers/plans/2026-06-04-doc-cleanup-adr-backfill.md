# Documentation Cleanup + ADR Backfill (round 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distill 5 ADRs (0016–0020) from the architectural mid-May–June superpowers specs, then archive all 29 batch specs, delete the 34 executed plans, repair 2 cross-references, and update the ADR index — leaving `docs/superpowers/{plans,specs}/` as empty `.gitkeep` staging dirs.

**Architecture:** Pure documentation change. No code, no tests, no build. Verification is `grep` / file-presence checks, not `pytest`. ADRs are written **first** (while the source specs are still in `docs/superpowers/specs/`), then the file moves/deletes happen, then the index update. Two commits: (1) ADRs + index, (2) archive/delete/link-fix.

**Tech Stack:** Markdown, `git mv` / `git rm`, the `caveman:caveman-commit` skill for commit messages (CLAUDE.md policy). Branch `docs/adr-backfill-cleanup` (already created off `origin/main`; the design spec is already committed as `2013393`).

**Spec:** `docs/superpowers/specs/2026-06-04-doc-cleanup-adr-backfill-design.md`

---

## File structure

**Create**
- `docs/adr/0016-label-enrichment.md`
- `docs/adr/0017-artist-enrichment.md`
- `docs/adr/0018-triage-buckets.md`
- `docs/adr/0019-youtube-music-vendor.md`
- `docs/adr/0020-canonical-entity-routes.md`
- `docs/superpowers/plans/.gitkeep`, `docs/superpowers/specs/.gitkeep` (re-tracked after the dirs empty out)

**Modify**
- `docs/adr/README.md` — index rows 0016–0020 + bump "next free number" to `0021`.
- `experiments/labels/README.md:7` — repoint spec link to the archive.
- `experiments/artists/README.md:7` — repoint spec link to the archive.

**Move** (`git mv` → `docs/archive/specs/`)
- All 29 batch specs in `docs/superpowers/specs/` **except** the working design spec, then the working spec last.

**Delete** (`git rm`)
- All 34 plans in `docs/superpowers/plans/` **except** this working plan, then this working plan last.

No new files, no backend/frontend/router change, no tests.

---

### Task 1: Write ADR-0016 — Label enrichment subsystem

**Files:**
- Create: `docs/adr/0016-label-enrichment.md`

- [ ] **Step 1: Create the ADR file**

Write `docs/adr/0016-label-enrichment.md` with exactly this content:

```markdown
# ADR-0016: Label enrichment subsystem (multi-vendor consensus, async)
Status: Accepted
Date: 2026-06-04

## Context

The original label-search subsystem was Perplexity-only, single-prompt, auto-fired
during Beatport ingest. It shipped fragile signals and clogged the canonical schema,
and it was removed wholesale. A sandbox at `experiments/labels/` produced a stronger
multi-vendor pipeline (Gemini, OpenAI, Tavily+DeepSeek) with a consensus aggregator
and a richer `LabelInfo` schema (tagline, status, primary styles, social URLs).

Two forces shaped the production design. A single run of N labels × M vendors blows
through the API Gateway 29-second budget (Gemini alone averages ~58 s per call), so
the work must be asynchronous. And label profiles should be enriched automatically as
users curate, not only when an admin runs a batch by hand.

## Decision

A new `src/collector/label_enrichment/` package owns the subsystem.

- **Multi-vendor consensus.** The worker calls all configured vendors in parallel
  (`ThreadPoolExecutor`) for one label; an aggregator picks per-field winners
  (majority vote for facts, a single LLM call for the narrative).
- **Async via SQS, one message per label.** The API Lambda inserts a runs row and
  enqueues one message per label; the worker processes them (mirrors the Beatport
  ingest pattern). Per-label (not per-cell) granularity keeps every cell for a label
  in one place for `merge_cells` and stays within the 15-min Lambda budget
  (~60–90 s/label observed). SQS reserved concurrency (default 10) caps cross-label
  parallelism.
- **Persistence + provenance.** `clouder_label_enrichment_runs`, `_cells`, and
  `clouder_label_info` (full merged `LabelInfo` as JSONB plus denormalized
  filter/sort columns). `is_ai_suspected` on `clouder_labels` is re-populated as a
  denormalized projection of the new pipeline.
- **Auto-enrich = inline best-effort (approach A).** A helper is called from the
  curation path *after* commit and only enqueues work (a few Data API calls + an SQS
  batch, sub-second). The LLM search runs in the background worker; curation never
  waits and an auto-enrich failure never breaks curation. Dedup uses
  `label_auto_enrich_state` (atomic claim, attempts counter, in-flight guard): skip
  if a merged result exists or a search is in-flight; exactly one retry on failure.
  A singleton `auto_enrich_config` (per kind) master toggle defaults OFF. Runs are
  tagged `source='manual'|'auto'`.
- **User preferences.** `clouder_user_label_prefs` (`user_id`, `label_id`, `status`
  in `liked`/`disliked`, PK `(user_id, label_id)`). `PUT /labels/{id}/preference`
  and `GET /me/label-preferences`. Absence of a row means `none`; writing `none`
  deletes the row.

## Consequences

- Vendor cost scales with labels × vendors; reserved concurrency is the throttle.
- `is_ai_suspected` is a denormalized projection — re-derive it whenever label info
  changes; do not treat it as a source of truth.
- Auto-enrich is intentionally post-commit and best-effort; keep it off the
  critical path.
- This shape is mirrored one-to-one by artist enrichment (ADR-0017). Relates to
  ADR-0008 (`is_ai_suspected` soft flag).

**Cross-references:** `../data/search-and-enrichment.md`, `../data/data-model.md`,
`../backend/handlers.md`, `../frontend/features.md`. Source specs (now archived):
`../archive/specs/2026-05-17-label-ai-sandbox-design.md`,
`../archive/specs/2026-05-18-label-enrichment-backend-design.md`,
`../archive/specs/2026-05-18-label-enrichment-pipeline-design.md`,
`../archive/specs/2026-05-19-label-frontend-design.md`,
`../archive/specs/2026-05-19-user-label-preferences-design.md`,
`../archive/specs/2026-05-25-auto-label-enrichment-design.md`.
```

- [ ] **Step 2: Verify the file opens with the template header**

Run: `head -3 docs/adr/0016-label-enrichment.md`
Expected:
```
# ADR-0016: Label enrichment subsystem (multi-vendor consensus, async)
Status: Accepted
Date: 2026-06-04
```

---

### Task 2: Write ADR-0017 — Artist enrichment

**Files:**
- Create: `docs/adr/0017-artist-enrichment.md`

- [ ] **Step 1: Create the ADR file**

Write `docs/adr/0017-artist-enrichment.md` with exactly this content:

```markdown
# ADR-0017: Artist enrichment mirrors label enrichment (parallel package, not shared engine)
Status: Accepted
Date: 2026-06-04

## Context

Once label enrichment (ADR-0016) shipped, artists needed the same treatment:
per-artist AI-researched info, auto-population on curation, and a full admin + read +
preference API. The `artist_v1` prompt and `ArtistInfo` schema were validated in the
`experiments/artists/` sandbox (PR #148/#149) and are ported into production.

The one structural difference from labels: labels are one-to-many with tracks
(`track.album_id → album.label_id`), while artists are **many-to-many** via
`clouder_track_artists(track_id, artist_id, role)`. All roles (main / feat /
producer / remixer) are enriched, so artist resolution returns a set per track.

## Decision

Approach **A**: a new `src/collector/artist_enrichment/` package that mirrors
`label_enrichment` module-for-module, swapping the entity (`artist_id`, M2M) and the
payload schema (`ArtistInfo`).

- **Rejected alternatives.** (B) Generalizing `label_enrichment` into a shared engine
  — too high a regression risk to working production code. (C) Extracting a thin
  shared base — modest DRY gain for real refactor cost. Generalization is revisited
  only if a third enrichable entity appears.
- **Reuse / port / new.** *Reuse* (import, no copy): `label_enrichment.vendors.*`
  adapters (schema-agnostic `run(system, user, schema, model)`) and `pricing`.
  *Port* from the sandbox: `ArtistInfo` schema/enums, the `artist_v1` prompt, the
  artist-tuned consensus aggregator. *New* (mirror with entity swap): repository,
  auto_repository, orchestrator, messages, routes, settings, handler, worker.
- **Data model** mirrors label: `clouder_artist_enrichment_runs` / `_cells` /
  `clouder_artist_info` (full `ArtistInfo` as JSONB + denormalized status,
  `primary_styles` GIN, artist_type, country, active_since, tagline). FK to
  `clouder_artists.id`, which already carries `is_ai_suspected`.
- **Full parity** with labels: admin backlog/enqueue/auto-config/runs, user
  preferences (like/dislike + "my artists"), AI-flag projection onto
  `clouder_artists.is_ai_suspected`, async SQS worker + auto-dispatch.
- **Frontend** (shipped as sub-project 2, PR #150): parallel artist-prefixed
  components reusing the entity-agnostic pieces (`EnrichConfigForm`, `EnqueueDrawer`,
  `BacklogTable`, the AI-badge markup, the `api<T>()` client, query patterns). The
  one genuinely new component is `ArtistsPanel` (main artist as a full `ArtistTile`
  card + every other artist as a chip) on all three players. A small backend touch
  adds `artists: [{id, name, role}]` to the bucket-tracks response so the triage
  player can resolve artist ids.

## Consequences

- Two near-identical enrichment packages now exist. The duplication is deliberate
  (isolation, zero risk to the working label path); a shared engine is the documented
  escape hatch if a third entity arrives.
- Many-to-many resolution means a track fans out to a set of artists, so artist
  enrichment costs more vendor calls per track than labels.
- Relates to ADR-0016 (the mirrored pattern) and ADR-0008.

**Cross-references:** `../data/search-and-enrichment.md`, `../data/data-model.md`,
`../frontend/features.md`. Source specs (now archived):
`../archive/specs/2026-05-26-artist-search-design.md`,
`../archive/specs/2026-05-27-artist-enrichment-backend-design.md`,
`../archive/specs/2026-05-27-artist-enrichment-frontend-design.md`,
`../archive/specs/2026-05-27-improve-artists-design.md`.
```

- [ ] **Step 2: Verify the header**

Run: `head -3 docs/adr/0017-artist-enrichment.md`
Expected: line 1 `# ADR-0017: Artist enrichment mirrors label enrichment (parallel package, not shared engine)`, line 2 `Status: Accepted`, line 3 `Date: 2026-06-04`.

---

### Task 3: Write ADR-0018 — Triage buckets

**Files:**
- Create: `docs/adr/0018-triage-buckets.md`

- [ ] **Step 1: Create the ADR file**

Write `docs/adr/0018-triage-buckets.md` with exactly this content:

```markdown
# ADR-0018: Triage staging-bucket auditioning + create-time classification (incl. FAV)
Status: Accepted
Date: 2026-06-04

## Context

Triage sorts incoming tracks into per-category staging buckets plus technical buckets
(NEW / OLD / NOT / UNCLASSIFIED / DISCARD). Two needs emerged: audition what is staged
before finalizing, and route tracks more intelligently at block creation. The
bucket-tracks API and a generic `PlaybackProvider` queue (`QueueSource` of
`type:'bucket'`) already existed. Classification was a hardcoded `CASE`: the
disliked-label rule defaulted off, there was no disliked-artist rule, and liked
material was scattered across NEW/OLD.

## Decision

- **Listen to bucket tracks.** A per-row Play button + a player panel on the
  bucket-detail page, mirroring `CategoryDetailPage`. `useBucketPlayerQueue` binds the
  visible bucket tracks to the singleton playback queue (cursor recompute / shrink
  logic copied from the category hook). Auditioning is read-only — no moves, no
  category writes. Play is enabled on **all** buckets (staging *and* technical);
  mobile uses a nested fullscreen `/player` route. Frontend-only, no API change.
- **Quick distribution in the bucket player.** A lean row of destination buttons —
  staging categories (excluding the current bucket) + DISCARD only; no Force mode, no
  hotkeys, no NEW/OLD/NOT. Tapping moves the currently-playing track and auto-advances.
  It reuses `POST /triage/blocks/{id}/move` and the optimistic `useMoveTracks`. The
  panel self-fetches the block via `useTriageBlock` so it works identically on the
  desktop split and the mobile route. Gated on block status `IN_PROGRESS` + a track
  playing. A triage-local button component is used (not Curate's `DestinationGrid`) to
  avoid a circular `triage ↔ curate` dependency.
- **Create-time classification.** A single `INSERT … SELECT` with a first-match-wins
  `CASE`: (1) liked label OR liked artist → FAV `[include_favorites]`; (2) disliked
  label OR artist → NOT `[include_disliked_labels / _artists]`; (3) null release date
  → UNCLASSIFIED; (4) old → OLD; (5) compilation → NOT `[compilations_to_not]`;
  (6) else → NEW. A new `FAV` technical bucket collects liked material. Likes win over
  dislikes by design. All four toggles default ON; when a toggle is OFF its
  subquery/branch is not emitted and its parameters are not bound.

## Consequences

- Auditioning rides the generic playback queue; the shrink/clamp cursor logic is
  duplicated from the category hook and must be kept in sync.
- Quick-distribute is deliberately leaner than Curate (no Force/hotkeys); undo restores
  the moved track to the bucket but does not rewind playback.
- `FAV` is a new technical bucket; finalize/move/transfer treat it like other staging
  surfaces.
- Relates to ADR-0010 (tap-to-assign) and ADR-0012 (optimistic shrink).

**Cross-references:** `../frontend/features.md`, `../frontend/playback.md`. Source
specs (now archived):
`../archive/specs/2026-05-20-triage-listen-buckets-design.md`,
`../archive/specs/2026-05-21-bucket-player-distribute-design.md`,
`../archive/specs/2026-05-27-triage-block-classification-design.md`.
```

- [ ] **Step 2: Verify the header**

Run: `head -3 docs/adr/0018-triage-buckets.md`
Expected: line 1 `# ADR-0018: Triage staging-bucket auditioning + create-time classification (incl. FAV)`, line 2 `Status: Accepted`, line 3 `Date: 2026-06-04`.

---

### Task 4: Write ADR-0019 — YouTube Music vendor

**Files:**
- Create: `docs/adr/0019-youtube-music-vendor.md`

- [ ] **Step 1: Create the ADR file**

Write `docs/adr/0019-youtube-music-vendor.md` with exactly this content:

```markdown
# ADR-0019: YouTube Music as a second vendor (match + publish), mirrored not shared
Status: Accepted
Date: 2026-06-04

## Context

YouTube Music is the first non-Spotify vendor. Two surfaces were needed: track
**matching** (so a user sees the corresponding YT Music track) and playlist
**publish** (parity with the existing Spotify publish). The provider abstraction —
`LookupProvider` / `ExportProvider` Protocols, `VendorTrackRef`, a registry behind the
`VENDORS_ENABLED` gate (ADR-0004) — and the `vendor_match` worker (ISRC fast-path →
metadata fuzzy → scorer → confidence threshold → review queue), `vendor_track_map`,
and `match_review_queue` already existed.

Key constraint: YouTube Music exposes no public ISRC search, so the ISRC fast-path
never fires for YT. Matching is metadata-fuzzy only, and a meaningful share of tracks
fall below threshold into the review queue.

## Decision

- **Matching.** Implement `providers/ytmusic/{lookup,export}` using `ytmusicapi`
  (unauthenticated search). Enqueue match jobs on playlist track-add, on Spotify
  import, and via a one-off backfill of existing playlist tracks. Below-threshold
  results store the top-5 candidates in `match_review_queue`. `vendor_track_map` is
  keyed `(clouder_track_id, vendor)`, so a YT Music match is shared across all users
  (canonical-core model). The fuzzy scorer is left unchanged.
- **Match review (user-facing).** A regular user resolves `needs_review` matches
  inline from the playlist (click the badge): accept one of the top-5 candidates,
  paste a YT Music link (videoId is format-validated only — no existence check), or
  mark "not on YT". Resolution writes the canonical `vendor_track_map`
  (`match_type='manual'`, confidence 1.0). No admin screen — the small DJ circle
  reviews its own playlists.
- **Publish.** Mirror the Spotify publish path one-to-one with **separate** YouTube
  Music classes; do **not** refactor the working Spotify path into a shared base
  (lower risk; extract later if a third vendor appears). Uses `ytmusicapi`
  authenticated + Google **device-flow** OAuth ("TVs and Limited Input devices"). The
  app-level `client_id`/`client_secret` live in Secrets Manager / SSM; per user we
  persist only the encrypted refresh token. The OAuth app stays in Google "testing"
  mode (≤100 users). Republish is edit-in-place (stable playlist URL). Publish runs
  synchronously in the curation Lambda (mirrors Spotify). Publish state is stored as
  mirrored `ytmusic_*` columns on `playlists` (not a normalized table). The
  `device_code` is client-held between request and poll (backend stateless), like the
  Spotify PKCE verifier. No custom cover (YT Music has no cover API).

## Consequences

- No ISRC → a lower auto-match rate than Spotify; the review queue is a permanent,
  expected surface, not an edge case.
- `ytmusicapi` is an unofficial internal API (ToS grey area) — accepted for the small
  audience.
- "Testing"-mode OAuth means a ~7-day refresh-token expiry, so users re-connect
  roughly weekly, and each must be added as a Google test user.
- Two parallel publish paths (Spotify + YT Music) with no shared base — intentional; a
  shared base is the documented future option.
- Relates to ADR-0004 (provider abstraction), ADR-0006 (Spotify metadata fallback),
  ADR-0011 (Spotify token bundling).

**Cross-references:** `../backend/providers.md`, `../data/data-model.md`. Source specs
(now archived):
`../archive/specs/2026-05-30-ytmusic-vendor-search-design.md`,
`../archive/specs/2026-05-30-ytmusic-match-review-design.md`,
`../archive/specs/2026-05-31-youtube-music-publish-design.md`.
```

- [ ] **Step 2: Verify the header**

Run: `head -3 docs/adr/0019-youtube-music-vendor.md`
Expected: line 1 `# ADR-0019: YouTube Music as a second vendor (match + publish), mirrored not shared`, line 2 `Status: Accepted`, line 3 `Date: 2026-06-04`.

---

### Task 5: Write ADR-0020 — Canonical entity routes

**Files:**
- Create: `docs/adr/0020-canonical-entity-routes.md`

- [ ] **Step 1: Create the ADR file**

Write `docs/adr/0020-canonical-entity-routes.md` with exactly this content:

```markdown
# ADR-0020: Canonical top-level routes for artist/label detail pages
Status: Accepted
Date: 2026-06-04

## Context

Artist and label detail pages were reachable only through style-scoped routes
(`/library/:styleId/artists/:artistId`, `/library/:styleId/labels/:labelId`). The
`styleId` was used only for the URL guard and the "← Back to {style}" link — the data
fetch ignores it (`GET /artists/{id}` and `GET /labels/{id}` take no style). Because
the route required a `styleId`, any context with no single style — the playlist player
panel above all — could not build the URL, so artist/label names rendered as plain
text instead of links.

## Decision

Move the detail pages to top-level canonical routes: `/artists/:artistId` and
`/labels/:labelId`. Any context now links to them unconditionally, and the conditional
`styleId` link plumbing (the optional `styleId` prop on `ArtistTile`/`LabelTile`)
disappears. Back navigation uses browser history (`navigate(-1)`) with a `/library`
fallback for deep links / new tabs. Library **list** pages stay style-scoped
(`/library/:styleId`, `/library/:styleId/artists`) — an intentional browse-by-style
surface whose list endpoints filter by `?style=`. Frontend-only: no backend, API, DB,
or OpenAPI change (the id-only endpoints already exist).

## Consequences

- Clean URL split: `/library/...` is browse-by-style, `/artists` & `/labels` are
  entity pages. No collision with `:styleId`.
- Old style-scoped detail URLs are removed; an external bookmark to
  `/library/:styleId/artists/:id` breaks. Acceptable — internal app only.
- Relates to ADR-0009 (frontend stack / routing).

**Cross-references:** `../frontend/features.md`. Source spec (now archived):
`../archive/specs/2026-06-02-decouple-artist-label-from-style-design.md`.
```

- [ ] **Step 2: Verify the header**

Run: `head -3 docs/adr/0020-canonical-entity-routes.md`
Expected: line 1 `# ADR-0020: Canonical top-level routes for artist/label detail pages`, line 2 `Status: Accepted`, line 3 `Date: 2026-06-04`.

---

### Task 6: Update the ADR index + commit ADRs

**Files:**
- Modify: `docs/adr/README.md`

- [ ] **Step 1: Bump the "next free number"**

In `docs/adr/README.md`, replace:
```
Four-digit, monotonic, never reused. The next free number is `0016`.
```
with:
```
Four-digit, monotonic, never reused. The next free number is `0021`.
```

- [ ] **Step 2: Append the five index rows**

In `docs/adr/README.md`, after the existing `| 0015 | ... |` row in the Index table, append exactly these five rows:
```
| 0016 | [Label enrichment subsystem (multi-vendor consensus, async)](0016-label-enrichment.md) |
| 0017 | [Artist enrichment mirrors label enrichment](0017-artist-enrichment.md)                  |
| 0018 | [Triage bucket auditioning + create-time classification](0018-triage-buckets.md)         |
| 0019 | [YouTube Music as a second vendor (match + publish)](0019-youtube-music-vendor.md)       |
| 0020 | [Canonical top-level artist/label routes](0020-canonical-entity-routes.md)               |
```

- [ ] **Step 3: Verify index integrity**

Run: `grep -E '^\| 00(1[6-9]|20) ' docs/adr/README.md | wc -l` and `grep -c '0021' docs/adr/README.md`
Expected: first → `5`; second → `1`.

- [ ] **Step 4: Verify every index link resolves to a real file**

Run:
```bash
for n in 16 17 18 19 20; do f=$(ls docs/adr/00$n-*.md); test -f "$f" && echo "ok $f" || echo "MISSING 00$n"; done
```
Expected: five `ok …` lines, no `MISSING`.

- [ ] **Step 5: Commit the ADRs + index**

Generate the commit message with the `caveman:caveman-commit` skill (CLAUDE.md policy — never hand-write the subject), then:
```bash
git add docs/adr/0016-label-enrichment.md docs/adr/0017-artist-enrichment.md \
        docs/adr/0018-triage-buckets.md docs/adr/0019-youtube-music-vendor.md \
        docs/adr/0020-canonical-entity-routes.md docs/adr/README.md
git commit -m "$(cat <<'EOF'
docs(adr): add ADR-0016..0020 from superpowers specs

Distill the mid-May–June architectural specs into per-subsystem
ADRs: label enrichment, artist enrichment, triage buckets,
YouTube Music vendor, canonical entity routes.
EOF
)"
```
Expected: commit succeeds; the PreToolUse hook passes (Conventional Commits, no AI trailer).

---

### Task 7: Archive the 29 batch specs

**Files:**
- Move: `docs/superpowers/specs/*.md` (except the working spec) → `docs/archive/specs/`

- [ ] **Step 1: `git mv` every batch spec except the working design spec**

Run (from the repo root):
```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/arch_improve
for f in docs/superpowers/specs/*.md; do
  [ "$(basename "$f")" = "2026-06-04-doc-cleanup-adr-backfill-design.md" ] && continue
  git mv "$f" docs/archive/specs/
done
```

- [ ] **Step 2: Verify exactly the working spec remains in superpowers/specs**

Run: `ls docs/superpowers/specs/`
Expected: only `2026-06-04-doc-cleanup-adr-backfill-design.md`.

- [ ] **Step 3: Verify the archive grew by 29**

Run: `ls docs/archive/specs/*.md | wc -l`
Expected: `60` (31 prior + 29 just moved).

---

### Task 8: Repair the two live cross-references

**Files:**
- Modify: `experiments/labels/README.md:7`
- Modify: `experiments/artists/README.md:7`

- [ ] **Step 1: Repoint the labels README**

In `experiments/labels/README.md`, replace:
```
Design spec: `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`
```
with:
```
Design spec: `docs/archive/specs/2026-05-17-label-ai-sandbox-design.md`
```

- [ ] **Step 2: Repoint the artists README**

In `experiments/artists/README.md`, replace:
```
Design spec: `docs/superpowers/specs/2026-05-26-artist-search-design.md`
```
with:
```
Design spec: `docs/archive/specs/2026-05-26-artist-search-design.md`
```

- [ ] **Step 3: Verify no live reference points at the old superpowers spec/plan paths**

Run: `grep -rn "docs/superpowers/\(specs\|plans\)" . --include="*.md" | grep -v "docs/archive/"`
Expected: only matches inside `docs/superpowers/specs/2026-06-04-doc-cleanup-adr-backfill-design.md` and `docs/superpowers/plans/2026-06-04-doc-cleanup-adr-backfill.md` (the working spec/plan, which describe the paths). No hit in `experiments/` or any topical doc.

---

### Task 9: Delete the 34 executed plans

**Files:**
- Delete: `docs/superpowers/plans/*.md` (except this working plan)

- [ ] **Step 1: `git rm` every plan except this working plan**

Run (from the repo root):
```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/arch_improve
for f in docs/superpowers/plans/*.md; do
  [ "$(basename "$f")" = "2026-06-04-doc-cleanup-adr-backfill.md" ] && continue
  git rm "$f"
done
```

- [ ] **Step 2: Verify exactly the working plan remains**

Run: `ls docs/superpowers/plans/`
Expected: only `2026-06-04-doc-cleanup-adr-backfill.md`.

- [ ] **Step 3: Re-track the empty plans dir**

Run:
```bash
touch docs/superpowers/plans/.gitkeep
git add docs/superpowers/plans/.gitkeep
```
Expected: `.gitkeep` staged (it will keep the dir tracked once the working plan is removed in Task 10).

---

### Task 10: Archive the working spec, remove the working plan, finalize

**Files:**
- Move: `docs/superpowers/specs/2026-06-04-doc-cleanup-adr-backfill-design.md` → `docs/archive/specs/`
- Delete: `docs/superpowers/plans/2026-06-04-doc-cleanup-adr-backfill.md`
- Create: `docs/superpowers/specs/.gitkeep`

> Run this task **last** — it removes the plan you are executing from. By this point
> every other task is done, so nothing else reads the plan file.

- [ ] **Step 1: Archive the working design spec**

Run:
```bash
git mv docs/superpowers/specs/2026-06-04-doc-cleanup-adr-backfill-design.md docs/archive/specs/
touch docs/superpowers/specs/.gitkeep
git add docs/superpowers/specs/.gitkeep
```

- [ ] **Step 2: Remove this working plan**

Run: `git rm docs/superpowers/plans/2026-06-04-doc-cleanup-adr-backfill.md`

- [ ] **Step 3: Full verification sweep**

Run each and confirm the expected output:
```bash
ls docs/superpowers/plans/            # expect: only .gitkeep
ls docs/superpowers/specs/            # expect: only .gitkeep
ls docs/adr/00{16,17,18,19,20}-*.md   # expect: the five ADR files
ls docs/archive/specs/*.md | wc -l    # expect: 61
grep -c '0021' docs/adr/README.md     # expect: 1
grep -rn "docs/superpowers/\(specs\|plans\)/2026" . --include="*.md" | grep -v docs/archive
                                      # expect: no output (all references gone with the working files)
```

- [ ] **Step 4: Commit the cleanup**

Generate the message with `caveman:caveman-commit`, then:
```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: archive superpowers specs, remove executed plans

Archive the mid-May–June design specs to docs/archive/specs, delete
the 34 executed implementation plans, and repoint the two experiment
READMEs at the archived spec paths. Decisions now live in ADR-0016..0020.
EOF
)"
```
Expected: commit succeeds; hook passes.

- [ ] **Step 5: Confirm a clean tree**

Run: `git status --short`
Expected: empty (everything committed).

---

## Notes on execution

- **No tests / no build.** This plan touches only `docs/` and two `experiments/*/README.md` files. Do not run `pytest`, `pnpm`, or `terraform`.
- **Commit messages go through `caveman:caveman-commit`** per CLAUDE.md, then `git commit -m`. Multi-line bodies use the heredoc form shown. No `Co-Authored-By` trailer (the hook strips/blocks it).
- **Branch** `docs/adr-backfill-cleanup` is already created off `origin/main`; the design spec is already committed (`2013393`). Do not re-branch.
- **Finishing:** after Task 10, the work is ready for a PR (title/body via `caveman:caveman-commit`) — see `superpowers:finishing-a-development-branch`.

# Documentation Cleanup + ADR Backfill (round 2) — Design Spec

**Date:** 2026-06-04
**Status:** Approved (design), pending implementation plan
**Author:** brainstorming session

## Goal

Repeat the documentation lifecycle established by
`docs/archive/specs/2026-05-17-documentation-overhaul-design.md` (Goal #3:
*"Historical implementation plans are removed and historical design specs are
archived; long-lived architectural decisions are distilled into a small set of
ADRs"*), applying it to the mid-May–June 2026 batch of superpowers artifacts:
**34 plans + 29 design specs**.

Concretely:

1. Delete all implementation plans under `docs/superpowers/plans/` — they are
   executed and shipped, and recoverable from git history.
2. Archive all design specs under `docs/superpowers/specs/` to
   `docs/archive/specs/`, alongside the ~30 already-archived earlier specs.
3. Distill the architecturally load-bearing specs into **5 new ADRs**
   (0016–0020), one per subsystem, following the existing
   `docs/adr/README.md` template.
4. Keep `docs/superpowers/{plans,specs}/` as empty staging dirs (with
   `.gitkeep`) so future `brainstorming` / `writing-plans` output has a home.
5. Repair the two live cross-references that point into the moved specs.

## Non-Goals

- **No content rewrite of the specs.** They are archived as-is for historical
  reference. ADRs are distilled separately, not copied.
- **No ADRs for cosmetic / pure-UI specs.** Only subsystem-level architectural
  decisions get an ADR (see classification below).
- **No new lifecycle conventions** (review cadence, ownership). Out of scope.
- **No changes to topical docs** (`docs/backend/`, `docs/frontend/`, etc.)
  beyond the new ADRs cross-referencing them.

## Current state (verified)

- `docs/superpowers/plans/` — 34 implementation plans (2026-05-17 → 2026-06-04).
  Each is a checkbox task list. No live doc links to any plan. 8 of them
  (`triage-populate-options`, `artist-search-experiment`, the six
  `artist-enrichment-{1a..2c}`) have no standalone spec — plans split finer than
  specs; they delete cleanly with the rest.
- `docs/superpowers/specs/` — 29 design specs from the batch (2026-05-17 →
  2026-06-04), plus this working spec (30 files in the dir during execution).
- `docs/archive/specs/` — already exists, 31 prior specs + a `.gitkeep`. This is
  the established archive location ("к остальным").
- `docs/adr/` — ADRs 0001–0015 accepted. Index in `README.md`. Next free
  number = `0016`. The May player/curate specs were already back-filled into
  ADRs 0010, 0012, 0013, 0015 during the round-1 overhaul.
- **Live cross-references into the superpowers paths (only two):**
  - `experiments/labels/README.md:7` → `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`
  - `experiments/artists/README.md:7` → `docs/superpowers/specs/2026-05-26-artist-search-design.md`
  - Both point at **specs** (which we move, not delete). No link points at a plan.
- **Subsystem code exists and is shipped** (verified by grep), so all 5 ADRs
  describe shipped reality and are `Status: Accepted`, not speculative:
  - `src/collector/label_enrichment/`
  - `src/collector/artist_enrichment/` (incl. `routes.py` — production-wired)
  - ytmusic: `src/collector/curation/youtube_data_api_client.py`, `curation_handler.py`
  - triage buckets: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
  - routes: `frontend/src/features/library/routes/{ArtistDetailPage,LabelDetailPage}.tsx`, `frontend/src/routes/router.tsx`

## Spec classification

All 29 batch specs are **archived** regardless of class (plus this working spec,
moved last). The class only decides which specs feed an ADR.

### Architectural → feed an ADR (17 specs → 5 ADRs)

| ADR | Title | Distilled from (specs) | Related ADRs |
|-----|-------|------------------------|--------------|
| 0016 | Label enrichment subsystem | `2026-05-17-label-ai-sandbox`, `2026-05-18-label-enrichment-backend`, `2026-05-18-label-enrichment-pipeline`, `2026-05-19-label-frontend`, `2026-05-19-user-label-preferences`, `2026-05-25-auto-label-enrichment` | 0008 |
| 0017 | Artist enrichment subsystem (mirrors label) | `2026-05-26-artist-search`, `2026-05-27-artist-enrichment-backend`, `2026-05-27-artist-enrichment-frontend`, `2026-05-27-improve-artists` | 0016 |
| 0018 | Triage listen-buckets + block classification | `2026-05-20-triage-listen-buckets`, `2026-05-21-bucket-player-distribute`, `2026-05-27-triage-block-classification` | 0010, 0012 |
| 0019 | YouTube Music as second publish vendor | `2026-05-30-ytmusic-vendor-search`, `2026-05-30-ytmusic-match-review`, `2026-05-31-youtube-music-publish` | 0004, 0006, 0011 |
| 0020 | Canonical top-level artist/label routes | `2026-06-02-decouple-artist-label-from-style` | 0009 |

### Cosmetic / feature → archived only, no ADR (12 batch specs + this spec)

`2026-05-21-desktop-design-tweaks`, `2026-05-21-distribution-buttons-style`,
`2026-05-21-player-polish`, `2026-05-22-sticky-player`,
`2026-05-22-tags-add-via-player`, `2026-05-23-category-tags-ux`,
`2026-05-23-player-focus-and-checkmark`, `2026-05-23-tag-pill-sizing`,
`2026-05-24-playlist-detail-parity`, `2026-05-24-playlist-page-visual-tuning`,
`2026-06-02-copy-playlist-json`, `2026-06-04-library-admin-style-unification`,
and this spec itself (`2026-06-04-doc-cleanup-adr-backfill`).

> Rationale: these are one-shot execution artifacts whose lasting content already
> lives in shipped CSS / components — the same "throwaway after execution" nature
> as plans. They carry no load-bearing architectural decision.

## ADR authoring rules

Each new ADR (0016–0020):

- Follows the `docs/adr/README.md` template exactly: `# ADR-NNNN: <title>`,
  `Status: Accepted`, `Date: 2026-06-04`, then `## Context`, `## Decision`,
  `## Consequences`.
- Is ≤ 2 pages. Captures *why*, not implementation detail.
- Describes shipped reality (verified above), in present tense.
- Ends with a **Cross-references** line pointing at the relevant topical docs
  (`../backend/…`, `../frontend/…`, `../data/…`) and the source specs in their
  new archive location (`../archive/specs/<file>.md`).
- Names related ADRs inline per the table above.

File names follow the existing kebab pattern:
`0016-label-enrichment.md`, `0017-artist-enrichment.md`,
`0018-triage-buckets.md`, `0019-youtube-music-vendor.md`,
`0020-canonical-entity-routes.md`.

## File operations

1. **Write ADRs first** (while specs are still in `docs/superpowers/specs/` for
   easy reference): create `docs/adr/0016-…` … `0020-…`.
2. **Archive the 29 batch specs:** `git mv` every spec in
   `docs/superpowers/specs/` **except this working spec**
   (`2026-06-04-doc-cleanup-adr-backfill-design.md`) into `docs/archive/specs/`.
   This working spec stays put until step 6.
3. **Fix links:** update the two `experiments/*/README.md` lines to
   `docs/archive/specs/…`.
4. **Delete plans:** `git rm docs/superpowers/plans/*.md`. Then ensure
   `docs/superpowers/plans/.gitkeep` exists.
5. **Update ADR index:** in `docs/adr/README.md`, add rows 0016–0020 to the
   Index table and change "The next free number is `0016`." → `0021`.
6. **Archive this spec** as the final doc move (matching how
   `2026-05-17-documentation-overhaul-design.md` ended up in `docs/archive/specs/`).
   Then ensure `docs/superpowers/specs/.gitkeep` exists so the now-empty dir is
   tracked.

**Order matters:** ADRs are written before the specs move so the source material
is in its expected place during authoring. Link fixes and the index update happen
after the moves so they point at final paths.

## Verification

- `grep -rn "docs/superpowers/\(specs\|plans\)" . --include="*.md"` returns no
  hits outside the archive itself (all live links repaired).
- `docs/superpowers/plans/` contains only `.gitkeep`.
- `docs/superpowers/specs/` contains only `.gitkeep` (after this spec is moved).
- `docs/adr/` contains 0001–0020 + README; README index lists all 20 and says
  next free number `0021`.
- All 29 batch specs + this working spec present in `docs/archive/specs/`
  (`docs/archive/specs/` grows from 31 to 61 `.md` files).
- ADRs 0016–0020 each open with the template header and end with a
  Cross-references line.

## Commit

Single commit (or a small logical sequence) via the `caveman:caveman-commit`
skill per CLAUDE.md policy. Branch off `origin/main` with a `docs/` prefix
(e.g. `docs/adr-backfill-cleanup`). No `Co-Authored-By` trailer.

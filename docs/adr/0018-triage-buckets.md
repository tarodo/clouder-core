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

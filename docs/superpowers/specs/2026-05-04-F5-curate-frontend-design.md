# F5 — Curate Frontend

**Date:** 2026-05-04
**Status:** brainstorm stage — design awaiting user approval before implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F5**.
**Backend prerequisite:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) §5.6 (`GET /triage/blocks/{id}/buckets/{bucket_id}/tracks`) and §5.7 (`POST /triage/blocks/{id}/move`) — both shipped; spec-D Data API hotfix (lessons-learned #27) merged with F3a, verified live.
**Frontend prerequisites:**

- [`2026-05-03-F3a-triage-detail-frontend-design.md`](./2026-05-03-F3a-triage-detail-frontend-design.md) — F3a merged 2026-05-03 (provides `useBucketTracks`, `useMoveTracks` with optimistic + undo + cache sweep, `useTriageBlock`, `bucketLabels.ts` helpers).
- [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — F2 merged 2026-05-03 (provides `useTriageBlocksByStyle` + `byStyle` cache key, used by index/style-resume routes).
- [`2026-05-01-F1-categories-frontend-design.md`](./2026-05-01-F1-categories-frontend-design.md) — F1 merged 2026-05-02 (provides `useStyles`, style-scoped routing pattern, `lastVisitedTriageStyle` storage shape mirrored here).
- [`2026-05-03-F4-triage-finalize-frontend-design.md`](./2026-05-03-F4-triage-finalize-frontend-design.md) — F4 merged 2026-05-03 (terminal CTA "Finalize block" on EndOfQueue links into F4's modal flow).

**Successor blockers:** F6 PlayerCard (replaces F5's Spotify deep-link with embedded SDK; `Space` hotkey graduates from no-op to play/pause). F8 Home (cross-feature sticky bar will subsume `?` overlay shortcut into a global help surface — F5 ships its own overlay first).

**Design pack reference:** `docs/design_handoff/03 Pages catalog · Pass 2 (Curate-Patterns).html` artboards **P-22** (Curate mobile) and **P-23** (Curate desktop, 1440 width). Theme tokens via `docs/design_handoff/tokens.css` and `theme.ts` already in place; `accent-magenta` modifier class is applied during the Curate route only.

**Open-questions tie-ins:** [`docs/design_handoff/OPEN_QUESTIONS.md`](../../design_handoff/OPEN_QUESTIONS.md) Q6 (hotkey scope), Q7 (just-tapped animation), Q8 (auto-advance timing). All three resolved in §3 of this spec; Q6 amended in this session — staging hotkeys widened from `1`–`6` to `1`–`9`, technical buckets remapped from `7`–`9` to `Q`/`W`/`E` to free more category slots.

## 1. Context and Goal

After F1–F4, a user can sign in, manage categories, create/list triage blocks, browse a block's bucket detail, move tracks between buckets, transfer tracks across blocks, and finalize a block. What's missing — and what the entire iter-2a gameplay loop pivots around — is the actual **curation experience**: working through a queue of unsorted tracks one-at-a-time and assigning each to its destination (a staging category, a technical bucket, or DISCARD).

F5 ships that experience. Curate is the heart of the product (per the Pass 2 cover blurb): a focused, keyboard-first surface that turns an `IN_PROGRESS` block's bucket into a sortable queue. The UX optimises for tactility (one keystroke per track, immediate visual confirmation, immediate next track) and reversibility (every action is undoable for as long as the previous action was the most recent).

After F5 ships, a logged-in user can:

- Open `/curate` (no params) → land on the most recently used style's most recently curated block + bucket. If no resume state exists, land on a setup picker that walks them through pick-a-block + pick-a-bucket within the current style's `IN_PROGRESS` blocks.
- From `TriageDetailPage` or `BucketDetailPage` (F3a surfaces) click a new `Curate this bucket` CTA → deep-link to `/curate/:styleId/:blockId/:bucketId`. The CTA is gated to non-empty source-eligible buckets (any non-STAGING bucket of an IN_PROGRESS block).
- See a `<CurateCard>` showing the current track (title, mix, artists, label, BPM, length, release date, AI-suspect badge) plus a Spotify deep-link button. Press `1`–`9` to assign to staging categories (active staging buckets, in `position` order), `Q`/`W`/`E` to assign to NEW/OLD/NOT, `0` to assign to DISCARD. The just-tapped destination button pulses (80ms scale + magenta accent fade); 200ms later the card auto-advances to the next track.
- Press `U` to undo the last assignment. If the 200ms pre-advance window hasn't fired yet, undo cancels the advance in place. Otherwise undo reverts the move HTTP-side (via the existing `undoMoveDirect` helper) and jumps the queue index back to the just-undone track.
- Press a different destination during the 200ms window → the in-flight move is reverted and the new destination is applied to the same track; the 200ms timer restarts so the user can continue to revise. Net effect: the user can mash keys in quick succession until the right one sticks.
- Press `J` to skip a track without assigning, `K` to step back to the previous track without undoing the assignment, `Space` to open the track in Spotify (placeholder — F6 promotes this to play/pause), `?` to toggle the keyboard-shortcut overlay, `Esc` to close the overlay (or to exit Curate when no overlay is open).
- After the last track in the source bucket is assigned, the queue is exhausted; the user sees a "Bucket clean" end-of-queue surface. If the same block has another non-empty source-eligible bucket (priority NEW → UNCLASSIFIED → OLD → NOT, excluding STAGING and the just-emptied bucket), a "Continue with {label} ({n})" CTA appears with `Enter` accepting it. If none, the surface offers a "Finalize block" CTA (deep-link to `TriageDetailPage` where F4's `FinalizeModal` opens) plus a "Back to triage" link.
- On mobile (touchscreen, viewport `<64em`), keyboard hotkeys are not bound; instead the destination buttons are full-width tap targets stacked vertically with the same just-tapped feedback and auto-advance. The `?` overlay shows a polite "Keyboard shortcuts available on desktop only" panel with a short tap-to-assign explanation.

Out of scope: audio playback (lives entirely in F6 — F5 ships an external Spotify deep-link as a pure placeholder), bulk operations on the current track (single-track-at-a-time only — the existing `useMoveTracks` hook batches one ID), block creation/finalize from inside Curate (those stay in Triage surfaces — Curate links into them but does not own the modal), bucket creation (impossible per spec-D §5.2), category editing from within Curate (F1 own surface), search inside the queue (the queue is linear and short by intent — Q&A flows are a distraction; if requested later, a `FUTURE-F5-1` covers it), per-track Spotify enrichment retry for UNCLASSIFIED (out of iter-2a — Phase 2 backend work).

## 2. Scope

**In scope:**

- New routes mounted under `/curate` in `frontend/src/routes/router.tsx`:
  - `/curate` → new `CurateIndexRedirect` element.
  - `/curate/:styleId` → new `CurateStyleResume` element.
  - `/curate/:styleId/:blockId/:bucketId` → new `CurateSessionPage` element.
  - The existing placeholder route `path: 'curate', element: <CuratePage />` (`frontend/src/routes/curate.tsx`) is replaced.
- New feature folder `frontend/src/features/curate/` with components, hooks, and lib (full layout in §9).
- New custom hook `useCurateSession({ blockId, bucketId, styleId })` — pure state-machine reducer over `useBucketTracks` queue + `useMoveTracks` mutator. Returned object shape:
  ```ts
  interface CurateSession {
    status: 'loading' | 'active' | 'empty' | 'error';
    queue: BucketTrack[];                        // flattened from useBucketTracks pages
    currentTrack: BucketTrack | null;
    currentIndex: number;
    totalAssigned: number;                       // session counter for EndOfQueue copy
    destinations: TriageBucket[];                // resolved from block.buckets, excluding source
    block: TriageBlock | null;
    lastTappedBucketId: string | null;           // drives data-just-tapped on the button
    canUndo: boolean;                            // lastOp != null
    assign: (toBucketId: string) => void;
    undo: () => void;
    skip: () => void;
    prev: () => void;
    openSpotify: () => void;                     // wraps window.open of currentTrack.spotify_id
  }
  ```
- New custom hook `useCurateHotkeys(session, { destinations, openOverlay, closeOverlay, exit })` — binds desktop-only keyboard, ignores when `useMediaQuery('(max-width: 64em)')` is true or when event target is editable.
- New helpers in `frontend/src/features/curate/lib/`:
  - `lastCurateLocation.ts` — typed read/write/clear for `localStorage` keys `lastCurateLocation` (per-style location) and `lastCurateStyle` (most-recently-used styleId). Mirrors `lastVisitedTriageStyle.ts` shape.
  - `destinationMap.ts` — pure mapping helper that resolves a hotkey-or-button-position to a destination `TriageBucket` given the current block's buckets array. Covers: 1–9 staging-by-position (active only, sorted by `position`), QWE → NEW/OLD/NOT lookup, 0 → DISCARD lookup, exclusion of the current bucket. Returns `null` if no destination resolves (e.g. block has zero staging or pressed key has no mapping).
  - `nextSuggestedBucket.ts` — pure selector for end-of-queue smart-suggest. Input: `block.buckets[]` + `currentBucketId`. Output: highest-priority non-empty non-STAGING non-current bucket using order NEW → UNCLASSIFIED → OLD → NOT, or `null` if none.
- New components in `frontend/src/features/curate/components/`: `CurateSession`, `CurateCard`, `DestinationGrid`, `DestinationButton`, `HotkeyOverlay`, `CurateSetupPage`, `EndOfQueue`, `CurateSkeleton`. Catalog in §5.
- Triage-feature integration: add `Curate this bucket` CTA to `TriageDetailPage` (header) and `BucketDetailPage` (header). The CTA is hidden on FINALIZED blocks, on STAGING buckets, and on buckets with `track_count === 0`. Wired as `<Button component={Link} to={...}>` — no extra hooks required.
- `useMoveTracks` reuse without modification. F3a's hook does not emit toasts internally — toasts live at the call site (`BucketTrackRow` etc.). F5's session callbacks simply do not call `notifications.show`, so the silent-toast effect is achieved by composition. The hook's exported helpers (`takeSnapshot`, `applyOptimisticMove`, `restoreSnapshot`, `undoMoveDirect`) are imported by the reducer for the double-tap and undo paths.
- New `accent-magenta` body class management: a small `useEffect` in `CurateSessionPage` adds `accent-magenta` to `document.body` on mount and removes on unmount. This activates the magenta `--color-selected-bg` token for just-tapped feedback. Confirmed safe per `tokens.css` — the modifier is opt-in and non-destructive.
- New i18n keys under `curate.*` (full list in §10).
- Vitest unit + integration tests, mirroring the F3a/F4 conventions: pure-helper unit tests, hook unit test for `useCurateSession`, integration test for the full session page using `<MantineProvider>` + MSW + the existing five jsdom shims (`frontend/src/test/setup.ts`).
- One CLAUDE.md gotcha: `accent-magenta` body class lifecycle (mount/cleanup) — added to "Frontend (post-F1...)" section once F5 ships.

**Out of scope:**

- **Audio playback.** `Space` is a no-op placeholder that opens the Spotify deep-link in a new tab (`window.open(...)`). F6 graduates `Space` to a play/pause control wired to the Web Playback SDK. F5 must not import `@spotify/web-playback-sdk`, must not request the `streaming` OAuth scope, must not introduce a global PlayerProvider.
- **Bulk operations on the current track.** Curate is one-track-at-a-time. Selecting multiple tracks at once for batch assignment is not supported (and not present in P-22/P-23). Future ticket `FUTURE-F5-2` covers a multi-select mode if requested.
- **Bucket creation, block creation, block finalization, category creation/edit from Curate.** All link out to the relevant Triage / Categories surfaces. Curate does not own these modals.
- **Track search.** No search input in `CurateCard` or `DestinationGrid`. The queue is linear; search would be a Triage-surface concern. `FUTURE-F5-1` covers an in-Curate filter if user volume warrants it.
- **Per-track Spotify enrichment retry.** UNCLASSIFIED bucket is treated as just another source bucket. We do not expose a "retry enrichment" CTA on the card. Phase 2 backend ticket.
- **Re-curate / move-back from STAGING.** STAGING buckets are not source-eligible. The user already has Triage's `MoveToMenu` for that — we don't duplicate it inside Curate.
- **Drag-and-drop in either direction.** Project memory: tap-on-buttons (not DnD), desktop + mobile from day one. No HTML5 DnD, no `@dnd-kit`, no swipe gestures.
- **Multi-block session.** Curate operates on a single `(blockId, bucketId)` at a time. End-of-queue smart-suggest links to another bucket _of the same block_; cross-block navigation requires user intent through the setup picker.
- **History stack deeper than 1.** Per Q4 outcome: silent toast + history depth 1 + double-tap cancel-then-replace. No "rewind 5 tracks" mode.
- **Mobile swipe gesture for skip/assign.** Tap on buttons only. Phase 2 if requested (`FUTURE-F5-3`).
- **Server-side undo endpoint.** Undo uses the existing `undoMoveDirect` helper which fires an inverse `POST /triage/blocks/{id}/move`. There is no special endpoint.
- **Persistence of pending-advance state across reloads.** If the user reloads the page mid-200ms-window, the move is committed (cache + backend) and the user lands on the next track. No special handling.
- **Recovery scheduler for 503 on move.** Single-track move is not bulk; the user retries by pressing the key again. F2's `pendingCreateRecovery` and F4's `pendingFinalizeRecovery` are bulk-operation patterns; F5 does not promote this pattern to single-track moves yet (`FUTURE-F5-4`).

## 3. Architectural Decisions

These are the load-bearing choices made during the brainstorming session, captured here so future-me understands the why.

### D1 — Hybrid entry: deep-link from Triage AND standalone with last-block resume

**Decision.** Two entry paths converge on the same active session route.

- Deep-link from Triage CTAs: `Link to="/curate/:styleId/:blockId/:bucketId"`. Source of truth = URL.
- Standalone `/curate` (or `/curate/:styleId` without further params): redirect through `lastCurateLocation[styleId]` (per-style storage). On stale state (block FINALIZED, soft-deleted, missing), cleanup + fallback to `<CurateSetupPage>` picker.

**Why.** Deep-link makes the keyboard-first ergonomics of "I'm sorting THIS bucket" precise; resume preserves the user's place across days when curating Tech House week-by-week. Per-style scoping aligns with `lastVisitedTriageStyle` and avoids the cross-style context loss of a single global pointer.

**Source of truth.** URL path > `lastCurateLocation[styleId]` > setup picker fallback. Resume reads only when the URL lacks block/bucket params.

### D2 — Single-bucket source per session

**Decision.** Curate operates on exactly one source bucket at a time. End-of-queue offers a "Continue with {bucket}" CTA but does not auto-jump.

**Why.** Three reasons:

1. Mental-model parity. Triage already trains the user to think in buckets; Curate inheriting that boundary keeps the model consistent.
2. Implementation simplicity. The queue = `useBucketTracks(blockId, bucketId)` infinite query, flattened. A multi-source queue would need a new aggregator hook with its own paging semantics — an avoidable abstraction.
3. User clarity. "I am sorting NEW" is a clearer mental frame than "I am sorting whatever bucket the system picked next." Smart-suggest on end-of-queue retains the convenience without sacrificing transparency.

**Alternatives considered.** Variant B (auto-queue across buckets in priority order) was rejected for hiding state. Variant C (multi-source picker with checkboxes) was rejected as YAGNI for iter-2a.

### D3 — No audio playback in F5; Spotify deep-link as `Space` placeholder

**Decision.** F5 ships without audio. The card has an "Open in Spotify" button (and `Space` hotkey) that calls `window.open('https://open.spotify.com/track/' + spotify_id, '_blank')`. F6 replaces this with the embedded SDK player.

**Why.** F6 carries OAuth `streaming` scope, Premium gating, device picker (F7), and a global PlayerProvider — significant infra. F5 ships the keyboard / assign / state-machine layer first so it can be tested in isolation. The deep-link is a graceful fallback: a paying user can keep their Spotify desktop app open and listen there during Curate sessions.

**Tradeoff.** A user without an open Spotify app gets only static metadata. The hotkey overlay surfaces this explicitly: "Audio playback in F6 — for now, Space opens the track in Spotify."

### D4 — Hotkey scope: `1`–`9` staging, `Q`/`W`/`E` technical, `0` DISCARD

**Decision.** This amends OPEN_QUESTIONS Q6.

| Key | Action |
|---|---|
| `1`–`9` | Assign to active staging bucket at `position` 0–8 (skipping inactive). |
| `Q` / `W` / `E` | Assign to NEW / OLD / NOT (only if present in block and not the current bucket). |
| `0` | Assign to DISCARD. |
| `Space` | Open Spotify deep-link (F5 placeholder). |
| `J` | Skip — advance index +1 without assigning. |
| `K` | Prev — step back index −1 without un-assigning anything (purely navigational). |
| `U` | Undo — see D5 state machine. |
| `?` | Toggle hotkey overlay. |
| `Esc` | Close overlay, else exit Curate (`navigate(-1)`). |
| `Enter` | On EndOfQueue surface only — accept the suggested next bucket (or Finalize). |

**Why the change from Q6's original `7`–`9`.** Frees four extra category slots. Up to 9 staging buckets can be hotkeyed instead of 6. `Q`/`W`/`E` are home-row-adjacent on QWERTY keyboards (the assumed layout for this audience — see project memory: small DJ circle, pro tool tone, English-first dev) and intuitive for "tech bucket triage at the side." Q6's edge case (more than 9 staging buckets) keeps the same shape: extras live behind a "More…" menu in the destination grid, surfaced explicitly in the overlay.

**Layout-sensitivity caveat.** Cyrillic / Dvorak users press the **physical** key at the QWE position. We bind on `event.code` (`KeyQ`, `KeyW`, `KeyE`) not `event.key`, so layout-switching does not break the binding. Documented in §6.

### D5 — Silent toast + history-depth-1 undo + double-tap cancel-and-replace

**Decision.** Curate's session callbacks do not emit toast notifications for move success / undo / undo-failure. F3a's `useMoveTracks` hook is toast-free internally — toasts come from call-site handlers (`BucketTrackRow` etc.), so silencing in F5 is achieved by composition: the session reducer captures and reverts state without calling `notifications.show`. Error-path toasts (422 / 503 / network failure) are still emitted by Curate's session — those are user-actionable signals, not move-confirmation noise. Undo uses a single in-memory `lastOp` snapshot (depth 1). Pressing `U` rolls back the most recent assignment (no time window) and resets `lastOp = null`. Pressing a destination during the 200ms pre-advance window cancels the in-flight move and applies the new destination to the same track; the 200ms timer restarts.

**Why depth 1.** A keyboard-first session sorts at one-track-per-second. A toast-stack would either spam or auto-dismiss before the user could click. A multi-step history is YAGNI — 99% of corrections are "I just hit the wrong key." Depth 1 covers it without complicating the reducer.

**Why no time window on post-advance undo.** As long as no further move is committed, the user can `U` minutes after the last assignment. The state-machine invariant: `lastOp` is non-null iff there is a reversible operation. New assignment overwrites `lastOp` (after the inverse of the previous op fires).

**Double-tap semantics.** Within the 200ms pre-advance window: if the user fires another `assign(toBucketId2)`, the reducer (a) `clearTimeout(pendingTimerId)`, (b) `undoMoveDirect(...)` with the original snapshot synchronously, (c) fires a new `useMoveTracks.mutate` with the new destination, (d) restarts the 200ms timer. The `lastOp` is overwritten by the second op's snapshot. If the second destination is the same as the first (`toBucketId === lastOp.input.toBucketId`), short-circuit: clearTimeout, but no rollback / re-fire — same destination, no-op semantically. (This avoids a useless inverse + re-apply round-trip.)

### D6 — `useCurateSession` custom hook owns the state machine

**Decision.** All session state lives in a custom hook returning a typed `Session` object. The page component is thin — it parses route params, validates, mounts `<CurateSession>`, which calls `useCurateSession` internally and renders the subtree.

**Why.** Three reasons:

1. **Testability.** The reducer can be unit-tested in isolation (no React tree, no MSW) by feeding it actions and asserting the next state. This catches reducer bugs that integration tests would surface only via flaky timers.
2. **Reuse.** If a future ticket adds a "compare two buckets" surface, the same session machinery applies — pass two queues, render two cards, share the destination grid.
3. **Single source of truth for derived state.** `currentTrack`, `currentIndex`, `status`, `lastOp` are computed in one place. Components receive them by prop or via the Session object.

**Implementation.** `useReducer` for the state, `useEffect` to bridge `useBucketTracks` → reducer (queue updates), `useEffect` to schedule the 200ms timer + cleanup, plain `useCallback`s for `assign / undo / skip / prev` exposed via the returned object. No external state library.

### D7 — Routing structure: deep-path with `:styleId/:blockId/:bucketId`

**Decision.** Three routes, mirroring F1/F2/F3 conventions:

```tsx
{
  path: 'curate',
  children: [
    { index: true, element: <CurateIndexRedirect /> },
    { path: ':styleId', element: <CurateStyleResume /> },
    { path: ':styleId/:blockId/:bucketId', element: <CurateSessionPage /> },
  ],
}
```

**Why deep-path over query-string.** URLs are shareable ("continue this block"), browser back/forward is meaningful, refresh preserves position, and the convention is consistent with the existing Triage routes (`/triage/:styleId/:id/buckets/:bucketId`).

**`CurateIndexRedirect`** — reads `lastCurateStyle` from `localStorage`. If present and the style still exists in `useStyles` data (hydrated via the existing F1 query), `<Navigate to={`/curate/${styleId}`}>`. Else, `<Navigate to={`/curate/${firstStyleId}`}>` using the first style returned by `useStyles`. If there are zero styles, redirect to `/categories` (catch-all, won't happen for an authenticated user with seeded data).

**`CurateStyleResume`** — reads `lastCurateLocation[styleId]`. If present, validates against `useTriageBlock(blockId)`:

- 200 + `block.status === 'IN_PROGRESS'` + `bucketId in block.buckets[]` + `bucket.bucket_type !== 'STAGING'` (source eligibility) → `<Navigate to={`/curate/${styleId}/${blockId}/${bucketId}`}>`.
- Else (404, FINALIZED, soft-deleted, ineligible) → cleanup `lastCurateLocation[styleId]` and render `<CurateSetupPage>` picker.

If no resume entry exists, render `<CurateSetupPage>` directly.

**`CurateSessionPage`** — guard wrapper (per CLAUDE.md "hooks rule + early Navigate return" pattern): parses params, validates non-null, renders `<CurateSession styleId blockId bucketId />`. The inner component owns hooks.

### D8 — Persistence triggers + storage shape

**Decision.** `lastCurateLocation: { [styleId: string]: { blockId: string; bucketId: string; updatedAt: string } }` and `lastCurateStyle: string` in localStorage.

Write triggers:

1. **`useMoveTracks.onSuccess`** — every successful move writes `lastCurateLocation[styleId] = { blockId, bucketId, updatedAt: new Date().toISOString() }` and `lastCurateStyle = styleId`. Synchronous, ~0.1ms.
2. **Bucket change inside `<CurateSetupPage>` picker** — when the user clicks a bucket option that differs from the URL, navigate fires + the new mount triggers write (route is the source of truth).
3. **Deep-link mount** — on `<CurateSessionPage>` mount, write the current `(styleId, blockId, bucketId)` immediately so a "I just opened the page and closed it" still preserves position.

Read trigger: only `<CurateIndexRedirect>` (for `lastCurateStyle`) and `<CurateStyleResume>` (for `lastCurateLocation[styleId]`).

**Stale handling.** On read, if the stored `blockId` does not pass the validation in D7, the entry is removed and the picker shows. Write does not validate — invalid writes are impossible because the route already validates on mount.

**Why localStorage over IndexedDB / cookie.** Tiny, sync, no server round-trip, naturally per-device. This is a UX nicety, not durable state.

### D9 — Visual feedback per Q7 (just-tapped) + Q8 (auto-advance)

**Decision.**

- **Just-tapped** (Q7): the destination button receives a `data-just-tapped="true"` attribute for 80ms, during which CSS applies `transform: scale(0.97)` + `background: var(--color-selected-bg)` (which is `accent-magenta` due to the body class — see §2 in scope), then transitions back over `--motion-base` (160ms). Pure CSS, no `framer-motion`, no JS animation library.
- **Auto-advance** (Q8): after the 80ms pulse fires, a 200ms `setTimeout` schedules the index advance. Total wall-clock: 280ms from key-press to next-track render. Q8 says "200ms after just-tapped peak" — peak ≈ start of pulse, so we measure the 200ms from the same keydown timestamp the pulse uses; pulse and timer fire in parallel. The timer can be cancelled by `U` (undo) or by another destination press (double-tap).

**Why this timing.** Tested in design pack: 200ms is the minimum where a user can mentally register "yes, that was the right bucket" before the next track appears. Any faster feels jarring; any slower feels sluggish for a one-second-per-track sorting flow. The 80ms pulse exists to make the action feel decisive even when the timer is running.

**Reduced-motion.** Respect `prefers-reduced-motion`: in that mode, drop the scale and the magenta fade. The advance still happens at 200ms — the timing is functional, not decorative. This is per `docs/design_handoff/MANTINE_9_NOTES.md` baseline.

### D10 — Mobile parity: same logic, different layout, no hotkeys

**Decision.** On `useMediaQuery('(max-width: 64em)')` (Mantine's `md` breakpoint), `useCurateHotkeys` does not bind keyboard listeners. The destination grid stacks vertically with full-width 56px buttons (mobile primary hit target per `tokens.css`). The card is single-column. The `?` overlay opens via an icon button in the header and shows a "Keyboard shortcuts available on desktop only" headline plus a tap-to-assign explanation.

**Why no swipe.** Project memory: tap-on-buttons (not DnD), desktop + mobile from day one. Swipe gestures are reserved for `FUTURE-F5-3`.

**Why same logic.** The state machine is input-agnostic — `assign(toBucketId)` is the same primitive whether triggered by hotkey or button click. Mobile only differs in (a) no keyboard binding, (b) layout, (c) overlay copy. No reducer changes.

## 4. UI Surface

### 4.1 `/curate` (no params)

`CurateIndexRedirect` — pure loader-free component that synchronously reads `localStorage.lastCurateStyle` and the first style from `useStyles` cache. Renders `<Navigate to={...}>`. No visible UI. No suspense surface — the redirect is instant.

### 4.2 `/curate/:styleId`

`CurateStyleResume` — reads localStorage + waits for `useTriageBlock` to validate (or fail). While loading, render `<CurateSkeleton>`. On valid resume: `<Navigate>`. On invalid / no resume: render `<CurateSetupPage>` (described in 4.5).

### 4.3 `/curate/:styleId/:blockId/:bucketId` desktop layout

Two-column grid, gap 32px (`--space-8`):

```
┌────────────────────────────────────────┬────────────────────────────────┐
│  CurateCard (60%)                      │  DestinationGrid (40%)         │
│                                        │                                │
│  [   AI badge  ]                       │  Staging                       │
│                                        │  ┌─────────────────────┐  ⌨ 1  │
│  Track title (text-32)                 │  ├─────────────────────┤  ⌨ 2  │
│  feat. Mix Name (text-18)              │  ├─────────────────────┤  ⌨ 3  │
│                                        │  │  ...                │       │
│  Artists · Label                       │                                │
│  BPM · Length · Released               │  Technical                     │
│                                        │  ┌──── NEW ─────────┐  ⌨ Q   │
│  [ Open in Spotify ↗ ]                 │  ├──── OLD ─────────┤  ⌨ W   │
│                                        │  └──── NOT ─────────┘  ⌨ E   │
│                                        │                                │
│                                        │  Discard                       │
│                                        │  ┌──── DISCARD ──────┐  ⌨ 0  │
│                                        │  └────────────────────┘       │
└────────────────────────────────────────┴────────────────────────────────┘
Footer: Track 47 / 312 in NEW · J Prev · K Skip · U Undo · ? Help · Esc Exit
```

`CurateCard` is `--space-8` padding, `--shadow-sm`, `--radius-lg`, `var(--color-bg-elevated)` background. The artist names are `<Anchor href={`https://open.spotify.com/artist/<id>`} target="_blank">` (one per artist if multiple — F3a `BucketTrack.artists: string[]` is name-only; we _do not_ have artist-spotify-id in this iter, so for F5 the artists are plain text — defer artist deep-link to F6 when the track-level Spotify embed makes it natural).

`DestinationButton` is 64px desktop / 56px mobile, justified `space-between` with the bucket label on the left and the `<Kbd>` hint on the right (desktop only). Disabled state for self-bucket (current source) and inactive staging — `opacity 0.4`, `pointer-events: none`, hotkey ignored.

The footer strip is `--text-12` `--color-fg-muted`, displayed as `<Group gap="md">` with separators. On a viewport that can't fit the footer (rare on desktop), it wraps.

### 4.4 `/curate/:styleId/:blockId/:bucketId` mobile layout

Single column, viewport `<64em`:

```
┌──────────────────────────────────┐
│ ← Back   Track 47 / 312       ?  │
├──────────────────────────────────┤
│                                  │
│  CurateCard (compact)            │
│  Title (text-24)                 │
│  Artists · Label · BPM           │
│  [ Open in Spotify ↗ ]           │
│                                  │
├──────────────────────────────────┤
│  Staging                         │
│  ┌────────────────────────────┐  │
│  │  Big Room                  │  │
│  ├────────────────────────────┤  │
│  │  Hard Techno               │  │
│  ├────────────────────────────┤  │
│  │  Tech House                │  │
│  └────────────────────────────┘  │
│  Technical                       │
│  ┌─── NEW ───┐ ┌─── OLD ───┐    │
│  └────────────┘ └────────────┘    │
│  ┌─── NOT ───┐                   │
│  └────────────┘                   │
│  Discard                         │
│  ┌────────────────────────────┐  │
│  │  DISCARD                   │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

Top bar fixed: back button (`navigate(-1)`), track counter (centered or right-aligned), help button (opens overlay). Buttons stack 56px height. Card scrolls naturally; the destination block sits below the card in DOM order — on small heights the user scrolls. On taller mobile (≥600px viewport height) the card + grid both fit without scrolling.

### 4.5 `<CurateSetupPage>` — block + bucket picker

Shown when no resume + `:styleId` route. Layout: centered column, `--space-12` padding.

- Heading: `Pick a block to curate`.
- `<Select>` of `IN_PROGRESS` blocks for the style (pulled from `useTriageBlocksByStyle('IN_PROGRESS')`). Default selection: first by `created_at desc`.
- `<Select>` of source-eligible buckets (non-STAGING, `track_count > 0`) of the chosen block. Default: NEW; if NEW empty → UNCLASSIFIED → OLD → NOT → first non-empty non-STAGING.
- CTA: `Start curating` → `<Link to={`/curate/${styleId}/${blockId}/${bucketId}`}>` button.
- Empty states:
  - Style has zero IN_PROGRESS blocks → `<EmptyState>` with title "No active blocks for {style}", body "Create one in Triage to start curating", CTA "Open Triage" linking `/triage/:styleId`.
  - Block has zero non-empty source-eligible buckets → similar, body "All buckets are empty or already promoted. Try another block."
- Loading state (`useTriageBlocksByStyle.isLoading` or `useTriageBlock.isLoading` mid-bucket-pick): `<CurateSkeleton>` (shared).

### 4.6 `<EndOfQueue>` surface

Shown when the queue is exhausted (`currentIndex >= queue.length && !hasNextPage`). Same outer layout as the active session (so the transition is gentle), but the card area shows:

- Heading: `Bucket clean — {currentBucketLabel}`.
- Body: `You sorted {totalAssigned} tracks.`
- Suggested-next (if `nextSuggestedBucket` returns non-null): primary CTA `Continue with {label} ({n})` linking to `/curate/:styleId/:blockId/:nextBucketId`. Hotkey hint `Enter`.
- If no suggestion: primary CTA `Finalize block` linking to `/triage/:styleId/:blockId` (where F4's `FinalizeModal` opens). No hotkey.
- Secondary CTA: `Back to triage` linking to `/triage/:styleId/:blockId`.

The destination grid is hidden in this state. Footer keeps `Esc Exit` only.

### 4.7 `<HotkeyOverlay>`

Mantine `Modal` size="md", title `Keyboard shortcuts`. Inside, a two-column table of `<Kbd>key</Kbd>` + label. Sections: Assign (1–9, Q/W/E, 0), Navigate (J, K), Action (Space, U), System (?, Esc, Enter on EndOfQueue).

Footer note: `Audio playback in F6 — Space opens Spotify for now.`
Footer note 2 (only if block has >9 active staging): `Categories beyond 9 are accessible via the More… menu.`

`?` toggles, `Esc` closes (priority: close overlay first, then exit if pressed again with overlay closed).

On mobile: same modal, but the table renders only the Action / System rows; Assign / Navigate sections are replaced by a single "Tap a button below the track card to assign" line.

## 5. Component Catalog

### 5.1 `CurateIndexRedirect`

```tsx
function CurateIndexRedirect(): JSX.Element {
  const styles = useStyles(); // F1 hook, cached
  const lastStyle = readLastCurateStyle();
  if (styles.isLoading) return <CurateSkeleton />;
  const target = lastStyle && styles.data?.some((s) => s.id === lastStyle)
    ? lastStyle
    : styles.data?.[0]?.id;
  return target
    ? <Navigate to={`/curate/${target}`} replace />
    : <Navigate to="/categories" replace />;
}
```

No own state. Uses `<Navigate replace>` so the URL history doesn't show `/curate` as an intermediate.

### 5.2 `CurateStyleResume`

Reads `lastCurateLocation[styleId]`. Calls `useTriageBlock(stored?.blockId)` if present. Validates per D7. Renders `<Navigate>`, `<CurateSetupPage>`, or `<CurateSkeleton>`.

### 5.3 `CurateSessionPage`

Guard wrapper. Validates params (non-null `styleId`/`blockId`/`bucketId`), redirects on missing. Owns the `accent-magenta` body class lifecycle (mount/cleanup). Renders inner `<CurateSession>`.

### 5.4 `CurateSession`

Top-level component for active session. Calls `useCurateSession(...)`. Splits into `<CurateCard>`, `<DestinationGrid>`, `<HotkeyOverlay>`, `<EndOfQueue>` based on session.status.

```tsx
interface CurateSessionProps { styleId: string; blockId: string; bucketId: string; }

function CurateSession(props: CurateSessionProps): JSX.Element {
  const session = useCurateSession(props);
  const [overlayOpen, setOverlayOpen] = useState(false);
  useCurateHotkeys(session, {
    openOverlay: () => setOverlayOpen(true),
    closeOverlay: () => setOverlayOpen(false),
  });

  if (session.status === 'loading') return <CurateSkeleton />;
  if (session.status === 'empty') return <EndOfQueue {...} />;
  if (session.status === 'error') return <ErrorRetry onRetry={...} />;

  return (
    <Layout>
      <CurateCard track={session.currentTrack} />
      <DestinationGrid
        buckets={session.destinations}
        currentBucketId={props.bucketId}
        onAssign={session.assign}
        lastTappedBucketId={session.lastTappedBucketId}
      />
      <HotkeyOverlay opened={overlayOpen} onClose={() => setOverlayOpen(false)} />
    </Layout>
  );
}
```

### 5.5 `CurateCard`

Pure presentation. Props: `track: BucketTrack`. Renders title + mix name + artists list + label + BPM + length + release date + AI-suspect badge + "Open in Spotify" button. Spotify URL: `spotify_id ? https://open.spotify.com/track/${spotify_id} : null` (button hidden if no `spotify_id`).

Mobile vs desktop variant via Mantine `useMediaQuery` — same component, different `<Stack>` gap and font sizes.

### 5.6 `DestinationGrid` + `DestinationButton`

`DestinationGrid` takes the block's buckets (via prop, derived in `useCurateSession`), splits into staging / technical / discard groups, renders `<DestinationButton>` rows. Skips inactive staging entries (or renders disabled, decision: render disabled for Q6 visibility — user knows why a slot is missing). The `>9 staging` overflow: render slots 1–9 as buttons, then a final "More categories…" `<Menu>` with the rest.

`DestinationButton` props: `bucket: TriageBucket`, `hotkeyHint: string | null` (e.g. `'1'`, `'Q'`, `'0'`, or null on mobile), `justTapped: boolean` (driven by parent comparing `bucket.id === lastTappedBucketId`), `disabled: boolean`, `onClick: () => void`. Self-bucket (currentBucketId) is `disabled`. Inactive staging is `disabled` with title `"Category inactive — re-activate in Categories"`. AI semantic: `aria-label={`Assign to ${label}`}`.

CSS-only just-tapped: `[data-just-tapped="true"] { transform: scale(0.97); background: var(--color-selected-bg); transition: ... }`.

### 5.7 `HotkeyOverlay`

Mantine `Modal`. Content per §4.7. No own logic; `opened` + `onClose` props.

### 5.8 `CurateSetupPage`

Per §4.5. Two `<Select>`s + CTA. Uses `useTriageBlocksByStyle('IN_PROGRESS', styleId)` and `useTriageBlock(blockId)` (the latter only when a block is selected — gated). Local `useState` for the picks; on submit `<Link>` navigation.

### 5.9 `EndOfQueue`

Per §4.6. Pure presentation; receives `block: TriageBlock`, `currentBucketId`, `totalAssigned: number` (computed by `useCurateSession` as a session-counter side-state). Calls `nextSuggestedBucket(block, currentBucketId)` to decide CTA copy.

### 5.10 `CurateSkeleton`

Mantine `<Skeleton>` rectangles laid out to mimic the active layout. Used for resume loading + setup loading + initial session load. ~80 LOC.

## 6. Data Flow

### 6.1 Mount → first render

1. `CurateSessionPage` parses params.
2. Mounts `accent-magenta` body class (`useEffect` with cleanup).
3. Renders `<CurateSession>`.
4. `useCurateSession` calls `useTriageBlock(blockId)` and `useBucketTracks(blockId, bucketId, '')` (no search). Both use shared cache; if F3a navigated through these, hits are warm.
5. Reducer initial state: `{ currentIndex: 0, pendingTimerId: null, lastOp: null, totalAssigned: 0, status: 'loading' }`.
6. When both queries hydrate → reducer sees `block` + `queue` and transitions to either `'active'` (queue length > 0), `'empty'` (queue length === 0 + `!hasNextPage`), or stays `'loading'` (still fetching).

### 6.2 Assign (key press or button click)

1. User presses `1` on desktop or taps the first staging button on mobile.
2. `useCurateHotkeys` resolves: `event.code === 'Digit1'` → `destinationMap.byPosition(buckets, 0)` → `bucket`.
3. Bucket is non-null and not the source bucket → call `session.assign(bucket.id)`.
4. Reducer dispatches `ASSIGN` with `{ toBucketId: bucket.id, trackId: queue[currentIndex].track_id }`.
5. Reducer body:
   - If `pendingTimerId !== null` → double-tap path:
     - If `lastOp.input.toBucketId === toBucketId` → just `clearTimeout`, reset timer for 200ms, return. (Same destination, no rollback needed.)
     - Else → `clearTimeout`, `undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot)` (synchronous restore + async inverse HTTP), then call `mutate({ fromBucketId, toBucketId, trackIds: [trackId] })` with the new bucket; on `onMutate` capture the new snapshot and store it as `lastOp`.
   - If `pendingTimerId === null` → fresh path:
     - Capture the snapshot directly via the exported helper: `const snapshot = takeSnapshot(qc, blockId, fromBucketId)`.
     - Call `mutate({ fromBucketId, toBucketId, trackIds: [trackId] })`. `useMoveTracks.onMutate` will independently call `takeSnapshot` + `applyOptimisticMove` — both helpers are pure cache reads/writes, so calling `takeSnapshot` twice on the same key is safe (the reducer's reference is captured before `mutate` triggers `onMutate`, identical state).
     - Set `lastOp = { input, snapshot, trackIndex: currentIndex }`.
   - Schedule `setTimeout(advance, 200)`. Store `pendingTimerId`.
   - Trigger `justTapped` for the destination button (state on the session: `lastTappedBucketId` cleared after 80ms via another timeout).
6. `mutate` succeeds in the background; `onSuccess` writes `lastCurateLocation[styleId]` and `lastCurateStyle = styleId`.
7. Timer fires after 200ms → reducer dispatches `ADVANCE` → `currentIndex++`, `pendingTimerId = null`, `totalAssigned++`. If `currentIndex >= queue.length` and `!hasNextPage`, status → `'empty'`. If `currentIndex >= queue.length - 5` and `hasNextPage`, fire `fetchNextPage()`.

### 6.3 Undo (`U` key, no UI button on desktop)

Reducer dispatches `UNDO`. Body:

- If `pendingTimerId !== null`:
  - `clearTimeout(pendingTimerId)`.
  - `undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot)` synchronously.
  - `lastOp = null`, `pendingTimerId = null`. `currentIndex` unchanged.
- Else if `lastOp !== null`:
  - `undoMoveDirect(...)` synchronously.
  - `currentIndex = lastOp.trackIndex`, `lastOp = null`. `totalAssigned--`. Status back to `'active'` if was `'empty'`.
- Else: no-op (optionally `notifications.show({ message: t('curate.toast.nothing_to_undo'), autoClose: 2000 })` with a 3s cooldown). Decision: skip the toast for now — silent no-op. If users complain, add a brief inline hint.

### 6.4 Skip / Prev (`J` / `K`)

Pure index movement. `J` = `currentIndex = Math.min(queue.length, currentIndex + 1)`; if at end and `hasNextPage` → fetch + stay. `K` = `currentIndex = Math.max(0, currentIndex - 1)`. Neither touches `lastOp` (not an assignment).

`J` past the end with no more pages → status `'empty'` + EndOfQueue.

### 6.5 Pagination

Inside `useCurateSession`, a `useEffect` watches `currentIndex` and `queue.length`:

```ts
useEffect(() => {
  if (
    bucketTracksQuery.hasNextPage &&
    !bucketTracksQuery.isFetchingNextPage &&
    currentIndex >= queue.length - 5
  ) {
    bucketTracksQuery.fetchNextPage();
  }
}, [currentIndex, queue.length, bucketTracksQuery.hasNextPage, ...]);
```

Buffer of 5 — at PAGE_SIZE=50 and one-track-per-second, the next page fetches ~5s before the user reaches the end of the current one.

### 6.6 Hotkey resolution (layout-safe)

`useCurateHotkeys` listens to `keydown` on `window`. Filters:

- Ignore if `event.target` is `<input>`, `<textarea>`, `[contenteditable]`, or inside a Mantine modal portal that does not belong to the overlay.
- Ignore on mobile (`useMediaQuery('(max-width: 64em)') === true`).
- Match by `event.code` for `Digit1`–`Digit9`, `Digit0`, `KeyQ`, `KeyW`, `KeyE`, `KeyJ`, `KeyK`, `KeyU`, `Space`, `Escape`, `Enter`. Match by `event.key === '?'` for help (since `?` is a shifted character that varies by layout; `event.code` would require `Shift+Slash` on US — the `?` key form is the user-facing intent).
- `event.preventDefault()` for matched keys, `event.stopPropagation()`.
- Resolve each match to a callback: `assign(...)`, `undo()`, `skip()`, `prev()`, `openOverlay()`, `closeOverlay()`, `exit()`, `openSpotify()`.

### 6.7 Cache invalidation already handled by `useMoveTracks`

F3a's hook already invalidates `bucketTracksKey(blockId, fromBucketId, ...)`, `bucketTracksKey(blockId, toBucketId, ...)`, `triageBlockKey(blockId)`, and `triageBlocksByStyleKey(styleId, status)` on success. F5 inherits these without modification. Curate's `useBucketTracks` query is one of the invalidated keys, so the optimistic apply + post-success refetch keeps the queue consistent if the user closes Curate and reopens.

### 6.8 No `useMoveTracks` modification needed

`useMoveTracks` (F3a) is toast-free internally — the hook handles only optimistic apply, snapshot, restore, and cache invalidation. Move-success toasts are emitted by call sites (`BucketTrackRow`'s `onSuccess` handler). Curate's session callbacks therefore don't call `notifications.show` for success, and the silent-toast behavior is achieved without changing the hook.

Error-path toasts in Curate (422 stale / 422 inactive / 503 / network) are emitted by the session reducer's `onError` handler when calling `mutate`, mapped per §8.

The hook's exported helpers — `takeSnapshot`, `applyOptimisticMove`, `restoreSnapshot`, `undoMoveDirect` — are imported by `useCurateSession` for the double-tap and undo paths (D5 + 6.2 + 6.3).

## 7. Validation

### 7.1 Param validation

`CurateSessionPage`:

- `styleId`, `blockId`, `bucketId` must each be a non-empty string. Else `<Navigate to="/curate" replace />`.
- After `useTriageBlock(blockId)` resolves: `block.style_id === styleId` (else redirect to `/curate/${block.style_id}/${blockId}/${bucketId}`), `bucketId in block.buckets`, `bucket.bucket_type !== 'STAGING'`, `block.status === 'IN_PROGRESS'`. Any failure → cleanup `lastCurateLocation[styleId]` + `<Navigate to={`/curate/${styleId}`} replace>` (which will then show the setup picker).

### 7.2 Picker validation

`<CurateSetupPage>`:

- Disable Start CTA until both block and bucket are picked.
- Filter bucket options to non-STAGING and (per UX) non-empty (`track_count > 0`). Empty buckets are not source-eligible.
- If user picks a block whose buckets are all empty / all STAGING → render the empty CTA (see §4.5).

### 7.3 Hotkey validation

In `destinationMap.ts`:

- `byPosition(buckets, position)` returns the active staging bucket at `position` (using `bucket.position` for ordering, filtering inactive). Returns `null` if out of range.
- `byTechType(buckets, type: 'NEW' | 'OLD' | 'NOT')` returns the matching technical bucket or `null` if absent (rare — block creation guarantees these in spec-D §5.2 unless explicitly disabled).
- `byDiscard(buckets)` returns DISCARD or `null`.
- Caller: in `useCurateHotkeys`, if resolution returns null, no-op (no error toast — just silent ignore).

### 7.4 No client-side track-id validation

We trust `queue[currentIndex].track_id` to be a UUID. The backend re-validates per spec-D §5.7 and emits 422 on mismatch.

## 8. Error / Empty / Loading UX Mapping

| Condition | UX |
|---|---|
| Initial mount, `useTriageBlock` + `useBucketTracks` loading | `<CurateSkeleton>` full-page |
| `useTriageBlock` 404 | Cleanup `lastCurateLocation[styleId]` → `<Navigate to={`/curate/${styleId}`}>` (setup picker) |
| `useTriageBlock` 503 (cold-start) | `<CurateSkeleton>` for first attempt; if 3 retries fail → `<ErrorRetry>` with `onRetry` re-fetching |
| `block.status === 'FINALIZED'` | `<Navigate to={`/triage/${styleId}/${blockId}`}>` + cleanup localStorage |
| `bucket.bucket_type === 'STAGING'` (deep-link tampering) | `<Navigate to={`/curate/${styleId}`}>` + cleanup |
| Source bucket empty (`queue.length === 0 && !hasNextPage`) | `<EndOfQueue>` immediately |
| Move 200 | Optimistic stays applied; `lastOp` valid for next undo; localStorage updated |
| Move 422 `tracks_not_in_source` | Reducer dispatches `SKIP_STALE`: revert optimistic via `restoreSnapshot` (already on error), index advances anyway, `lastOp = null`. Single info-tone notification: `Track no longer in this bucket — skipped.` (`curate.toast.skip_stale`). |
| Move 422 `block_not_editable` (block became FINALIZED) | Show red toast `Block was finalized. Returning to triage.` → `<Navigate to={`/triage/${styleId}/${blockId}`}>` + cleanup localStorage |
| Move 422 `target_bucket_inactive` | Amber toast `Destination became inactive. Pick another.` Reducer reverts optimistic (already on error), `lastOp = null`. Invalidate `useTriageBlock` so the next render disables the inactive button |
| Move 404 `triage_block_not_found` | Red toast `Block not found. It may have been deleted.` → `<Navigate to={`/triage/${styleId}`}>` |
| Move 503 cold-start (single track) | Amber toast `Service unavailable. Move not applied — please retry.` Reducer reverts optimistic, `lastOp = null`. No auto-retry scheduler in F5 |
| Move network error / unknown 500 | Red toast `Move failed. Please retry.` Same revert path |
| Pagination 503 | `useBucketTracks` error toast (already standard); index doesn't advance past loaded; "Load more" CTA disabled until retry succeeds |
| `useStyles` empty | Should not happen for an authenticated user; if so, redirect to `/categories` (catch-all from CurateIndexRedirect) |
| `useTriageBlocksByStyle('IN_PROGRESS')` empty in setup | `<EmptyState>` with CTA "Open Triage" |
| Reduced-motion preference | No scale, no fade. 200ms timer still fires (functional) |

## 9. Code Layout

```
frontend/src/features/curate/
├── components/
│   ├── __tests__/
│   │   ├── CurateCard.test.tsx
│   │   ├── DestinationButton.test.tsx
│   │   ├── DestinationGrid.test.tsx
│   │   ├── EndOfQueue.test.tsx
│   │   └── HotkeyOverlay.test.tsx
│   ├── CurateCard.tsx
│   ├── CurateSession.tsx
│   ├── CurateSetupPage.tsx
│   ├── CurateSkeleton.tsx
│   ├── DestinationButton.tsx
│   ├── DestinationGrid.tsx
│   ├── EndOfQueue.tsx
│   └── HotkeyOverlay.tsx
├── hooks/
│   ├── __tests__/
│   │   ├── useCurateSession.test.ts
│   │   └── useCurateHotkeys.test.ts
│   ├── useCurateHotkeys.ts
│   └── useCurateSession.ts
├── lib/
│   ├── __tests__/
│   │   ├── destinationMap.test.ts
│   │   ├── lastCurateLocation.test.ts
│   │   └── nextSuggestedBucket.test.ts
│   ├── destinationMap.ts
│   ├── lastCurateLocation.ts
│   └── nextSuggestedBucket.ts
├── routes/
│   ├── CurateIndexRedirect.tsx
│   ├── CurateSessionPage.tsx
│   └── CurateStyleResume.tsx
└── index.ts                          # public exports
```

Plus integration test: `frontend/src/__tests__/curate-flow.test.tsx`.
Plus router edit: `frontend/src/routes/router.tsx` (replace `/curate` placeholder with the three new routes).
Plus i18n edit: `frontend/src/i18n/en.json` (new `curate.*` keys).
Plus Triage CTA wiring: `frontend/src/features/triage/components/TriageBlockHeader.tsx` and `BucketDetailPage.tsx` — small additions only, no extraction yet.
Plus removal: `frontend/src/routes/curate.tsx` (the placeholder).

## 10. i18n Keys

Under `curate.*` in `frontend/src/i18n/en.json`:

```json
{
  "curate": {
    "page_title": "Curate",
    "card": {
      "open_in_spotify": "Open in Spotify",
      "open_in_spotify_aria": "Open {{title}} in Spotify (new tab)",
      "ai_badge": "AI suspect",
      "ai_badge_aria": "Track flagged as possibly AI-generated",
      "released_label": "Released",
      "label_label": "Label",
      "bpm_label": "BPM",
      "length_label": "Length",
      "no_spotify_id": "No Spotify match"
    },
    "destination": {
      "group_staging": "Staging",
      "group_technical": "Technical",
      "group_discard": "Discard",
      "more_categories": "More categories…",
      "more_aria": "Show {{count}} more categories",
      "assign_aria": "Assign to {{label}}",
      "self_disabled_title": "Current bucket — pick a different destination",
      "inactive_disabled_title": "Category inactive — re-activate in Categories"
    },
    "footer": {
      "track_counter_one": "Track {{current}} of {{total}}",
      "track_counter_other": "Track {{current}} of {{total}}",
      "in_bucket": "in {{label}}",
      "shortcut_prev": "Prev",
      "shortcut_skip": "Skip",
      "shortcut_undo": "Undo",
      "shortcut_help": "Help",
      "shortcut_exit": "Exit"
    },
    "hotkeys": {
      "title": "Keyboard shortcuts",
      "section_assign": "Assign",
      "section_navigate": "Navigate",
      "section_action": "Action",
      "section_system": "System",
      "key_digits_label": "Assign to staging category 1–9",
      "key_qwe_label": "Assign to NEW / OLD / NOT",
      "key_zero_label": "Assign to DISCARD",
      "key_space_label": "Open in Spotify (audio in F6)",
      "key_j_label": "Skip without assigning",
      "key_k_label": "Step back to previous track",
      "key_u_label": "Undo last assignment",
      "key_help_label": "Show / hide this overlay",
      "key_esc_label": "Close overlay or exit Curate",
      "key_enter_label": "Accept suggested next bucket",
      "footer_audio_note": "Audio playback ships in F6 — Space opens Spotify in a new tab for now.",
      "footer_overflow_note": "Categories beyond 9 are accessible via the More… menu.",
      "mobile_note": "Keyboard shortcuts available on desktop only. Tap a destination button to assign."
    },
    "toast": {
      "skip_stale": "Track no longer in this bucket — skipped.",
      "block_finalized": "Block was finalized. Returning to triage.",
      "block_not_found": "Block not found. It may have been deleted.",
      "destination_inactive": "Destination became inactive. Pick another.",
      "service_unavailable": "Service unavailable. Move not applied — please retry.",
      "move_failed": "Move failed. Please retry."
    },
    "setup": {
      "title": "Pick a block to curate",
      "block_select_label": "Block",
      "block_select_placeholder": "Select an active block",
      "bucket_select_label": "Bucket",
      "bucket_select_placeholder": "Select a source bucket",
      "start_cta": "Start curating",
      "no_active_blocks_title": "No active blocks for {{style_name}}",
      "no_active_blocks_body": "Create a triage block to start curating.",
      "open_triage_cta": "Open Triage",
      "no_eligible_buckets_title": "No source-eligible buckets",
      "no_eligible_buckets_body": "All buckets are empty or already promoted. Try another block."
    },
    "end_of_queue": {
      "heading": "Bucket clean — {{label}}",
      "body": "You sorted {{count}} track. Nice work.",
      "body_other": "You sorted {{count}} tracks. Nice work.",
      "continue_cta": "Continue with {{label}} ({{count}})",
      "finalize_cta": "Finalize block",
      "back_to_triage_cta": "Back to triage"
    },
    "exit_aria": "Exit Curate",
    "help_aria": "Show keyboard shortcuts",
    "back_aria": "Back to triage"
  }
}
```

Russian translations are added to `frontend/src/i18n/ru.json` in CC-4 (deferred); F5 ships English-only keys, but the structure is symmetric so CC-4 is mechanical.

## 11. Testing

### 11.1 Unit tests

**`destinationMap.test.ts`:**

- `byPosition(buckets, 0)` returns the first active staging bucket.
- `byPosition(buckets, 4)` skips inactive staging entries when computing the offset.
- `byPosition(buckets, 12)` returns `null` (out of range).
- `byTechType` returns NEW / OLD / NOT or null.
- `byDiscard` returns the DISCARD bucket.
- All-of-the-above respect "exclude current bucket" when caller provides `currentBucketId`.

**`lastCurateLocation.test.ts`:**

- `read / write / clear` round-trip per styleId.
- Read with corrupt JSON → returns null + clears the bad entry.
- `isStale(stored, block)` → true on FINALIZED, true on `bucketId not in block.buckets`, false on healthy IN_PROGRESS.

**`nextSuggestedBucket.test.ts`:**

- Priority NEW → UNCLASSIFIED → OLD → NOT.
- Skips current bucket.
- Skips empty buckets (`track_count === 0`).
- Skips STAGING + DISCARD.
- Returns null when none available.

**`useCurateSession.test.ts`** (uses `renderHook` + `MantineProvider` + a fake QueryClient):

- Initial state: status `'loading'`, then `'active'` once queue hydrates.
- `assign(toBucketId)` → reducer schedules timer, captures `lastOp`, optimistic apply visible in cache.
- 200ms passes → `currentIndex` advances, `pendingTimerId = null`.
- Double-tap: `assign(b1)` then immediately `assign(b2)` (within 200ms) → first reverted, second applied, `lastOp.input.toBucketId === b2`, single advance.
- Same-destination double-tap: `assign(b1)` twice → no rollback, timer reset, single advance.
- Undo within window: `assign(b1)`, then `undo()` within 200ms → no advance, snapshot restored, `lastOp = null`.
- Undo after window: `assign(b1)`, advance fires, then `undo()` → snapshot restored, `currentIndex` rolls back to original, `lastOp = null`.
- Skip / Prev: pure index movement.
- End of queue: when `currentIndex >= queue.length && !hasNextPage` → status `'empty'`.

**`useCurateHotkeys.test.ts`:**

- `Digit1` → calls `assign(byPosition(0))`.
- `KeyQ` → calls `assign(byTechType('NEW'))`.
- `Digit0` → calls `assign(byDiscard())`.
- `KeyU` → calls `undo()`.
- `KeyJ` / `KeyK` → calls `skip()` / `prev()`.
- `?` → calls `openOverlay()`.
- `Escape` with overlay open → calls `closeOverlay()`; without overlay → calls `exit()`.
- Mobile (mocked `useMediaQuery`) → no listeners bound; key presses are no-ops.
- Editable target (input) → key presses are ignored.

**Component tests** (`*.test.tsx`):

- `<CurateCard>`: renders all metadata fields; "Open in Spotify" hidden if no `spotify_id`; AI badge shows only if `is_ai_suspected`.
- `<DestinationButton>`: disabled state for self-bucket and inactive staging; `data-just-tapped` set + cleared correctly; click fires `onClick`.
- `<DestinationGrid>`: groups laid out staging / technical / discard; "More…" appears when staging count > 9.
- `<EndOfQueue>`: renders "Continue" CTA when suggestion exists; renders "Finalize" CTA otherwise.
- `<HotkeyOverlay>`: desktop content vs mobile content via mocked `useMediaQuery`; `?` toggles, `Esc` closes.

### 11.2 Integration test (`curate-flow.test.tsx`)

Single happy-path test using `<RouterProvider>` + `<MantineProvider>` + MSW + the existing five jsdom shims.

Setup: MSW handlers for `GET /triage/blocks/:id` (returns IN_PROGRESS block with NEW/OLD/NOT/UNCLASSIFIED/DISCARD/STAGING-x3), `GET /triage/blocks/:id/buckets/:bucketId/tracks` (returns 50 tracks), `POST /triage/blocks/:id/move` (200 → updates an in-test counter that the test asserts on).

Scenarios in one test (with shared setup, separated by `await waitFor` + assertions):

1. Mount `/curate/style-1/block-1/bucket-new` → card renders with track 1.
2. Press `1` → first staging button receives `data-just-tapped="true"` → after 200ms card shows track 2 + counter `2 / 50`.
3. Press `2`, then `3` within the 200ms window → only the third destination's `data-just-tapped` flickers; track advances once; backend received exactly one inverse-move + two forward-moves (asserting on MSW history).
4. Press `U` → card re-renders track 1 (or stays at track 1 if undone within window).
5. Walk through 49 tracks (rapid `1` presses with `act` wrapping) → on 50th the EndOfQueue surface renders; if NEW had a follow-up OLD with tracks → "Continue with OLD" CTA visible.
6. Press `?` → overlay opens; press `Esc` → overlay closes.

If feasibility of one test for all six is poor (timer races), split into two tests sharing setup helpers.

Mobile variant: separate test with `useMediaQuery` mocked to return true. Asserts no keyboard listeners + tap on destination button works.

Deep-link redirects: separate test mounting `/curate` with `lastCurateStyle` set in localStorage → asserts `<Navigate>` cascade lands on the session page.

### 11.3 Test infra reuse

- `frontend/src/test/setup.ts` five shims (NODE_OPTIONS webstorage, `notifyManager.setScheduler(queueMicrotask)`, i18n init, `ResizeObserver` + `scrollIntoView`, `getBoundingClientRect`) — already in place from F1–F4.
- `frontend/src/test/theme.ts` (singleton MantineTheme with disabled transitions) — required for any component mounting `Modal` or `Notifications`.
- `vi.useFakeTimers()` is needed for the 200ms advance timer and the 80ms pulse. CLAUDE.md gotcha #19 notes the brittleness of fake timers + TQ5 + React 19 microtask scheduler — for this case we drive the reducer timer manually with `vi.advanceTimersByTime(200)` and let TQ5 flush via `await waitFor(...)` after each frame. If still flaky, fall back to real timers + `waitFor` ceilings.

### 11.4 Out-of-scope tests

- Real keyboard layout switching (Cyrillic / Dvorak). Manual smoke during F5 close-out.
- Real Spotify deep-link click. Manual smoke.
- Reduced-motion CSS path. Visual regression — not in scope; manual.
- E2E full-flow (Playwright) — handled by CC-2 once that ticket lands.

## 12. Delivery

### 12.1 Branch + commits

Branch `feat/curate` (no user prefix). Commits follow `caveman:caveman-commit` skill output (Conventional Commits, terse).

Suggested commit cadence (subagent-driven if the implementation plan dispatches agents per task):

1. `feat(curate): add lastCurateLocation storage`
2. `feat(curate): add destinationMap + nextSuggestedBucket helpers`
3. `feat(curate): add useCurateSession reducer`
4. `feat(curate): add useCurateHotkeys binding`
5. `feat(curate): add CurateCard component`
6. `feat(curate): add DestinationButton + DestinationGrid`
7. `feat(curate): add HotkeyOverlay`
8. `feat(curate): add EndOfQueue component`
9. `feat(curate): add CurateSetupPage`
10. `feat(curate): add CurateSession + CurateSessionPage`
11. `feat(curate): add CurateIndexRedirect + CurateStyleResume`
12. `feat(curate): wire routes in router.tsx + remove placeholder`
13. `feat(curate): add Curate this bucket CTAs in Triage`
14. `feat(curate): add curate.* i18n keys`
15. `feat(curate): mount accent-magenta body class on session route`
16. `test(curate): unit + integration tests`
17. `docs(claude-md): capture F5 gotchas`

### 12.2 Smoke against prod API GW

Same shape as F3a / F4: `pnpm dev` from `frontend/`, sign in, navigate from Triage CTA into Curate, sort 5–10 tracks across destinations, validate each destination type, validate undo within and after window, validate double-tap, validate end-of-queue smart-suggest, validate `/curate` cold entry resumes correctly.

### 12.3 PR

Title: `feat(curate): F5 Curate desktop + mobile`. Body: caveman summary + test plan, no AI attribution. Per project PR policy.

### 12.4 Roadmap update

After merge:

- Mark F5 shipped in `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`.
- Add lessons-learned entries (post-F5 section), mirroring the F1/F2/F3a/F3b/F4 cadence.
- Promote any genuinely new gotchas to CLAUDE.md (e.g. `accent-magenta` body class lifecycle, hotkey `event.code` vs `event.key`, fake-timers + 200ms advance pattern).

## 13. Open Items, Edge Cases, Future Flags

- **`FUTURE-F5-1`** — In-Curate search input. Skipped per §2.
- **`FUTURE-F5-2`** — Multi-select (assign N tracks at once). Skipped per §2.
- **`FUTURE-F5-3`** — Mobile swipe gestures (swipe-right = NEW, swipe-left = DISCARD, etc.). Skipped per §2; revisit if a power user requests it.
- **`FUTURE-F5-4`** — Auto-retry scheduler for single-track move 503. Skipped per §2.
- **`FUTURE-F5-5`** — `Shift+1`–`Shift+9` for staging slots 10–18 when block has >9 active staging. Currently the user falls back to a "More…" menu; if categorisation grows wider, hotkeys can extend. Revisit at iter-2b.
- **`FUTURE-F5-6`** — Pre-fetch all queue pages on mount when total ≤200. Currently we lazy-paginate (50/page). For small buckets this is fine; for large ones (300+) the user might notice the brief fetch hiccup at the page boundary. If felt in practice, swap to one-shot prefetch.
- **Q6 amendment** — needs to be reflected in `docs/design_handoff/OPEN_QUESTIONS.md` (staging hotkeys widened to 1–9, technical buckets remapped to QWE). The amendment is part of F5 delivery.

**Edge cases handled:**

- Block has zero staging buckets → keys `1`–`9` no-op silently. Overlay shows the section with a "(none configured)" hint.
- Block has zero `Q`/`W`/`E` buckets (all NEW/OLD/NOT inactive — should never happen since spec-D guarantees them at creation, but defensively) → keys no-op silently. Buttons disabled.
- DISCARD bucket missing (impossible per spec-D) → `0` no-op silently.
- Source bucket changes via another tab while session is open — invalidation cascade refetches `useBucketTracks` → reducer sees a shorter queue → if `currentIndex >= queue.length` → status `'empty'`.
- User opens Curate, then in another tab finalizes the block → next move emits 422 `block_not_editable` → red toast + redirect.
- localStorage quota exceeded (extremely unlikely — entries are tiny) — write fails silently (try/catch), session continues without persistence. Resume just falls back to picker.
- Browser reload mid-200ms-window — the optimistic was already applied + the mutate call may have already fired. On reload, the cache is gone (RTQ doesn't persist), so refetch yields the post-move state. User lands on whatever track is at index 0 of the resumed queue — same UX as a fresh session.
- User navigates back via browser back during pending advance — `useEffect` cleanup fires, `clearTimeout(pendingTimerId)` runs. The optimistic apply is already committed via `mutate`; the inverse will not fire because we never called undo. Next visit refetches, queue reflects the post-move state.

## 14. Acceptance Criteria

- `/curate` (no params) redirects through `lastCurateStyle` to `/curate/:styleId`.
- `/curate/:styleId` (no resume entry, fresh user) renders `<CurateSetupPage>` with a block + bucket picker.
- `/curate/:styleId` (with valid resume) redirects to `/curate/:styleId/:blockId/:bucketId`.
- `/curate/:styleId` (with stale resume entry — block FINALIZED / soft-deleted) cleans up localStorage + renders `<CurateSetupPage>`.
- `/curate/:styleId/:blockId/:bucketId` renders the active session: card + destination grid + footer.
- `Curate this bucket` CTA in `TriageDetailPage` and `BucketDetailPage` is visible only when block is IN_PROGRESS, bucket is non-STAGING, and bucket has tracks. Clicks deep-link into the session route.
- Press `1` → first staging destination button pulses (80ms) → 200ms later the card shows the next track. Counter increments.
- Press `1` twice rapidly (within 200ms) → no rollback, single advance.
- Press `1` then `2` rapidly (within 200ms) → first move reverted, second applied, single advance, single `lastOp` recorded with `toBucketId === bucket-2`.
- Press `Q` → assigns to NEW. Press `W` → OLD. Press `E` → NOT.
- Press `0` → assigns to DISCARD.
- Press `U` within 200ms after `1` → no advance, snapshot restored, button no longer pulses.
- Press `U` after the 200ms window → previous track restored, `currentIndex` decremented, `totalAssigned` decremented.
- Press `U` with no `lastOp` → silent no-op.
- Press `J` → index advances without assigning. Press `K` → index decrements.
- Press `Space` → opens `https://open.spotify.com/track/<id>` in a new tab (skipped silently if no `spotify_id`).
- Press `?` → overlay opens. Press `Esc` → overlay closes. Press `Esc` again → exits Curate (browser back).
- Reach last track in queue with no more pages → `<EndOfQueue>` renders; if another non-empty source-eligible bucket exists in the same block → "Continue with {label} ({n})" CTA + `Enter` accepts. Else "Finalize block" CTA visible.
- 422 `tracks_not_in_source` → silent skip + info toast `Track no longer in this bucket — skipped.`
- 422 `block_not_editable` → red toast `Block was finalized.` + redirect to `/triage/:styleId/:blockId`.
- 422 `target_bucket_inactive` → amber toast + button disabled on next render.
- 503 cold-start → amber toast + revert + user retries with the same key.
- Mobile (`<64em`): keyboard listeners not bound; tap on destination button works the same way; overlay shows mobile-only copy.
- Reduced-motion: pulse + scale dropped; 200ms timer still advances.
- localStorage updated after each successful move (`updatedAt` advances; `lastCurateStyle` set).

## 15. References

- spec-D §5.6 / §5.7: `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks`, `POST /triage/blocks/{id}/move`.
- F3a spec: `useBucketTracks`, `useMoveTracks` (with `undoMoveDirect` helper), `MoveToMenu` parallel.
- F4 spec: `FinalizeModal` flow that EndOfQueue links into.
- design_handoff: `03 Pages catalog · Pass 2 (Curate-Patterns).html` artboards P-22 / P-23 / S-06 (hotkey overlay) / S-05 (undo pattern).
- OPEN_QUESTIONS Q6 (hotkey scope — amended to 1–9 + QWE), Q7 (just-tapped 80ms pulse + 160ms fade), Q8 (auto-advance 200ms + undo cancel).
- CLAUDE.md frontend gotchas (post-F1 through post-F4): jsdom shims, `<MantineProvider theme={testTheme}>` requirement, fake-timer brittleness, `<Text component={Link}>` color override, hooks-rule guard wrapper pattern, cold-start recovery scheduler pattern (not used in F5 but cross-referenced).
- project memory: `project_clouder_curation_ux.md` — tap-on-buttons (not DnD), desktop + mobile from day one.
- Roadmap: F5 size L; depends on F1–F4; unblocks F6 (PlayerCard).

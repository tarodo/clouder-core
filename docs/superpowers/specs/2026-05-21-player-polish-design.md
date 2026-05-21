# Triage / Category Player Polish — Design Spec

**Date:** 2026-05-21
**Status:** Draft (awaiting user review)
**Scope:** Three refinements to the triage bucket player and the category player: (1) restrict the triage player to staging (user-category) buckets only; (2) match the triage player's width to the category player; (3) unify the distribution-button style and layout across both players (controls → buttons → label info).

## Goal

The triage bucket player and the category player should feel like one consistent surface. Today they diverge: the triage player appears on every bucket (including technical NEW/OLD/NOT/UNCLASSIFIED/DISCARD buckets), is narrower (360px vs 520px), uses `Button`-style distribution buttons while categories use `Chip`s, and orders label info differently. This polish converges them.

## Out of scope

- Any backend / API / schema change.
- Changing distribution semantics (triage = one-shot move + advance; category playlist/tag chips = membership toggle). Only the visual style is unified.
- Reworking the category tag/playlist cloud internals — they already use `Chip` and stay as-is apart from the LabelTile reorder.
- Restyling the technical-bucket "Curate from bucket" flow — untouched.

## Requirements & decisions (from brainstorming)

1. **Player only on staging buckets.** On technical buckets the player panel, per-row Play buttons, and queue binding are removed; the user can still curate technical buckets via the existing "Curate from bucket" button.
2. **Width parity.** The triage `BucketPlayerPanel` root is `520px` wide (matching `CategoryPlayerPanel.module.css` `.root`), replacing the current `flex: '0 0 360px'` / `maxWidth: 360`.
3. **Unified layout + button style, applied to BOTH players:** layout is `track controls → distribution buttons → label info`. Distribution buttons use `Chip` style. The triage player shows the full `LabelTile` (not just the label/BPM line). The category player's `LabelTile` moves from above the chip clouds to the bottom.

## Background — current state

- **`BucketDetailPage`** (`frontend/src/features/triage/routes/BucketDetailPage.tsx`) wires the player for ALL buckets: `useBucketPlayerQueue(blockId, bucketId, playerTracks)`, `playTrack`, the desktop `<BucketPlayerPanel>` split, `onPlay={playTrack}` + `currentTrackId` on the list, and the mobile `/player` outlet.
- **`BucketPlayerPanel`** (`...triage/components/BucketPlayerPanel.tsx`) root `<Stack style={{ flex: '0 0 360px', maxWidth: 360 }}>`; renders `<PlayerCard belowMainRow={metaRow}>` (metaRow = `label_name` + `bpm`) then `<BucketDistributeButtons>`. It has no `LabelTile`.
- **`BucketDistributeButtons`** (`...triage/components/BucketDistributeButtons.tsx`) renders Mantine `Button`s in a `SimpleGrid` (DISCARD red).
- **`CategoryPlayerPanel`** (`...categories/components/CategoryPlayerPanel.tsx`) root `className={classes.root}` (520px). Order: `<PlayerCard belowMainRow={metaRow}>` → `<LabelTile>` (when `effectiveRich?.label?.id`) → `<Divider>` → Tags heading + `<PlayerPanelTagCloud>` → `<Divider>` → Playlists heading + `<PlayerPanelPlaylistCloud>`. The clouds already use `Chip`.
- **`LabelTile`** (`...library/components/LabelTile.tsx`) takes `{ labelId, labelName, styleId }`, renders null when `!labelId`. Already imported by `CategoryPlayerPanel`, so `library` is a shared lower-level feature; importing it from `triage` introduces no cycle.
- `BucketTrack` carries `label_id` and `label_name`; `isTechnical(bucket)` and `bucket_type === 'STAGING'` distinguish bucket kinds.

## 1. Restrict the triage player to staging buckets

In `BucketDetailPage` (`BucketDetailInner`):

- Derive, right after the block query (above the early returns, so it's available to the player hooks): `const isStagingBucket = block?.buckets.find((b) => b.id === bucketId)?.bucket_type === 'STAGING';` (`block` is the `useTriageBlock` data; it may be `undefined` during load → `isStagingBucket` falsy, which is the safe default — no player until loaded).
- `useBucketPlayerQueue(blockId, bucketId, isStagingBucket ? playerTracks : EMPTY)` where `EMPTY` is a stable `[]` constant (module-level `const EMPTY_TRACKS: PlaybackTrack[] = []`) so the dependency identity is stable. For technical buckets the bound queue is empty (no playback).
- `playTrack`: early-return when `!isStagingBucket` (in addition to the existing `!tr.spotify_id` guard).
- Render: pass `onPlay={isStagingBucket ? playTrack : undefined}` to `BucketTracksList` (no per-row Play on technical buckets). Render `<BucketPlayerPanel>` (desktop split) only when `isStagingBucket`; otherwise render the list full-width.
- Mobile `/player` outlet short-circuit: `if (onPlayerSubpath) { return isStagingBucket ? <Outlet context=... /> : <Navigate to={`/triage/${styleId}/${blockId}/buckets/${bucketId}`} replace />; }` — a technical bucket reached via a stale `/player` URL redirects back to its detail page.
- Technical buckets keep the existing "Curate from bucket" button (unchanged).

## 2. Width parity for the triage player

The triage player root becomes `520px` to match the category player. Replace `BucketPlayerPanel`'s inline `style={{ minWidth: 0, flex: '0 0 360px', maxWidth: 360 }}` (on both the empty-state and playing-state `<Stack>`) with a `520px` width. Use a `BucketPlayerPanel.module.css` `.root { width: 520px; flex-shrink: 0; }` (mirroring the category module's width/flex-shrink) applied to both branches, OR an inline `style={{ width: 520, flexShrink: 0, minWidth: 0 }}`. A CSS module is preferred for parity with the category panel; the desktop split wrapper in `BucketDetailPage` already provides the surrounding layout, so border-right/scroll are not required for visual size parity.

## 3. Unified layout + Chip-style distribution buttons (both players)

### 3a. `BucketDistributeButtons` → Chip style

Rewrite the grid to use `Chip` instead of `Button`, mirroring `PlayerPanelPlaylistCloud`/`PlayerPanelTagCloud`:
- A `Group gap="xs" wrap="wrap"` of `Chip` components (not `SimpleGrid` of `Button`s).
- Each `Chip`: `checked={false}`, `size="sm"`, `variant="outline"`, `color` = `'red'` for DISCARD else default; `onChange={() => onDistribute(b.id)}` (one-shot — no persistent checked state). Label = `bucketLabel(b, t)`.
- Keep the section heading (`triage.bucket_player.distribute.heading`) and the empty → `null` behavior.

### 3b. `BucketPlayerPanel` layout

Playing-state `<Stack>` (now 520px wide) becomes:
1. `<PlayerCard ... belowMainRow={metaRow}>` (metaRow stays: `label_name` + `bpm` — same as categories).
2. `<BucketDistributeButtons destinations={destinations} onDistribute={distribute} />` (now Chips).
3. `<LabelTile labelId={effectiveRich?.label_id ?? null} labelName={effectiveRich?.label_name ?? null} styleId={block?.style_id ?? ''} />` (renders null when no label).

`LabelTile` import added from `../../library/components/LabelTile`. The empty-state branch (no current track) is unchanged apart from the width.

### 3c. `CategoryPlayerPanel` layout (reorder only)

Move the existing `{effectiveRich?.label?.id && <LabelTile .../>}` block from its current position (immediately after `<PlayerCard>`) to the BOTTOM of the panel — after the Playlists section. Final order: `PlayerCard` → `Divider` → Tags + tag cloud → `Divider` → Playlists + playlist cloud → `LabelTile`. No other change to this file (chips already `Chip`).

## Data flow & edge cases

- **Technical bucket:** `isStagingBucket` false → empty queue, no row Play, no panel, `/player` redirects. Curate button still works. Read-only otherwise.
- **Block loading:** `block` undefined → `isStagingBucket` falsy → player suppressed until the block loads, then it appears for staging buckets. No flicker of a broken player.
- **No current track:** `BucketPlayerPanel` keeps its empty-state branch (width 520).
- **No label on the current track:** `LabelTile` returns null (both players).
- **FINALIZED staging bucket:** player still shows (read-only audition), distribution buttons hidden (existing `destinations === []` gate from the prior feature).
- **One-shot Chip:** never shows a persistent checked state; the track moves out and the queue advances on tap (existing `useBucketDistribute` behavior, unchanged).

## Testing (TDD)

- **`BucketDetailPage` integration:** on a STAGING bucket — per-row Play present and the player panel/queue active (existing behavior preserved); on a TECHNICAL bucket — NO per-row Play buttons and NO player panel rendered, while the list + Curate button still render. (Mock `usePlayback`; the existing test's `inProgressBlock` already has `bk1`=NEW and `bk3`=STAGING.)
- **`BucketDistributeButtons`:** renders `Chip`s for each destination (assert by role/text), `onDistribute` fires on tap, empty → renders nothing. (Adapt the existing test from button-role to the chip's accessible control.)
- **`CategoryPlayerPanel`:** the `LabelTile` (its label link) appears AFTER the Playlists section in DOM order — assert relative order (e.g. via `compareDocumentPosition` or querying that the label anchor follows the playlists heading).
- **`BucketPlayerPanel`:** when playing a staging track with a label, the `LabelTile` renders below the distribution buttons; width style/class is 520. (Mock `useTriageBlock` + `usePlayback` + `useBucketDistribute` as in the existing panel test; `LabelTile` uses `useLabelInfo` (a `useQuery`) so either wrap in a QueryClient or mock `useLabelInfo`/`LabelTile`.)

## Files touched

**Changed**
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — staging gate (queue, Play, panel, mobile redirect).
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — width 520, add `LabelTile` below the buttons.
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` — `Button` → `Chip`.
- `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — move `LabelTile` to the bottom.
- Tests for each of the above (`BucketDetailPage.integration.test.tsx`, `BucketDistributeButtons.test.tsx`, `CategoryPlayerPanel.test.tsx`, `BucketPlayerPanel.test.tsx`).

**New (optional)**
- `frontend/src/features/triage/components/BucketPlayerPanel.module.css` — `.root { width: 520px; flex-shrink: 0; }` (if using a module rather than inline style).

No backend, schema, API, or router-config change (the mobile redirect is in-component navigation, not a route definition change).

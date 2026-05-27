# Improve artists — design

Date: 2026-05-27
Status: approved (pending spec review)

## Problem

Three gaps around artist/label info in the SPA and admin tooling:

1. **Curate player shows no artist info.** The `/curate` session player (reached
   from Triage — the user calls it "триаж") renders a full `LabelTile` in its
   side panel but **no artist tile at all**. The artist appears only as plain
   dimmed text inside the `PlayerCard`. There is no like/dislike for the artist
   and no enrichment, even though the track data already carries an `artists`
   array.

2. **Artist/label info is not uniform across all players.** The app has **four**
   track players, and they disagree on what they show:

   | Player | File | Artist tile | Label tile | Clickable (styleId) |
   |---|---|---|---|---|
   | Triage `BucketPlayerPanel` | `frontend/src/features/triage/components/BucketPlayerPanel.tsx` | yes | yes | yes |
   | Categories `CategoryPlayerPanel` | `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` | yes | yes | yes |
   | Playlists `PlaylistPlayerPanel` | `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` | yes (no links) | **no** (label as text only) | no |
   | Curate `CurateSession` | `frontend/src/features/curate/components/CurateSession.tsx` | **no** | yes | yes |

   Goal: every player shows both an artist tile and a label tile, each with
   name + like/dislike, plus enrichment when it exists.

3. **No admin "search this entity now" button.** `ArtistDetailPage` and
   `LabelDetailPage` have no admin controls. An admin viewing a specific label
   or artist cannot trigger an enrichment search for it using the settings
   already registered for automatic search (`auto_enrich_config`).

## Non-goals

- Mobile layout for the Curate side panel. The Curate `LabelTile` is already
  desktop-only (`!isMobile`); the new artist tile follows the same guard. Mobile
  is out of scope for this iteration.
- Changing auto-enrichment dispatch, vendors, prompts, or merge logic.
- Clickable artist/label links from the playlist player (playlist tracks have no
  `styleId`; see Decision D2).
- Reworking the Triage/Categories players — they already satisfy the parity
  goal and are left untouched.

## Decisions

- **D1 (Curate artist tile):** Add `ArtistsPanel` to the Curate side panel,
  below the existing `LabelTile`, passing the available `styleId` so names link
  to the library. Desktop-only, mirroring the `LabelTile` guard.
- **D2 (Playlist parity — linkless tiles):** Render the same `LabelTile` (and
  keep the existing `ArtistsPanel`) in the playlist player **without** a
  `styleId`. Names render as plain text instead of links. `ArtistTile` already
  supports this; `LabelTile` will be changed to support it too.
- **D3 (Search button backend):** New dedicated endpoints
  `POST /admin/labels/{id}/enrich-auto` and `POST /admin/artists/{id}/enrich-auto`.
  The server reads `auto_enrich_config`, builds a run, and enqueues to SQS —
  reusing the existing manual-enrich run-creation + enqueue path. The frontend
  does not duplicate settings logic.
- **D4 (Search button placement):** Button lives in the `ArtistDetailHeader` /
  `LabelDetailHeader`, visible only when `is_admin` is true.

## Architecture / changes

### Part 1 — Frontend player parity (covers gaps 1 & 2)

**Shared component change — `LabelTile` linkless mode**
File: `frontend/src/features/library/components/LabelTile.tsx`

- Make `styleId` optional: `styleId?: string` (currently required `string`).
- Render the name as a `Link` `Anchor` only when `styleId` is present; otherwise
  render plain `<Text fw={600} size="lg">`. This mirrors `ArtistTile.tsx`
  (lines 67–75), which already branches on `styleId`.
- Compute `detailUrl` only when `styleId` is present.
- No other behavior changes: enrichment, AI badge, preference buttons, and
  channel links stay as-is.

**Curate player — add artist tile**
File: `frontend/src/features/curate/components/CurateSession.tsx`

- In the desktop-only side panel (`!isMobile` block, currently lines ~327–342),
  add below the existing `LabelTile`:

  ```tsx
  <ArtistsPanel
    artists={session.currentTrack?.artists ?? []}
    styleId={styleId}
  />
  ```

- `session.currentTrack` is a `BucketTrack` (from
  `frontend/src/features/triage/hooks/useBucketTracks.ts`), which already
  includes `artists: { id; name; role }[]`. No data/hook change required.
- `ArtistsPanel` already renders `ArtistTile` for the main artist (name +
  like/dislike always; enrichment when present) and badges for the rest.

**Playlist player — add label tile, keep artists**
File: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`

- Replace the "no LabelTile here" comment (lines ~231–235) with a `LabelTile`
  rendered **without** `styleId`:

  ```tsx
  <LabelTile
    labelId={effectiveRich?.label?.id ?? null}
    labelName={effectiveRich?.label?.name ?? null}
  />
  ```

- The existing `<ArtistsPanel artists={...} />` (no `styleId`) stays — artist
  names remain plain text, now matching the label tile's linkless behavior.

**Result after Part 1**

| Player | Artist tile | Label tile | Links |
|---|---|---|---|
| Triage | yes | yes | yes |
| Categories | yes | yes | yes |
| Playlists | yes | **yes (new)** | no (linkless) |
| Curate | **yes (new)** | yes | yes |

### Part 2 — Admin "search now" button (covers gap 3)

**Backend — new endpoints**

Routes:
- `POST /admin/labels/{id}/enrich-auto`
- `POST /admin/artists/{id}/enrich-auto`

Handler behavior (mirrored for labels and artists):
1. Auth: admin-only, same gating as the other `/admin/*` routes.
2. Read auto-search settings via the auto-config repository
   (`label_enrichment/auto_repository.py::get_config('labels')`, and the artist
   equivalent). Use `vendors`, `models`, `prompt_slug`, `prompt_version`,
   `merge_vendor`, `merge_model`. The `enabled` flag governs **automatic
   dispatch only** and is ignored here — the manual button always runs with the
   configured settings.
3. If no config row exists at all, return `409 Conflict` (auto-search not
   configured) — nothing sensible to run.
4. Resolve the entity by `{id}` (it exists; the caller is on its detail page).
5. Build a single-entity run and enqueue to the enrichment SQS queue, reusing
   the existing path in `label_enrichment/routes.py::handle_post_enrich`
   (`create_run` + per-entity SQS message). `source='manual'`.
6. Respond `202 Accepted` with `{ run_id }`.

Wiring (per the OpenAPI gotcha in `CLAUDE.md`):
- Add handlers in `src/collector/label_enrichment/routes.py` and
  `src/collector/artist_enrichment/routes.py`.
- Register routes in `src/collector/handler.py` (`_ADMIN_ROUTES` + dispatcher).
- Add the routes to `infra/api_gateway.tf` and to
  `scripts/generate_openapi.py:ROUTES`.
- Regenerate `docs/api/openapi.yaml`
  (`PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`) and the
  frontend `frontend/src/api/schema.d.ts` (CI diff-checks it).

**Frontend — button + hooks**

- New mutation hooks, e.g. `useEnrichLabelAuto(labelId)` and
  `useEnrichArtistAuto(artistId)` under `frontend/src/features/library/hooks/`,
  POSTing to the new endpoints. On success show a notification ("search
  queued"); on error show an error toast. Disable the button while pending.
- Add an admin-only button to `LabelDetailHeader.tsx` and
  `ArtistDetailHeader.tsx`. Gate with `useAuth()`:
  render only when `state.status === 'authenticated' && state.user.is_admin`.
- Label/aria via i18n (new keys, e.g. `library.detail.admin_search_now`).

## Data flow (search button)

```
Admin on /library/:styleId/labels/:id
  → clicks "Search now" (visible because is_admin)
  → POST /admin/labels/:id/enrich-auto
  → handler reads auto_enrich_config('labels')
  → create_run(source='manual', vendors/models/prompt/merge from config)
  → SQS message for this label
  → existing label_enricher_worker processes it (unchanged)
  → label_info updated; detail page reflects it on next fetch
  → 202 { run_id } → frontend toast "search queued"
```

## Error handling

- **No auto-config row:** `409` from the endpoint; frontend shows an explanatory
  toast.
- **Non-admin caller:** blocked by existing admin route gating (same as other
  `/admin/*`).
- **Entity not found:** `404`.
- **Empty `artists` array (players):** `ArtistsPanel` returns `null` (current
  behavior) — acceptable; the user's concern is the common case of an
  un-enriched artist that still has a row, which renders name + buttons.
- **Missing label on a track (players):** `LabelTile` returns `null` when
  `labelId` is null — acceptable.

## Testing

Backend (pytest):
- New handler: reads config and enqueues a run for the given id (assert SQS
  message + run row); `409` when no config row; admin-only; `404` for unknown
  id. Mirror tests for labels and artists.

Frontend (vitest / jsdom):
- `LabelTile` renders a `Link` when `styleId` is provided and plain text when it
  is absent.
- Curate side panel renders an artist tile (name + preference buttons) for the
  current track.
- Playlist player renders a `LabelTile` (linkless) for a track with a label.
- Admin button: present only when `is_admin`; click fires the mutation; success
  and error toasts.

Notes:
- jsdom proves logic/markup; these changes reuse already-styled tiles, so a
  dedicated `pnpm test:browser` pass is optional. Run it if the linkless
  `LabelTile` layout looks off (per `CLAUDE.md` gotcha 11).

## Files touched (summary)

Frontend:
- `frontend/src/features/library/components/LabelTile.tsx` (optional `styleId`)
- `frontend/src/features/curate/components/CurateSession.tsx` (add `ArtistsPanel`)
- `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` (add `LabelTile`)
- `frontend/src/features/library/components/LabelDetailHeader.tsx` (admin button)
- `frontend/src/features/library/components/ArtistDetailHeader.tsx` (admin button)
- `frontend/src/features/library/hooks/useEnrich{Label,Artist}Auto.ts` (new)
- `frontend/src/api/schema.d.ts` (regenerated)
- i18n keys for the button

Backend / infra:
- `src/collector/label_enrichment/routes.py`, `src/collector/artist_enrichment/routes.py`
- `src/collector/handler.py` (routes + dispatch)
- `infra/api_gateway.tf`
- `scripts/generate_openapi.py` (ROUTES)
- `docs/api/openapi.yaml` (regenerated)
</content>
</invoke>

# User Label Preferences — Design Spec

**Date:** 2026-05-19
**Status:** Approved
**Scope:** Per-user like/dislike state on labels, surfaced in navbar, library list, label detail, and the curate player tile.

## Goal

Let each user mark labels as `liked` or `disliked`. Surface the preference in three places — library list (with filter), label detail header, and the curate player's right-side label tile. The player tile must always render the label name when the current track has a `label_id`, even before label info loads, so the user can react immediately.

## Out of scope

- Artist preferences — no UI for artists exists yet; the schema/UI for artists is deferred.
- Sorting labels by likes count (global popularity).
- Social signals (who else liked).
- Bulk preference editing.

## 1. Data model

New table `clouder_user_label_prefs`:

| column        | type                        | notes                                                |
|---------------|-----------------------------|------------------------------------------------------|
| `user_id`     | `uuid NOT NULL`             | FK → `clouder_users.id`, `ON DELETE CASCADE`         |
| `label_id`    | `text NOT NULL`             | FK → `clouder_labels.id`, `ON DELETE CASCADE`        |
| `status`      | `text NOT NULL`             | CHECK in (`'liked'`, `'disliked'`)                   |
| `updated_at`  | `timestamptz NOT NULL`      | default `NOW()`, set on every upsert                 |

- **Primary key:** `(user_id, label_id)`. Guarantees mutual exclusion of like/dislike per (user, label).
- **Index:** `idx_user_label_prefs_user_status (user_id, status)` — supports `?my=liked|disliked` queries.

Absence of a row means `status=none`. The application never writes a `none` row — `PUT … status=none` deletes.

**Migration:** `alembic/versions/20260519_23_user_label_prefs.py`.

## 2. API surface

### New endpoints

#### `PUT /labels/{label_id}/preference`

- **Auth:** required (any authenticated user).
- **Body:** `{"status": "liked" | "disliked" | "none"}`.
- **Behavior:**
  - `liked` / `disliked` → `INSERT … ON CONFLICT (user_id, label_id) DO UPDATE SET status=$2, updated_at=NOW()`.
  - `none` → `DELETE FROM clouder_user_label_prefs WHERE user_id=$1 AND label_id=$2`. Returns 204 whether or not a row existed (idempotent).
- **Returns:** `204 No Content` on success.
- **Errors:** `404` if `label_id` does not exist in `clouder_labels`. `422` if `status` is not one of the three allowed values.

#### `GET /me/label-preferences?status=liked|disliked&page=N&limit=N`

- **Auth:** required.
- **Default `status`:** `liked`. Default `limit`: 50, max 200. Default `page`: 1.
- **Returns:** `{ items: LabelSummary[], total, page, limit }` — same shape as `GET /labels`. Each item carries `my_preference` set to the requested status.
- **Use:** future "My Liked Labels" page; this iteration ships the endpoint for parity but no UI surface beyond what the existing list provides.

### Changed endpoints

#### `GET /labels?my=all|liked|disliked|unrated`

- New query param `my`, default `all`.
- `liked` / `disliked` → inner join on `clouder_user_label_prefs` for current `user_id` filtered by status.
- `unrated` → anti-join (`LEFT JOIN … WHERE prefs.user_id IS NULL`).
- `all` → no join filter, but the JOIN is still emitted (LEFT) so `my_preference` is projected on every row.
- Each `LabelSummary` gains `my_preference: "liked" | "disliked" | null`.

#### `GET /labels/{label_id}`

- Response gains top-level `my_preference: "liked" | "disliked" | null`.

### OpenAPI

Regenerate `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts` after schema edits in `scripts/generate_openapi.py`.

## 3. Frontend surfaces

### 3.1 Navbar (`frontend/src/routes/_layout.tsx`)

Add a new entry to `NAV_ITEMS`, positioned between `playlists` and `profile`:

```ts
{ path: '/library', labelKey: 'appshell.library', Icon: IconBook }
```

`IconBook` from `@tabler/icons-react`; add to `components/icons.ts` re-export. i18n key `appshell.library = "Library"`.

### 3.2 Shared component: `LabelPreferenceButtons`

`frontend/src/features/library/components/LabelPreferenceButtons.tsx`. Reused by tile, table, detail header.

```tsx
interface Props {
  labelId: string;
  current: 'liked' | 'disliked' | null;
  size?: 'sm' | 'md';
}
```

- Renders two `ActionIcon` buttons: `IconHeart` (filled red when `current === 'liked'`) and `IconX` (filled black when `current === 'disliked'`).
- Click on the active icon → sets `none`. Click on the inactive icon → sets that status. Click on neither-active icon → sets clicked status.
- Calls `useSetLabelPreference` hook with optimistic update.
- ARIA labels via i18n: `library.prefs.like_aria`, `library.prefs.dislike_aria`, `library.prefs.unset_aria`.

### 3.3 Hook: `useSetLabelPreference`

`frontend/src/features/library/hooks/useSetLabelPreference.ts`.

```ts
function useSetLabelPreference(): UseMutationResult<void, Error, { labelId: string; status: 'liked' | 'disliked' | 'none' }>
```

- `mutationFn` calls `PUT /labels/{labelId}/preference`.
- `onMutate`: snapshot current state of `['labelInfo', labelId]` and any `['labelsList', ...]` queries; patch `my_preference` to the new value (or `null` for `none`).
- `onError`: restore snapshots.
- `onSettled`: invalidate `['labelInfo', labelId]` to reconcile with server truth — cheap because labelInfo is small.

The hook does NOT invalidate `['labelsList', ...]` on settle — optimistic patch is enough, and refetching every list query on every click is costly. List queries refetch naturally on remount/filter change.

### 3.4 LabelTile (curate player) — always render when `labelId` present

`frontend/src/features/library/components/LabelTile.tsx`.

Signature change:

```ts
interface Props {
  labelId: string | null | undefined;
  labelName: string | null | undefined;  // NEW: fallback name from the playing track
  styleId: string;
}
```

Rendering logic:

| State                          | Renders                                                  |
|--------------------------------|----------------------------------------------------------|
| `labelId == null`              | `null`                                                   |
| Info loading                   | Name (from `labelName` prop) + `LabelPreferenceButtons`  |
| Info 404 / error               | Name (from `labelName` prop) + `LabelPreferenceButtons`  |
| Info loaded                    | Full card (current content) + buttons in the header      |

The "info missing" path uses `labelName` directly without consulting the (now-failed) query. The "info loaded" path uses `info.label_name` (canonical, possibly tidier than the track's stored label name).

Callers updated to pass `labelName`:

- `CurateSession.tsx`: `labelName={session.currentTrack?.label_name ?? null}`
- `CategoryPlayerPanel.tsx`: `labelName={effectiveRich?.label?.name ?? null}`

### 3.5 LabelsTable (`/library/:styleId`)

`frontend/src/features/library/components/LabelsTable.tsx`.

- New column `My` between `AI detected` and `Description`. Renders `LabelPreferenceButtons` for each row (size `sm`).
- The column is shown unconditionally — the user is always authenticated in this app.

### 3.6 Library list toolbar — `my` filter

`frontend/src/features/library/components/LibraryFilters.tsx` (or current toolbar).

- New `SegmentedControl` next to existing info-status filter: `All / Liked / Disliked / Unrated`.
- Drives URL param `?my=all|liked|disliked|unrated`. Default omitted = `all`.
- `useLabelsList` hook forwards the param to the API.

### 3.7 LabelDetailHeader

`frontend/src/features/library/components/LabelDetailHeader.tsx`.

- `LabelPreferenceButtons` rendered to the right of the AI badge in the title row. Size `md`.

## 4. i18n keys (new)

| key                                 | en                          |
|-------------------------------------|-----------------------------|
| `appshell.library`                  | `Library`                   |
| `library.prefs.like_aria`           | `Like label`                |
| `library.prefs.dislike_aria`        | `Dislike label`             |
| `library.prefs.unset_aria`          | `Remove preference`         |
| `library.list.col_my`               | `My`                        |
| `library.list.my_all`               | `All`                       |
| `library.list.my_liked`             | `Liked`                     |
| `library.list.my_disliked`          | `Disliked`                  |
| `library.list.my_unrated`           | `Unrated`                   |

## 5. State of the curate player tile (recap)

The current contract: `LabelTile` returns `null` when info is missing. The new contract: `LabelTile` returns `null` only when there is no `labelId`. Once a track exposes a `label_id`, the user can react, and the tile is the surface for that.

This is the only contract change that touches non-library code. The new prop `labelName` is required at the type level; both call sites (curate + categories) pass the value they already have.

## 6. Testing

### Backend

- Unit tests for `repository.upsert_user_label_pref`, `delete_user_label_pref`, `list_labels(my=...)`.
- Integration tests for `PUT /labels/{id}/preference`:
  - 204 for each of `liked` / `disliked` / `none`.
  - Idempotency: two `liked` calls in a row don't error.
  - Toggle: `liked` → `disliked` → `none` leaves the table empty.
  - 404 on unknown `label_id`.
  - 422 on invalid status.
- Integration tests for `GET /labels?my=liked` (only labels with `liked` rows for that user appear).
- Integration tests for `GET /me/label-preferences?status=liked` (pagination, status filter).
- Integration tests for `GET /labels/{id}` projecting `my_preference`.

### Frontend

- `LabelPreferenceButtons` — click on heart sets `liked`; click on heart while `liked` sets `none`; click on cross while `liked` sets `disliked`. Active icon is the filled variant.
- `useSetLabelPreference` — optimistic update applied immediately, rollback on error.
- `LabelTile` — when info is `null` and `labelName='Fokuz'`, renders `Fokuz` + buttons; when info loads, switches to full card.
- `LabelsTable` — renders `My` column with preference buttons; selecting `Liked` filter passes `my=liked` to the hook.
- `LabelDetailHeader` — buttons render next to AI badge, reflect server state.

## 7. Migration & rollout

- Single deploy: migration + backend + frontend ship together. No feature flag.
- The new table starts empty; pre-existing labels show as `unrated` until a user clicks.
- No data backfill needed.

## 8. File map

### Backend
- `alembic/versions/20260519_23_user_label_prefs.py` — new
- `src/collector/label_enrichment/repository.py` — extend `list_labels`, `get_label_info_for_user`; add `upsert_user_label_pref`, `delete_user_label_pref`, `list_user_label_prefs`
- `src/collector/label_enrichment/routes.py` — add `handle_put_label_preference`, `handle_get_my_label_preferences`; project `my_preference` in existing handlers
- `src/collector/handler.py` — register new routes
- `infra/api_gateway.tf` — `aws_apigatewayv2_route` for `PUT /labels/{label_id}/preference` and `GET /me/label-preferences`
- `scripts/generate_openapi.py` — ROUTES + schemas

### Frontend
- `frontend/src/routes/_layout.tsx` — new nav item
- `frontend/src/components/icons.ts` — re-export `IconBook`, `IconHeart`, `IconHeartFilled`, `IconX`
- `frontend/src/i18n/en.json` — new keys
- `frontend/src/api/labels.ts` — extend `LabelSummary`, `LabelDetail` types
- `frontend/src/features/library/hooks/useSetLabelPreference.ts` — new
- `frontend/src/features/library/hooks/useLabelsList.ts` — pass `my` param
- `frontend/src/features/library/components/LabelPreferenceButtons.tsx` — new
- `frontend/src/features/library/components/LabelTile.tsx` — new `labelName` prop, always-render logic
- `frontend/src/features/library/components/LabelsTable.tsx` — new `My` column
- `frontend/src/features/library/components/LibraryFilters.tsx` (or current toolbar) — new `my` SegmentedControl
- `frontend/src/features/library/components/LabelDetailHeader.tsx` — buttons next to AI badge
- `frontend/src/features/library/routes/LibraryListPage.tsx` — wire `my` URL param
- `frontend/src/features/curate/components/CurateSession.tsx` — pass `labelName`
- `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — pass `labelName`

### Tests
- `tests/unit/label_enrichment/test_user_label_prefs_repo.py` — new
- `tests/integration/label_enrichment/test_put_label_preference.py` — new
- `tests/integration/label_enrichment/test_get_my_label_preferences.py` — new
- `tests/integration/label_enrichment/test_list_labels_my_filter.py` — new
- `frontend/src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx` — new
- `frontend/src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx` — new
- `frontend/src/features/library/components/__tests__/LabelTile.test.tsx` — extend with no-info + labelName case
- `frontend/src/features/library/components/__tests__/LabelsTable.test.tsx` — new column assertion

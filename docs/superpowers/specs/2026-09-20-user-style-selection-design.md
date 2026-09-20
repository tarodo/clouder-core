# Per-user style selection — design

**Date:** 2026-09-20
**Status:** Approved (design phase)

## Problem

`clouder_styles` is a shared canonical dictionary: every Beatport ingest
auto-creates a row for each genre it sees (`canonicalize.py:_resolve_style` →
`repositories.create_style`). Nothing ever removes one — the table has no
`deleted_at`, no `DELETE` route, and its FKs (`clouder_tracks.style_id`,
`categories.style_id`, `triage_blocks.style_id`) carry no cascade, so a style
with any data cannot be deleted at all.

The user works in a handful of styles. Every dropdown shows the full catalog,
and the noise grows with every ingest. The default style is also unstable:
redirects fall back to `items[0]` and the list is sorted `created_at DESC`
(`repositories.py:list_styles`), so the newest ingested genre silently becomes
the default.

## Goal

Let each user pick the styles they work in. Those — and only those — appear in
the dropdowns, in an order the user controls.

### Non-goals

- Deleting or hiding styles globally. The catalog stays shared and intact.
- Touching any track, category or triage data. The selection is a view filter.
- Per-feature selections (a different set for triage than for library). One set
  per user.
- Admin screens. They work against the whole catalog by design.

## Decisions

| Question | Decision |
|---|---|
| Empty selection | Means "no filter" — the full catalog is returned. The feature is opt-in; nothing changes for a user who never visits it, and no data backfill is needed. |
| Scope of the filter | Everywhere except admin screens. |
| Data in a deselected style | Untouched. Direct URLs (`/categories/<styleId>`) keep working. |
| Where the UI lives | A section on the existing `/profile` page. |
| Ordering | User-controlled, drag & drop, persisted as `position`. |
| Where filtering happens | Server-side, inside `GET /styles`. |

### Why filter server-side

`useStyles()` is called from 13 places (`StyleSelector`, all three
`*IndexRedirect`s, `HomePage`, `LibraryListPage`, `ArtistsListPage`,
`AddTracksModal`, `CurateSetupPage`, `CategoriesListPage`, `TriageListPage`,
and two admin backlog pages). Making the endpoint personal means the frontend
hook is unchanged and no caller can be forgotten; only the exceptions (admin
pages, the profile section) opt out via `?scope=all`. The alternatives — a
separate `/me/styles` endpoint, or intersecting on the client — both push a
13-way decision onto the frontend and make "we forgot one screen" the default
failure mode.

## Data model

New table, modelled on `clouder_user_label_prefs`
(`alembic/versions/20260519_23_user_label_prefs.py`):

```
clouder_user_style_prefs
  user_id    varchar(36)  NOT NULL  FK users.id          ON DELETE CASCADE
  style_id   varchar(36)  NOT NULL  FK clouder_styles.id ON DELETE CASCADE
  position   integer      NOT NULL
  updated_at timestamptz  NOT NULL
  PRIMARY KEY (user_id, style_id)
  INDEX idx_user_style_prefs_user_position (user_id, position)
```

`position` is dense and 0-based, rewritten wholesale on every update.
`ON DELETE CASCADE` on `style_id` also means a style removed from the catalog
disappears from every selection on its own.

Migration adds the table only. No backfill: an empty selection already behaves
exactly like today.

## API

### `GET /styles` — now personal

- Selection non-empty → only those styles, `ORDER BY position`.
- Selection empty → the whole catalog, `ORDER BY created_at DESC` (unchanged).
- `limit` / `offset` / `search` keep their current semantics. `total` counts the
  rows the caller can actually see.
- Response shape unchanged: `{items, total, limit, offset, correlation_id}`.

Keeping the empty-selection sort as-is means this change is invisible to anyone
who has not opted in.

### `GET /styles?scope=all` — the catalog

Every style, plus two fields per item:

```json
{"id": "...", "name": "Drum & Bass", "selected": true, "position": 0}
```

Base fields (`id`, `name`, `normalized_name`, `created_at`, `updated_at`) are
unchanged; `selected` and `position` are additive. `position` is `null` when
`selected` is `false`. Ordering: selected first by `position`, then the rest by
`name`. Available to any authenticated user — it is not an admin route; the
profile section and the two admin backlog pages both use it.

The generated OpenAPI contract reuses the shared `LIST_RESPONSE_TEMPLATE`
(`scripts/generate_openapi.py`), so `selected` and `position` are documented
in this prose but are not part of the generated item schema. `CatalogStyle`
on the frontend (`frontend/src/hooks/useAllStyles.ts`) is therefore a
hand-maintained contract that the frontend CI schema diff-check cannot
protect — a backend field rename here would not fail that check.

### `PUT /me/styles` — replace the selection

```json
{"style_ids": ["<uuid>", "<uuid>", "..."]}
```

Array order *is* the order. Responds `204`. An empty array clears the selection
(back to "all styles visible").

One idempotent replace covers both checkbox toggling and drag & drop — there is
no separate reorder route, and therefore no window where an add and a reorder
race each other.

Validation errors, all `400 validation_error`:

| Case | Message |
|---|---|
| `style_ids` missing or not an array | `style_ids must be an array` |
| duplicate ids | `style_ids must be unique` |
| more than 100 ids | `style_ids exceeds 100 entries` |
| any id absent from `clouder_styles` | `unknown style_id: <id>` |

Any `scope` value other than `all` is a `400 validation_error`
(`scope must be 'all'`). `limit` stays capped at 200 by
`_parse_pagination_params`, which is above the size of the style catalog.

Other responses: `401` unauthenticated (authorizer), `503 db_not_configured`.

## Backend

New package `src/collector/user_styles/`, following the `label_enrichment`
layout:

- `repository.py` — `UserStylesRepository(data_api)`:
  - `list_for_user(user_id, limit, offset, search)` — `JOIN` on the prefs table,
    `ORDER BY p.position`.
  - `count_for_user(user_id, search)`.
  - `list_catalog(user_id, limit, offset, search)` — `LEFT JOIN` prefs,
    projecting `selected` / `position`, `ORDER BY (p.position IS NULL),
    p.position, s.name`.
  - `count_catalog(search)`.
  - `replace_selection(user_id, style_ids, now)` — one transaction:
    `SELECT id FROM clouder_styles` for the requested ids (validation),
    `DELETE FROM clouder_user_style_prefs WHERE user_id = :user_id`, then one
    `INSERT` per id with its index as `position`. Row-at-a-time inserts match
    the existing `CategoriesRepository.reorder` pattern and keep the Data API
    parameter binding simple.
- `routes.py` — `handle_get_styles(event)` and `handle_put_my_styles(event)`,
  returning `(status, body)` tuples like the enrichment routes. `user_id` comes
  from `requestContext.authorizer.lambda.user_id` via a local `_extract_user_id`
  helper (the same one already duplicated across four route modules; unifying it
  is out of scope here).

Changes in `src/collector/handler.py`:

- Remove `"GET /styles"` from `_LIST_ROUTES` — it now needs `user_id` and
  `scope`, which the generic list handler does not carry.
- Route `GET /styles` and `PUT /me/styles` to `user_styles.routes`, matching the
  existing per-route dispatch style.

`ClouderRepository.list_styles` / `count_styles` lose their only caller and are
deleted; their logic moves into `UserStylesRepository`.

Route registration must land in all three places (a missing gateway route
returns `{"message":"Not Found"}`):

1. `src/collector/handler.py` dispatch,
2. `scripts/generate_openapi.py` — pull `"styles"` out of the
   `("tracks", "albums", "styles")` loop into its own entry with the `scope`
   parameter and the extended item schema, and add `PUT /me/styles`,
3. `infra/api_gateway.tf` — new `PUT /me/styles` route with the JWT authorizer
   (`GET /styles` already exists).

Then regenerate: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`,
and refresh `frontend/src/api/schema.d.ts` (CI diff-checks it).

## Frontend

**Hooks** (`frontend/src/hooks/`):

- `useStyles()` — unchanged, key `['styles']`. It is now personal by virtue of
  the endpoint.
- `useAllStyles()` — new, key `['styles', 'all']`, fetches
  `/styles?scope=all&limit=200`. Items carry `selected` and `position`.
- `useUpdateMyStyles()` — new, `PUT /me/styles`, 200 ms debounce copied from
  `useReorderCategories`; on success invalidates both `['styles']` and
  `['styles', 'all']`; on error re-invalidates and shows a red toast.

**Profile section** (`frontend/src/features/profile/`):

`routes/profile.tsx` currently centres a 28-line block (`<Center mih="60vh">`);
it becomes a normal top-aligned `Stack` with the existing identity/sign-out
block plus a new `MyStylesSection`.

`MyStylesSection` has two zones:

- **My styles** — the selected set as a sortable list (`@dnd-kit`), each row
  with a drag handle and a remove action. Reordering and removal both call
  `useUpdateMyStyles` with the full new array. Per the repo's dnd rule, the list
  uses `DragOverlay` + `dropAnimation={null}` +
  `animateLayoutChanges={() => false}` (as in `PlaylistTracksList`).
- **Add a style** — searchable list of the unselected remainder; clicking one
  appends it to the end of the selection.

When the selection is empty the section shows an explicit hint that all styles
are currently visible, so "empty" never reads as "broken".

Updates are optimistic against the `['styles', 'all']` cache, with the debounced
`PUT` behind them.

**Admin screens** switch to `useAllStyles()`:
`AdminEnrichmentBacklogPage`, `AdminArtistEnrichmentBacklogPage`.

Everything else keeps `useStyles()` and is filtered automatically.

## Edge cases

- **Last-visited style no longer in the set.** `localStorage`
  (`clouder.lastStyleId`, `clouder.lastTriageStyleId`) may point at a deselected
  style. The redirects already do `items.find(s => s.id === last)?.id ??
  items[0]?.id`, so they fall back correctly with no change.
- **Direct URL into a deselected style.** Keeps working — category, triage and
  library pages fetch by `styleId` and never consult the style list.
- **Selection that empties itself.** Removing the last style is allowed and
  means "show everything" again; the UI says so.
- **Style deleted from the catalog.** FK cascade removes the pref rows.
- **Concurrent updates from two tabs.** Last write wins. The set is small,
  single-user data; versioning it would cost more than the conflict.
- **`search` combined with a selection.** Filters within the selection, not the
  catalog — `?scope=all` is the way to search everything.
- **Catalog page-size ceiling.** `useAllStyles` requests `limit=200` and
  filters client-side; it does not page. Past 200 styles, the "Add a style"
  list silently truncates. Selected rows sort first (`list_catalog`'s
  `ORDER BY (p.position IS NULL), p.position, s.name`), so a user's existing
  selection is unaffected — it's the unselected tail of the alphabet that
  disappears from the add list. Server-side `search` (already supported by
  `?scope=all&search=`) is the exit once the catalog outgrows 200 rows.

## Testing

Backend (`pytest`):

- `tests/unit/test_user_styles_repository.py` — `FakeDataApi` stub as in
  `test_label_enrichment_prefs_repo.py`: SQL/params for `list_for_user`,
  `list_catalog`, and `replace_selection` (delete-then-insert, positions 0..n-1).
- `tests/unit/test_handler_my_styles.py` — `PUT` validation matrix (non-array,
  duplicates, >100, unknown id), `204` on success, `401`, `503`.
- `tests/integration/test_handler.py` — update the existing
  `test_list_styles_returns_results`; add: empty selection → full catalog,
  non-empty → filtered and ordered by `position`, `scope=all` → `selected` /
  `position` present.

Frontend (`pnpm test`): `useAllStyles` query shape, `useUpdateMyStyles`
(debounce, invalidation, error toast), `MyStylesSection` (select, deselect,
empty-state hint), and the two admin pages still seeing the full catalog.

Browser (`pnpm test:browser`): the drag & drop reorder in `MyStylesSection` —
jsdom applies no stylesheets, so the overlay/drop behaviour cannot be verified
there.

Before merging, run the frontend CI gates locally: `pnpm typecheck`, `pnpm lint`,
`pnpm test`.

## Rollout

Order matters — the frontend must not ship before the routes exist:

1. `alembic upgrade head` (new table).
2. `scripts/package_lambda.sh` + deploy the collector Lambda.
3. `terraform apply` in `infra/` (adds `PUT /me/styles`).
4. Regenerate `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts`.
5. Deploy the frontend.

Steps 1–3 are backward compatible: with no rows in
`clouder_user_style_prefs`, `GET /styles` behaves exactly as it does today.

**Step 1 must complete before step 2's code serves traffic.** Every branch of
`GET /styles` touches `clouder_user_style_prefs`: `?scope=all` LEFT JOINs it in
`list_catalog`, and every other request calls `count_selection` against it
before deciding which list to return. So new collector code running against a
database that doesn't have the table yet 500s on the hot path used by all 13
style-dropdown screens. `infra/lambda.tf` packages the migration Lambda and
the collector API from the same zip, so `terraform apply` and invoking the
migration Lambda are two independent, unordered actions — nothing stops an
operator from applying Terraform first and running the migration after,
inverting steps 1 and 2. Do one of:

- run `alembic upgrade head` over a tunnel before packaging the zip, or
- deploy the zip and invoke the migration Lambda directly, and only then let
  `terraform apply` move the API Gateway integration onto the new code.

Rollback is safe in the other direction: reverting the collector code alone
is fine even with the table still present, since old code never queries it.

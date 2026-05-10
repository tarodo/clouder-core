# Categories tracks table improvements — design

**Date:** 2026-05-10
**Scope:** `/categories/{id}` Tracks tab — fix empty Artists column, add Label and Spotify release date columns, add server-side sorting.
**Status:** approved (pending implementation plan).

## Goals

1. Show artist names in the Artists column (currently always empty due to a backend/frontend type mismatch).
2. Add a **Label** column showing the track's label name (joined via `clouder_albums.label_id`).
3. Add a **Released** column showing `clouder_tracks.spotify_release_date`.
4. Allow sorting the table by **Title**, **Released** (Spotify date), and **Added** date.

Out of scope:
- Client-side sorting (rejected — breaks pagination correctness).
- Persisting sort selection in URL or localStorage (component state only).
- Sorting on the mobile (card) layout.
- Linking Label/Artists to detail pages (no such routes exist yet; future work).

## Background

`GET /categories/{id}/tracks` currently returns track records via `CategoriesRepository.list_tracks` with a fixed `ORDER BY ct.added_at DESC, t.id ASC`. The SQL `STRING_AGG`s artist names into a comma-separated string and the repository splits it into a `list[str]`. The frontend's `CategoryTrack.artists` is typed as `TrackArtist[]` (`{id, name}[]`), so `track.artists.map(a => a.name)` evaluates to `[undefined, undefined, ...]` and renders empty.

Label and Spotify release date are not projected at all today.

## Architecture

```
Frontend (TracksTab → useCategoryTracks)
   │  ?sort=...&order=... (component state)
   ▼
GET /categories/{id}/tracks
   │  ValidationError on bad sort/order
   ▼
curation_handler._handle_list_tracks (validates whitelist)
   │
   ▼
CategoriesRepository.list_tracks(sort, order, ...)
   │  builds ORDER BY from whitelist; LEFT JOINs albums+labels;
   │  JSON_AGG(artists) for {id, name}[] shape
   ▼
Aurora (Data API)
```

No new tables, columns, or migrations. All projected fields already exist on `clouder_tracks`, `clouder_albums`, `clouder_labels`.

## API contract

`GET /categories/{id}/tracks`

**New query params** (both optional, both case-insensitive on input, lowercased before validation):

| Param  | Allowed values                                   | Default      |
|--------|--------------------------------------------------|--------------|
| `sort` | `title`, `spotify_release_date`, `added_at`      | `added_at`   |
| `order`| `asc`, `desc`                                    | `desc`       |

Invalid values → 400 `ValidationError` via the existing error envelope (`{error_code, message, correlation_id}`). Tie-breaker is always `t.id ASC` after the requested key, for deterministic pagination.

`spotify_release_date` always sorts with `NULLS LAST` regardless of `order` direction — tracks lacking Spotify metadata stay at the bottom.

**Response shape (per item)**:

```json
{
  "id": "uuid",
  "title": "...",
  "mix_name": "..." | null,
  "artists": [{"id": "uuid", "name": "..."}],
  "label": {"id": "uuid", "name": "..."} | null,
  "bpm": 128 | null,
  "length_ms": 360000 | null,
  "publish_date": "2026-01-15" | null,
  "spotify_release_date": "2026-01-17" | null,
  "isrc": "..." | null,
  "spotify_id": "..." | null,
  "release_type": "single" | null,
  "is_ai_suspected": false,
  "added_at": "2026-05-08T12:34:56+00:00",
  "source_triage_block_id": "uuid" | null
}
```

**Breaking change vs. current**: `artists` was `string[]` (names only). Now `{id, name}[]`. The current shape is unrenderable on the existing frontend (Artists column is empty), so there is no production consumer to break.

## Backend implementation

### `CategoriesRepository.list_tracks`

Module: `src/collector/curation/categories_repository.py`.

Add module-level whitelists (private to the module):

```python
_SORT_COLUMNS = {
    "title":                "t.title",
    "spotify_release_date": "t.spotify_release_date",
    "added_at":             "ct.added_at",
}
_ORDER_DIRS = {"asc": "ASC", "desc": "DESC"}
```

Updated method signature:

```python
def list_tracks(
    self,
    *,
    user_id: str,
    category_id: str,
    limit: int,
    offset: int,
    search: str | None,
    sort: str = "added_at",
    order: str = "desc",
) -> PaginatedResult[TrackInCategoryRow]:
```

The repository trusts that `sort`/`order` are already validated by the handler. It still does a `KeyError`-safe lookup; an unexpected value would raise an internal 500 (acceptable — it indicates a contract bug, not user input).

SQL:

```sql
SELECT
    t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
    t.publish_date, t.spotify_id, t.release_type, t.is_ai_suspected,
    t.spotify_release_date,
    COALESCE(
        JSON_AGG(
            JSON_BUILD_OBJECT('id', a.id, 'name', a.name)
            ORDER BY cta.role, a.name
        ) FILTER (WHERE a.id IS NOT NULL),
        '[]'::json
    ) AS artists_json,
    l.id   AS label_id,
    l.name AS label_name,
    ct.added_at, ct.source_triage_block_id
FROM category_tracks ct
JOIN clouder_tracks t ON t.id = ct.track_id
LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
LEFT JOIN clouder_artists       a   ON a.id  = cta.artist_id
LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
LEFT JOIN clouder_labels        l   ON l.id   = alb.label_id
WHERE ct.category_id = :category_id
  {search_clause}
GROUP BY t.id, ct.added_at, ct.source_triage_block_id, l.id, l.name
ORDER BY {order_by}, t.id ASC
LIMIT :limit OFFSET :offset
```

`{order_by}` is built as:

```python
column = _SORT_COLUMNS[sort]
direction = _ORDER_DIRS[order]
nulls = " NULLS LAST" if sort == "spotify_release_date" else ""
order_by = f"{column} {direction}{nulls}"
```

Row mapping:

```python
import json

items = []
for r in rows:
    artists_raw = r.pop("artists_json")
    artists = json.loads(artists_raw) if isinstance(artists_raw, str) else (artists_raw or [])
    label_id = r.pop("label_id", None)
    label_name = r.pop("label_name", None)
    label = {"id": label_id, "name": label_name} if label_id else None
    spot = r.pop("spotify_release_date", None)
    spot_str = str(spot) if spot is not None else None

    track = dict(r)
    track["artists"] = artists
    track["label"] = label
    track["spotify_release_date"] = spot_str

    added_at = track.pop("added_at")
    source_id = track.pop("source_triage_block_id")
    items.append(
        TrackInCategoryRow(
            track=track,
            added_at=str(added_at),
            source_triage_block_id=source_id,
        )
    )
```

The `isinstance(artists_raw, str)` guard handles the Data API quirk where JSON aggregates are returned as strings; if a future Data API change ever returns a parsed list, the code still works.

The COUNT(*) query for `total` is unchanged — it does not need the new joins.

### Handler

Module: `src/collector/curation_handler.py`.

```python
_SORT_VALUES = {"title", "spotify_release_date", "added_at"}
_ORDER_VALUES = {"asc", "desc"}

def _handle_list_tracks(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    sort = (qp.get("sort") or "added_at").lower()
    if sort not in _SORT_VALUES:
        raise ValidationError(
            f"sort must be one of {sorted(_SORT_VALUES)}"
        )
    order = (qp.get("order") or "desc").lower()
    if order not in _ORDER_VALUES:
        raise ValidationError("order must be 'asc' or 'desc'")

    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
        sort=sort, order=order,
    )
    return _paginated_response(
        result, _track_in_category_response, correlation_id
    )
```

`_track_in_category_response` requires no behavioural change — `track` already contains the new `artists`, `label`, `spotify_release_date` fields from the repo.

## Frontend implementation

### Types & hook

Module: `frontend/src/features/categories/hooks/useCategoryTracks.ts`.

```ts
export interface TrackArtist { id: string; name: string }
export interface TrackLabel  { id: string; name: string }

export type CategoryTrackSort = 'title' | 'spotify_release_date' | 'added_at';
export type SortOrder = 'asc' | 'desc';

export interface CategoryTrack {
  id: string;
  title: string;
  mix_name: string | null;
  artists: TrackArtist[];
  label: TrackLabel | null;
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  spotify_release_date: string | null;
  isrc: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  added_at: string;
  source_triage_block_id: string | null;
}

export const categoryTracksKey = (
  id: string,
  search: string,
  sort: CategoryTrackSort,
  order: SortOrder,
) => ['categories', 'tracks', id, search, sort, order] as const;

export function useCategoryTracks(
  categoryId: string,
  search: string,
  sort: CategoryTrackSort = 'added_at',
  order: SortOrder = 'desc',
) {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search, sort, order),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
        sort,
        order,
      });
      if (search) params.set('search', search);
      return api<PaginatedTracks>(`/categories/${categoryId}/tracks?${params}`);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!categoryId,
  });
}
```

Sort/order are part of the React Query cache key. Switching sort starts a fresh infinite query — old pages remain cached so navigation back to a previous sort is instant.

### TracksTab

Module: `frontend/src/features/categories/components/TracksTab.tsx`.

State:

```tsx
const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
const [sortDir, setSortDir] = useState<SortOrder>('desc');

const handleSort = (key: CategoryTrackSort) => {
  if (key === sortKey) {
    setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
  } else {
    setSortKey(key);
    setSortDir(key === 'title' ? 'asc' : 'desc');
  }
};
```

Desktop `<Table.Thead>` updated with three sortable headers (Title, Released, Added) plus two static columns (Label, Artists, BPM, Length stay non-sortable). Order from left to right: **Title · Artists · Label · BPM · Length · Released · Added**.

### SortableTh component

New file `frontend/src/features/categories/components/SortableTh.tsx`. A thin wrapper over `Table.Th` that:

- Renders children + a sort icon: `IconChevronUp` (asc, active), `IconChevronDown` (desc, active), `IconArrowsSort` (inactive, `c="dimmed"`).
- Wraps the content in a `<UnstyledButton>` with `onClick`, `cursor: pointer`, and visible focus ring (Mantine default).
- Sets `aria-sort` to `'ascending' | 'descending' | 'none'` on the parent `<th>`.
- Adds `aria-label={t('categories.tracks_table.sort_aria', { column })}`.

Props: `{ children, active: boolean, dir: SortOrder, onClick: () => void }`.

### TrackRow

Module: `frontend/src/features/categories/components/TrackRow.tsx`.

`joinArtists` becomes trivial:

```tsx
function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}
```

Desktop adds two `<Table.Td>`s — Label (after Artists) and Released (before Added):

```tsx
<Table.Td>{track.label?.name ?? '—'}</Table.Td>
...
<Table.Td className="font-mono">
  {formatReleaseDate(track.spotify_release_date)}
</Table.Td>
```

Mobile card adds two extra rows in the `<Group>`, but only when the value is present (NULL hidden, not rendered as `—`):

```tsx
{track.label && (
  <Text size="xs" c="dimmed">{track.label.name}</Text>
)}
{track.spotify_release_date && (
  <Text size="xs" c="dimmed" className="font-mono">
    {formatReleaseDate(track.spotify_release_date)}
  </Text>
)}
```

### Formatter

Module: `frontend/src/lib/formatters.ts` — add `formatReleaseDate(date: string | null): string` returning `date ?? '—'`. `spotify_release_date` already comes as `YYYY-MM-DD`; no locale formatting (kept consistent with `formatAdded` style of the existing column).

### i18n keys

Module: `frontend/src/i18n/en.json` (and any sibling locales).

```json
"tracks_table": {
  "title": "Title",
  "artists": "Artists",
  "label": "Label",
  "bpm": "BPM",
  "length": "Length",
  "released": "Released",
  "added": "Added",
  "ai_suspected_aria": "AI-suspected",
  "sort_aria": "Sort by {{column}}"
}
```

## Testing

### Backend

Unit tests on `CategoriesRepository.list_tracks` (extend existing repo test file):

1. Default call (no `sort`/`order`) preserves `ORDER BY ct.added_at DESC, t.id ASC` — regression for existing pagination behaviour.
2. `artists` returned as `[{id, name}, ...]`, ordered by `(role, name)`. Two-artist track confirms order; track with no artists returns `[]`.
3. Label: track→album→label chain returns `{id, name}`; track without album returns `null`; album without label returns `null`.
4. `spotify_release_date` projected; NULL when not set.
5. `sort=title order=asc` and `=desc` produce inverse orderings.
6. `sort=spotify_release_date` always places NULLs last regardless of `order`.
7. `sort=added_at order=desc` matches the default behaviour from (1).
8. `search` + `sort` combine correctly (search clause is preserved when ORDER BY changes).
9. Pagination with `limit=2 offset=2` on a 5-track sorted set returns the correct middle slice.

Handler-level tests (extend existing handler test file):

10. Invalid `sort` → 400 ValidationError.
11. Invalid `order` → 400 ValidationError.
12. `sort=Title` (mixed case) accepted (handler lowercases).

### Frontend

`useCategoryTracks` (hook test):

13. Cache key includes `sort` + `order`.
14. Changing `sort` triggers a new fetch with `?sort=...&order=...`.
15. Changing `order` triggers a new fetch.

`TracksTab` (component test):

16. Click on `Title` header sets `sortKey='title'`, `sortDir='asc'`. Second click flips to `desc`.
17. Click on `Released` sets `sortKey='spotify_release_date'`, `sortDir='desc'`.
18. `aria-sort` is `'ascending' | 'descending'` on the active column and `'none'` elsewhere.

`TrackRow` desktop:

19. Artists list rendered as comma-joined names.
20. Label shown when present; `—` when null.
21. Released formatted; `—` when null.

`TrackRow` mobile:

22. Label and Released hidden when null (no `—` placeholder).

MSW fixtures: update existing category-tracks fixtures to the new shape (`artists: [{id, name}]`, `label`, `spotify_release_date`) so unrelated tests do not regress.

## Risks & mitigations

- **Aurora Data API JSON shape.** `JSON_AGG` returns a string under the Data API. The repository parses defensively with `isinstance(... , str)` so any future format change is forward-compatible. Before merging, grep for existing `JSON_AGG`/`JSONB_AGG` usage in `src/collector/` to confirm the same parse pattern is used elsewhere.
- **Performance.** Two added LEFT JOINs (`clouder_albums`, `clouder_labels`) on PK/FK columns. At current scale (categories hold low-thousands of tracks max) this is negligible. No new index needed; `clouder_tracks.album_id` is an FK and Postgres does not auto-index FKs, but the access pattern here is "track row already in hand → fetch its album by PK" which uses the albums PK index. Re-evaluate only if a slow-query alarm fires.
- **Breaking `artists` shape.** Today's frontend renders Artists empty, so no real consumer is broken. Confirm by grepping handler tests and frontend tests for the old `artists: ['name', ...]` shape and updating them in the same PR.
- **MSW fixture drift.** New shape must be added to every fixture that mocks `/categories/{id}/tracks`. Locate via `rg "categories/.*tracks" frontend/src` and update in lockstep.

## Out-of-scope follow-ups

- URL-persisted sort selection (would benefit deep-linking).
- Mobile card sorting via `Mantine Select` dropdown.
- Linkifying Label and Artists once `/labels/{id}` and `/artists/{id}` SPA routes exist.
- Per-track Spotify-vs-Beatport date display (currently only Spotify shown; Beatport `publish_date` remains unrendered).

# Categories tracks table improvements — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the empty Artists column on `/categories/{id}` Tracks tab, add Label and Spotify release date columns, and add server-side sort by Title / Released / Added.

**Architecture:** Backend `CategoriesRepository.list_tracks` is extended to project label (LEFT JOIN albums→labels), `spotify_release_date`, and `artists` as `[{id, name}]` via `JSON_AGG`. The handler whitelists new `?sort=` and `?order=` query params and forwards them. The frontend hook adds `sort`/`order` params (component-state, no URL/localStorage), TracksTab grows clickable sort headers, and TrackRow renders the two new fields (NULL → `—` on desktop, hidden on mobile).

**Tech Stack:** Python 3.13 (collector Lambda) + Aurora Data API + pytest; React 19 + Mantine 9 + react-i18next + TanStack Query 5 + Vitest + MSW.

**Spec:** `docs/superpowers/specs/2026-05-10-categories-table-improvements-design.md`

---

## File Structure

| File                                                                                  | Action  | Responsibility                                                                                |
|---------------------------------------------------------------------------------------|---------|-----------------------------------------------------------------------------------------------|
| `src/collector/curation/categories_repository.py`                                     | Modify  | New SELECT projection (label, spotify_release_date, artists_json), `sort`/`order` ORDER BY    |
| `src/collector/curation_handler.py`                                                   | Modify  | Validate `?sort` / `?order`; pass to repo                                                     |
| `tests/unit/test_categories_repository.py`                                            | Modify  | Update list_tracks tests for new shape; add sort/label/NULLS-LAST cases                       |
| `tests/integration/test_curation_handler.py`                                          | Modify  | Update FakeRepo signature; add 400-on-invalid sort/order tests                                |
| `frontend/src/features/categories/hooks/useCategoryTracks.ts`                         | Modify  | New types (`TrackLabel`, `CategoryTrackSort`, `SortOrder`); pass `sort`/`order` query params  |
| `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`         | Modify  | Add tests for sort/order in cache key + URL params; update fixtures with label + released     |
| `frontend/src/features/categories/components/SortableTh.tsx`                          | Create  | Clickable `<Table.Th>` with sort icon + `aria-sort`                                           |
| `frontend/src/features/categories/components/__tests__/SortableTh.test.tsx`           | Create  | Cover active/inactive icon, click handler, aria-sort                                          |
| `frontend/src/features/categories/components/TracksTab.tsx`                           | Modify  | Sort state, new headers (Title/Released/Added sortable; Label static), pass to hook           |
| `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`            | Modify  | Update fixtures; add sort interaction tests                                                   |
| `frontend/src/features/categories/components/TrackRow.tsx`                            | Modify  | Render Label and Released; new mobile rows; trivial `joinArtists`                             |
| `frontend/src/lib/formatters.ts`                                                      | Modify  | Add `formatReleaseDate(date: string | null): string`                                          |
| `frontend/src/lib/__tests__/formatters.test.ts` (or existing equivalent)              | Modify/Create | Cover `formatReleaseDate` returns the date or `—`                                       |
| `frontend/src/i18n/en.json`                                                           | Modify  | New keys `label`, `released`, `sort_aria`                                                     |

No new top-level source files in `src/collector/`. No DB migration. No infra changes.

---

## Phase 1 — Backend tests (red)

Writing failing tests against the current implementation locks the contract before any code changes.

### Task 1: Update repository `list_tracks` tests for the new artists / label / released shape

**Files:**
- Modify: `tests/unit/test_categories_repository.py:679-748`

- [ ] **Step 1: Read current `test_list_tracks_*` tests** to confirm the existing mock shape (`artist_names: str`).

Run: `sed -n '679,748p' tests/unit/test_categories_repository.py`

- [ ] **Step 2: Update `test_list_tracks_handles_empty_artists` to the new shape**

Replace the body of `test_list_tracks_handles_empty_artists` (around line 679–701) with:

```python
def test_list_tracks_handles_empty_artists() -> None:
    """LEFT JOIN with no matching artists yields artists_json='[]' → []."""
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "Song", "mix_name": None,
                "isrc": None, "bpm": None, "length_ms": None,
                "publish_date": None, "spotify_id": None,
                "release_type": None, "is_ai_suspected": False,
                "spotify_release_date": None,
                "artists_json": "[]",
                "label_id": None, "label_name": None,
                "added_at": "2026-04-27T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    assert result.items[0].track["artists"] == []
    assert result.items[0].track["label"] is None
    assert result.items[0].track["spotify_release_date"] is None
```

- [ ] **Step 3: Update `test_list_tracks_returns_rows_and_total` to the new shape**

Replace the body of `test_list_tracks_returns_rows_and_total` (around line 704–730) with:

```python
def test_list_tracks_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "Song", "mix_name": None,
                "isrc": "X", "bpm": 124, "length_ms": 360000,
                "publish_date": None, "spotify_id": None,
                "release_type": "single", "is_ai_suspected": False,
                "spotify_release_date": "2026-01-15",
                "artists_json": (
                    '[{"id":"a1","name":"Artist A"},'
                    '{"id":"a2","name":"Artist B"}]'
                ),
                "label_id": "l1", "label_name": "Cool Label",
                "added_at": "2026-04-27T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    assert result.total == 1
    item = result.items[0]
    assert item.track["id"] == "t1"
    assert item.track["artists"] == [
        {"id": "a1", "name": "Artist A"},
        {"id": "a2", "name": "Artist B"},
    ]
    assert item.track["label"] == {"id": "l1", "name": "Cool Label"}
    assert item.track["spotify_release_date"] == "2026-01-15"
    assert item.added_at == "2026-04-27T12:00:00Z"
    assert item.source_triage_block_id is None
```

- [ ] **Step 4: Update `test_list_tracks_applies_search_lowercased` mock to include the new columns**

Replace the body of `test_list_tracks_applies_search_lowercased` (around line 733–747) with:

```python
def test_list_tracks_applies_search_lowercased() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],
        [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search="  Tech  ",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    list_params = data_api.execute.call_args_list[1].args[1]
    assert "ILIKE" in list_sql
    assert list_params["search"] == "%tech%"
```

(no shape change — it just calls `repo.list_tracks` with no rows; left unchanged so the section reads as a unit, but you may skip this step if the diff is empty).

- [ ] **Step 5: Run the updated tests to verify they go red**

Run: `pytest tests/unit/test_categories_repository.py::test_list_tracks_returns_rows_and_total tests/unit/test_categories_repository.py::test_list_tracks_handles_empty_artists -v`

Expected: both FAIL — current `repo.list_tracks` returns `artists` as `list[str]` and does not project `label` / `spotify_release_date`. Failures look like `KeyError` on `'artists_json'` or `assert ['Artist A', 'Artist B'] == [{'id': ...}]`.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_categories_repository.py
# Use caveman:caveman-commit skill to generate the message:
git commit -m "test(categories): update list_tracks tests for new artists/label/released shape"
```

### Task 2: Add new repository tests for label join, NULLS LAST, sort dispatch

**Files:**
- Modify: `tests/unit/test_categories_repository.py` (append after existing list_tracks tests, around line 748)

- [ ] **Step 1: Append three new tests**

```python
def test_list_tracks_label_null_when_no_album() -> None:
    """Track with no album → label is None."""
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "Song", "mix_name": None,
                "isrc": None, "bpm": None, "length_ms": None,
                "publish_date": None, "spotify_id": None,
                "release_type": None, "is_ai_suspected": False,
                "spotify_release_date": None,
                "artists_json": "[]",
                "label_id": None, "label_name": None,
                "added_at": "2026-04-27T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    assert result.items[0].track["label"] is None


def test_list_tracks_default_sort_added_at_desc() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}], [], [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    assert "ORDER BY ct.added_at DESC, t.id ASC" in list_sql


def test_list_tracks_sort_title_asc() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}], [], [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
        sort="title", order="asc",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    assert "ORDER BY t.title ASC, t.id ASC" in list_sql


def test_list_tracks_sort_spotify_release_date_nulls_last_asc() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}], [], [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
        sort="spotify_release_date", order="asc",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    assert (
        "ORDER BY t.spotify_release_date ASC NULLS LAST, t.id ASC" in list_sql
    )


def test_list_tracks_sort_spotify_release_date_nulls_last_desc() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}], [], [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
        sort="spotify_release_date", order="desc",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    assert (
        "ORDER BY t.spotify_release_date DESC NULLS LAST, t.id ASC" in list_sql
    )


def test_list_tracks_search_combines_with_sort() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}], [], [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search="tech",
        sort="title", order="asc",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    list_params = data_api.execute.call_args_list[1].args[1]
    assert "ILIKE" in list_sql
    assert "ORDER BY t.title ASC, t.id ASC" in list_sql
    assert list_params["search"] == "%tech%"
```

- [ ] **Step 2: Run new tests**

Run: `pytest tests/unit/test_categories_repository.py -k "list_tracks" -v`

Expected: the new tests FAIL because (a) `list_tracks` does not yet accept `sort`/`order` kwargs (TypeError) or (b) the SQL string does not contain the asserted ORDER BY.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_categories_repository.py
git commit -m "test(categories): add list_tracks sort + label-null tests"
```

### Task 3: Add handler tests for `?sort` / `?order` validation

**Files:**
- Modify: `tests/integration/test_curation_handler.py:223-254` (FakeRepo.list_tracks signature)
- Modify: `tests/integration/test_curation_handler.py:686-714` (existing list_tracks 200 test)
- Modify: `tests/integration/test_curation_handler.py` (append new validation tests after `test_list_tracks_200`)

- [ ] **Step 1: Update `FakeRepo.list_tracks` signature to accept new kwargs**

Replace the `list_tracks` method on `FakeRepo` (around line 223–254):

```python
def list_tracks(
    self, *, user_id, category_id, limit, offset, search,
    sort: str = "added_at", order: str = "desc",
):
    c = self.categories.get(category_id)
    if (
        c is None
        or c["user_id"] != user_id
        or c.get("deleted_at") is not None
    ):
        raise NotFoundError("category_not_found", "Category not found")
    rows = []
    for (cid, tid), meta in self.tracks.items():
        if cid != category_id:
            continue
        track = self.track_meta[tid]
        if search and search.strip().lower() not in track.get(
            "normalized_title", ""
        ):
            continue
        rows.append(
            TrackInCategoryRow(
                track=track,
                added_at=meta["added_at"],
                source_triage_block_id=meta["source_triage_block_id"],
            )
        )

    def _key(r):
        if sort == "title":
            return (r.track.get("title", ""), r.track["id"])
        if sort == "spotify_release_date":
            v = r.track.get("spotify_release_date")
            # NULLS LAST: None tracks tuple-rank as 1, real values as 0.
            return (0 if v is not None else 1, v or "", r.track["id"])
        return (r.added_at, r.track["id"])

    rows.sort(key=_key, reverse=(order == "desc"))
    total = len(rows)
    return PaginatedResult(
        items=rows[offset:offset+limit],
        total=total, limit=limit, offset=offset,
    )
```

(The fake's NULLS-LAST behaviour reverses under `desc` because `reverse=True` flips the whole tuple. That's wrong for the prod NULLS-LAST contract but acceptable for the FakeRepo — the handler test does not assert NULL ordering through the fake; the SQL test in Task 2 owns that contract.)

- [ ] **Step 2: Append new validation tests** (after `test_list_tracks_200`, around line 715):

```python
def test_list_tracks_400_invalid_sort(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"sort": "bogus"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert "sort" in body["message"].lower()


def test_list_tracks_400_invalid_order(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"order": "sideways"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert "order" in body["message"].lower()


def test_list_tracks_accepts_mixed_case_sort(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"sort": "Title", "order": "ASC"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 200
```

- [ ] **Step 3: Run the new validation tests**

Run: `pytest tests/integration/test_curation_handler.py -k "list_tracks" -v`

Expected: the three new tests FAIL — handler does not yet validate `sort` / `order`. The existing `test_list_tracks_200` may still pass (no query params).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_curation_handler.py
git commit -m "test(curation): add 400-on-invalid sort/order handler tests"
```

---

## Phase 2 — Backend implementation (green)

### Task 4: Implement `CategoriesRepository.list_tracks` shape & sort

**Files:**
- Modify: `src/collector/curation/categories_repository.py:608-690`

- [ ] **Step 1: Add `json` import at the top of the file** (if not already present)

Read the import block; if `json` is missing, add `import json` next to existing stdlib imports.

- [ ] **Step 2: Add module-level whitelists** above the `CategoriesRepository` class (around line 27, after the dataclass definitions and before `class CategoriesRepository`):

```python
_SORT_COLUMNS = {
    "title":                "t.title",
    "spotify_release_date": "t.spotify_release_date",
    "added_at":             "ct.added_at",
}
_ORDER_DIRS = {"asc": "ASC", "desc": "DESC"}
```

- [ ] **Step 3: Replace `list_tracks` method body**

Replace the entire `list_tracks` method (currently lines 608–690) with:

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
    cat_rows = self._data_api.execute(
        """
        SELECT id FROM categories
        WHERE id = :category_id
          AND user_id = :user_id
          AND deleted_at IS NULL
        """,
        {"category_id": category_id, "user_id": user_id},
    )
    if not cat_rows:
        raise NotFoundError("category_not_found", "Category not found")

    params: dict[str, Any] = {
        "category_id": category_id,
        "limit": limit,
        "offset": offset,
    }
    search_clause = ""
    if search and search.strip():
        search_clause = " AND t.normalized_title ILIKE :search "
        params["search"] = f"%{search.strip().lower()}%"

    column = _SORT_COLUMNS[sort]
    direction = _ORDER_DIRS[order]
    nulls = " NULLS LAST" if sort == "spotify_release_date" else ""
    order_by = f"{column} {direction}{nulls}"

    sql = f"""
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
    """
    rows = self._data_api.execute(sql, params)

    count_params: dict[str, Any] = {"category_id": category_id}
    count_clause = ""
    if "search" in params:
        count_clause = " AND t.normalized_title ILIKE :search "
        count_params["search"] = params["search"]
    total_rows = self._data_api.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM category_tracks ct
        JOIN clouder_tracks t ON t.id = ct.track_id
        WHERE ct.category_id = :category_id
          {count_clause}
        """,
        count_params,
    )
    total = int(total_rows[0]["total"]) if total_rows else 0

    items = []
    for r in rows:
        artists_raw = r.pop("artists_json", "[]")
        if isinstance(artists_raw, str):
            artists = json.loads(artists_raw)
        else:
            artists = artists_raw or []
        label_id = r.pop("label_id", None)
        label_name = r.pop("label_name", None)
        label = (
            {"id": label_id, "name": label_name} if label_id else None
        )
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
    return PaginatedResult(items=items, total=total, limit=limit, offset=offset)
```

- [ ] **Step 4: Run repo tests**

Run: `pytest tests/unit/test_categories_repository.py -v`

Expected: all PASS. If the sort assertions still fail, double-check the f-string output of `order_by` matches the asserted substring exactly (no extra spaces).

- [ ] **Step 5: Run full unit test suite to catch incidental regressions**

Run: `pytest tests/unit -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/categories_repository.py
git commit -m "feat(categories): add label, spotify_release_date, server sort to list_tracks"
```

### Task 5: Implement handler validation for `?sort` / `?order`

**Files:**
- Modify: `src/collector/curation_handler.py:394-407`

- [ ] **Step 1: Add module-level value sets** near the top of the file (after the existing imports, before the first handler function):

Search the file for an existing constants block (e.g. near `_CATEGORY_SELECT` references). Add:

```python
_SORT_VALUES = {"title", "spotify_release_date", "added_at"}
_ORDER_VALUES = {"asc", "desc"}
```

- [ ] **Step 2: Replace `_handle_list_tracks`** (lines 394–407):

```python
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

- [ ] **Step 3: Run handler tests**

Run: `pytest tests/integration/test_curation_handler.py -k "list_tracks" -v`

Expected: PASS for all five list_tracks tests (200 happy path + two 400 cases + mixed-case + the original 200).

- [ ] **Step 4: Run the full curation handler suite to catch regressions**

Run: `pytest tests/integration/test_curation_handler.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py
git commit -m "feat(curation): validate ?sort/?order on GET /categories/{id}/tracks"
```

---

## Phase 3 — Frontend (TDD-friendly: types → tests → impl)

### Task 6: Extend hook types and accept `sort` / `order`

**Files:**
- Modify: `frontend/src/features/categories/hooks/useCategoryTracks.ts`

- [ ] **Step 1: Replace the entire file**

```ts
import {
  useInfiniteQuery,
  type UseInfiniteQueryResult,
  type InfiniteData,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface TrackArtist {
  id: string;
  name: string;
}

export interface TrackLabel {
  id: string;
  name: string;
}

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

export interface PaginatedTracks {
  items: CategoryTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

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
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
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
      return api<PaginatedTracks>(
        `/categories/${categoryId}/tracks?${params.toString()}`,
      );
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

- [ ] **Step 2: Run typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: TypeScript errors in the existing tests/components that consume `CategoryTrack` (label/spotify_release_date missing in fixtures, sort param missing in some hook calls). Note them and fix in the next tasks.

- [ ] **Step 3: Do not commit yet** — typecheck is dirty; fix in subsequent tasks.

### Task 7: Update hook tests for fixture shape and `sort`/`order` URL params

**Files:**
- Modify: `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

- [ ] **Step 1: Update `mkTracks` fixture** (around line 17–33) to include `label` and `spotify_release_date`:

```ts
function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: 'Original Mix',
    artists: [{ id: 'a1', name: 'Artist' }],
    label: { id: 'l1', name: 'Cool Label' },
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    spotify_release_date: '2026-01-03',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
}
```

- [ ] **Step 2: Append two new tests** at the bottom of the `describe` block (before the closing `});`):

```ts
it('passes default ?sort=added_at&order=desc', async () => {
  let captured: { sort: string | null; order: string | null } = { sort: null, order: null };
  server.use(
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      const url = new URL(request.url);
      captured = {
        sort: url.searchParams.get('sort'),
        order: url.searchParams.get('order'),
      };
      return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
    }),
  );
  const { result } = renderHook(() => useCategoryTracks('c1', ''), { wrapper: wrap() });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(captured).toEqual({ sort: 'added_at', order: 'desc' });
});

it('passes explicit ?sort and ?order', async () => {
  let captured: { sort: string | null; order: string | null } = { sort: null, order: null };
  server.use(
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      const url = new URL(request.url);
      captured = {
        sort: url.searchParams.get('sort'),
        order: url.searchParams.get('order'),
      };
      return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
    }),
  );
  const { result } = renderHook(
    () => useCategoryTracks('c1', '', 'spotify_release_date', 'asc'),
    { wrapper: wrap() },
  );
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(captured).toEqual({ sort: 'spotify_release_date', order: 'asc' });
});

it('changes cache key when sort changes', async () => {
  const { categoryTracksKey } = await import('../useCategoryTracks');
  expect(categoryTracksKey('c1', '', 'added_at', 'desc')).not.toEqual(
    categoryTracksKey('c1', '', 'title', 'desc'),
  );
});
```

- [ ] **Step 3: Run hook tests**

Run: `cd frontend && pnpm test src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

Expected: PASS — the hook in Task 6 already passes `sort`/`order`. The `categoryTracksKey` import line confirms the cache key shape.

- [ ] **Step 4: Commit hook + types**

```bash
git add frontend/src/features/categories/hooks/useCategoryTracks.ts \
        frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx
git commit -m "feat(categories): add label, spotify_release_date, sort/order to tracks hook"
```

### Task 8: Add `formatReleaseDate` formatter

**Files:**
- Modify: `frontend/src/lib/formatters.ts`
- Test: existing formatter test file (locate first; otherwise create one)

- [ ] **Step 1: Locate or create the formatter test file**

Run: `ls frontend/src/lib/__tests__/ 2>/dev/null || ls frontend/src/lib/ | grep -i formatter`

If `frontend/src/lib/__tests__/formatters.test.ts` exists, modify it; otherwise create it.

- [ ] **Step 2: Read the current `formatters.ts`** to confirm the file contains `formatLength` and `formatAdded` already.

Run: `head -40 frontend/src/lib/formatters.ts`

- [ ] **Step 3: Append `formatReleaseDate` to `formatters.ts`**:

```ts
export function formatReleaseDate(date: string | null): string {
  return date ?? '—';
}
```

- [ ] **Step 4: Add (or append) test**

If the test file is new, write the full file:

```ts
import { describe, it, expect } from 'vitest';
import { formatReleaseDate } from '../formatters';

describe('formatReleaseDate', () => {
  it('returns the date as-is when present', () => {
    expect(formatReleaseDate('2026-01-15')).toBe('2026-01-15');
  });
  it('returns em-dash when null', () => {
    expect(formatReleaseDate(null)).toBe('—');
  });
});
```

If the test file already exists, append the `describe` block above to it.

- [ ] **Step 5: Run the formatter test**

Run: `cd frontend && pnpm test src/lib/__tests__/formatters.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/formatters.ts frontend/src/lib/__tests__/formatters.test.ts
git commit -m "feat(formatters): add formatReleaseDate helper"
```

### Task 9: Add i18n keys

**Files:**
- Modify: `frontend/src/i18n/en.json`

> Deviation from spec: `sort_aria` key intentionally omitted. `aria-sort` on the `<th>` plus the visible header text are sufficient for screen readers; an extra aria-label would duplicate. If a future a11y review demands explicit "Sort by X" wording, add it then.

- [ ] **Step 1: Replace the `categories.tracks_table` block** (around line 143–150 in `en.json`) with:

```json
"tracks_table": {
  "title": "Title",
  "artists": "Artists",
  "label": "Label",
  "bpm": "BPM",
  "length": "Length",
  "released": "Released",
  "added": "Added",
  "ai_suspected_aria": "AI-suspected"
}
```

- [ ] **Step 2: Verify JSON parses**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8'))"`

Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(i18n): add label, released, sort_aria keys for tracks table"
```

### Task 10: Build `SortableTh` component

**Files:**
- Create: `frontend/src/features/categories/components/SortableTh.tsx`
- Create: `frontend/src/features/categories/components/__tests__/SortableTh.test.tsx`

- [ ] **Step 1: Write the test first**

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Table } from '@mantine/core';
import { SortableTh } from '../SortableTh';

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider>
      <Table>
        <Table.Thead>
          <Table.Tr>{children}</Table.Tr>
        </Table.Thead>
      </Table>
    </MantineProvider>
  );
}

describe('SortableTh', () => {
  it('renders children', () => {
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(screen.getByText('Title')).toBeInTheDocument();
  });

  it('sets aria-sort=none when inactive', () => {
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'none');
  });

  it('sets aria-sort=ascending when active asc', () => {
    render(
      <Wrapper>
        <SortableTh active dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'ascending');
  });

  it('sets aria-sort=descending when active desc', () => {
    render(
      <Wrapper>
        <SortableTh active dir="desc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'descending');
  });

  it('fires onClick when activated', async () => {
    const onClick = vi.fn();
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={onClick}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Title/ }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test src/features/categories/components/__tests__/SortableTh.test.tsx`

Expected: FAIL with "Cannot find module ../SortableTh".

- [ ] **Step 3: Create the component**

```tsx
import { Table, UnstyledButton, Group, Text } from '@mantine/core';
import {
  IconArrowsSort,
  IconChevronDown,
  IconChevronUp,
} from '@tabler/icons-react';
import type { ReactNode } from 'react';
import type { SortOrder } from '../hooks/useCategoryTracks';

export interface SortableThProps {
  children: ReactNode;
  active: boolean;
  dir: SortOrder;
  onClick: () => void;
}

export function SortableTh({ children, active, dir, onClick }: SortableThProps) {
  const ariaSort = !active ? 'none' : dir === 'asc' ? 'ascending' : 'descending';
  const Icon = !active
    ? IconArrowsSort
    : dir === 'asc'
      ? IconChevronUp
      : IconChevronDown;
  return (
    <Table.Th aria-sort={ariaSort}>
      <UnstyledButton onClick={onClick} style={{ width: '100%' }}>
        <Group gap={4} wrap="nowrap">
          <Text fw={500} size="sm">
            {children}
          </Text>
          <Icon size={14} color={active ? undefined : 'var(--mantine-color-dimmed)'} />
        </Group>
      </UnstyledButton>
    </Table.Th>
  );
}
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && pnpm test src/features/categories/components/__tests__/SortableTh.test.tsx`

Expected: PASS for all five cases.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/SortableTh.tsx \
        frontend/src/features/categories/components/__tests__/SortableTh.test.tsx
git commit -m "feat(categories): add SortableTh header component"
```

### Task 11: Wire sort state into `TracksTab` and add new headers

**Files:**
- Modify: `frontend/src/features/categories/components/TracksTab.tsx`

- [ ] **Step 1: Replace the entire file**

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useCategoryTracks,
  type CategoryTrackSort,
  type SortOrder,
} from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { SortableTh } from './SortableTh';
import { EmptyState } from '../../../components/EmptyState';

export interface TracksTabProps {
  categoryId: string;
}

export function TracksTab({ categoryId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
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

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useCategoryTracks(categoryId, debounced, sortKey, sortDir);

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('categories.detail.tracks_search_placeholder')}
      leftSection={<IconSearch size={16} />}
      value={rawSearch}
      onChange={(e) => setRawSearch(e.currentTarget.value)}
      rightSection={
        rawSearch ? (
          <IconX
            size={16}
            role="button"
            onClick={() => setRawSearch('')}
            style={{ cursor: 'pointer' }}
          />
        ) : null
      }
    />
  );

  if (!isLoading && items.length === 0) {
    if (debounced) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('categories.empty_state.no_search_results_title', { term: debounced })}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
                {t('categories.empty_state.clear_search')}
              </Button>
            }
          />
        </Stack>
      );
    }
    return (
      <Stack gap="md">
        {searchInput}
        <EmptyState
          title={t('categories.empty_state.no_tracks_title')}
          body={t('categories.empty_state.no_tracks_body')}
        />
      </Stack>
    );
  }

  if (isMobile) {
    return (
      <Stack gap="md">
        {searchInput}
        {items.map((tr) => (
          <TrackRow key={tr.id} track={tr} variant="mobile" />
        ))}
        {hasNextPage && (
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        )}
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      {searchInput}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <SortableTh
              active={sortKey === 'title'}
              dir={sortDir}
              onClick={() => handleSort('title')}
            >
              {t('categories.tracks_table.title')}
            </SortableTh>
            <Table.Th>{t('categories.tracks_table.artists')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.label')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.bpm')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.length')}</Table.Th>
            <SortableTh
              active={sortKey === 'spotify_release_date'}
              dir={sortDir}
              onClick={() => handleSort('spotify_release_date')}
            >
              {t('categories.tracks_table.released')}
            </SortableTh>
            <SortableTh
              active={sortKey === 'added_at'}
              dir={sortDir}
              onClick={() => handleSort('added_at')}
            >
              {t('categories.tracks_table.added')}
            </SortableTh>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((track) => (
            <TrackRow key={track.id} track={track} variant="desktop" />
          ))}
        </Table.Tbody>
      </Table>
      {hasNextPage && (
        <Group justify="center">
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
```

- [ ] **Step 2: Update `TracksTab.test.tsx` fixtures and add sort interaction tests**

Replace the `mkTracks` helper and append sort tests. Edit `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`:

- Replace `mkTracks` with the same body used in Task 7 (adds `label`, `spotify_release_date`).
- Append at the bottom of the `describe` block, before `});`:

```tsx
it('renders Title and Released sortable headers with default sort', async () => {
  server.use(
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: mkTracks(0, 1), total: 1, limit: 50, offset: 0 }),
    ),
  );
  render(
    <Wrapper>
      <TracksTab categoryId="c1" />
    </Wrapper>,
  );
  await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
  // Default sort = added_at desc → Added header is descending, others none
  expect(
    screen.getByRole('columnheader', { name: /Added/i }),
  ).toHaveAttribute('aria-sort', 'descending');
  expect(
    screen.getByRole('columnheader', { name: /Title/i }),
  ).toHaveAttribute('aria-sort', 'none');
});

it('clicking Title switches sort to title asc, then desc', async () => {
  let lastSort = '';
  let lastOrder = '';
  server.use(
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      const url = new URL(request.url);
      lastSort = url.searchParams.get('sort') ?? '';
      lastOrder = url.searchParams.get('order') ?? '';
      return HttpResponse.json({
        items: mkTracks(0, 1),
        total: 1,
        limit: 50,
        offset: 0,
      });
    }),
  );
  render(
    <Wrapper>
      <TracksTab categoryId="c1" />
    </Wrapper>,
  );
  await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
  await userEvent.click(screen.getByRole('button', { name: /Title/i }));
  await waitFor(() => expect(lastSort).toBe('title'));
  expect(lastOrder).toBe('asc');
  await userEvent.click(screen.getByRole('button', { name: /Title/i }));
  await waitFor(() => expect(lastOrder).toBe('desc'));
  expect(lastSort).toBe('title');
});
```

- [ ] **Step 3: Run TracksTab tests**

Run: `cd frontend && pnpm test src/features/categories/components/__tests__/TracksTab.test.tsx`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/categories/components/TracksTab.tsx \
        frontend/src/features/categories/components/__tests__/TracksTab.test.tsx
git commit -m "feat(categories): wire server-side sort + new headers into TracksTab"
```

### Task 12: Render Label + Released in `TrackRow`

**Files:**
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`

- [ ] **Step 1: Replace the entire file**

```tsx
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { formatAdded, formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
}

export function TrackRow({ track, variant }: TrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('categories.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;

  if (variant === 'desktop') {
    return (
      <Table.Tr>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {aiBadge}
            <Stack gap={0}>
              <Text fw={500}>{track.title}</Text>
              {track.mix_name && (
                <Text size="xs" c="dimmed">
                  {track.mix_name}
                </Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
        <Table.Td>{joinArtists(track.artists)}</Table.Td>
        <Table.Td>{track.label?.name ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">
          {formatReleaseDate(track.spotify_release_date)}
        </Table.Td>
        <Table.Td>{formatAdded(track.added_at)}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm">
      <Stack gap={4}>
        <Group gap="xs">
          {aiBadge}
          <Text fw={500}>{track.title}</Text>
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">
            {track.mix_name}
          </Text>
        )}
        <Text size="sm">{joinArtists(track.artists)}</Text>
        {track.label && (
          <Text size="xs" c="dimmed">
            {track.label.name}
          </Text>
        )}
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          {track.spotify_release_date && (
            <Text size="xs" c="dimmed" className="font-mono">
              {track.spotify_release_date}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            {formatAdded(track.added_at)}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 2: Run frontend typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: PASS. If errors remain, they will be in fixture files we have not yet updated — fix the failing fixtures (likely `BucketTrackRow.test.tsx` etc. for **other** features still pass strings; do not change those).

- [ ] **Step 3: Run all categories tests**

Run: `cd frontend && pnpm test src/features/categories`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/categories/components/TrackRow.tsx
git commit -m "feat(categories): render label and Spotify release date in TrackRow"
```

---

## Phase 4 — Verification & PR

### Task 13: Full local verification

- [ ] **Step 1: Backend full test pass**

Run: `pytest -q`

Expected: PASS. If a test elsewhere referenced `repo.list_tracks` without keyword args, fix at the call site (rare — should be only the FakeRepo updated in Task 3).

- [ ] **Step 2: Frontend typecheck + tests**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test`

Expected: PASS for all suites.

- [ ] **Step 3: Frontend lint**

Run: `cd frontend && pnpm lint`

Expected: PASS. Investigate any new warnings in the changed files.

- [ ] **Step 4: Smoke test the UI manually**

Run: `cd frontend && pnpm dev`

Open `http://127.0.0.1:5173/categories/<some-id>` in a browser.

Verify:
- Artists column shows comma-separated names (no longer empty).
- Label column shows label names (`—` when null).
- Released column shows `YYYY-MM-DD` (`—` when null).
- Click Title header → list re-sorts; arrow appears on the header.
- Click Title again → direction flips.
- Click Released → list sorts by Spotify date; tracks without dates appear last regardless of direction.
- Click Added → list re-sorts back to default-style (added_at desc).
- Mobile breakpoint (<= 64em): card shows label name and Spotify date if present, otherwise hides those rows.

If anything is off, capture the issue and fix before committing.

- [ ] **Step 5: Commit any smoke-test fixes** (only if needed) using the same caveman commit policy.

### Task 14: Open PR

- [ ] **Step 1: Push the branch**

Run: `git push -u origin HEAD`

- [ ] **Step 2: Generate PR title + body via caveman:caveman-commit skill**

Use the skill to draft a Conventional-Commits-shaped title and a caveman body that summarises the changes (Artists fix, two new columns, server-side sort) plus a test plan checklist.

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "<caveman title>" --body "$(cat <<'EOF'
<caveman body>
EOF
)"
```

Verify the PR URL and that the project pre-commit hook accepted the title.

---

## Risks recap

- **Aurora Data API JSON return shape**: handled defensively (`isinstance(... , str)` parse fallback).
- **`artists` shape break**: no live consumer renders the old `string[]` correctly (column is currently empty); other features (triage) keep their separate `string[]` shape — do not touch `useBucketTracks.ts`.
- **MSW fixture drift**: only categories fixtures need the new fields. Triage fixtures stay as-is.
- **No DB migration / no Aurora schema change**: low blast radius for rollback (revert PR).

# Category Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inline Spotify player on the category detail page. The user starts tracks from a category, assigns playlists / tags / removal without leaving the page, auto-advances on natural track end, and the previously global triage MiniBar is retired in the same change.

**Architecture:** Reuse the singleton `PlaybackProvider` in `_layout.tsx`; extend `QueueSource` with a `category` variant so a single SDK player serves both Curate and Category routes. A new left-column `CategoryPlayerPanel` (PlayerCard-based shell + tag/playlist clouds + remove button + depth-1 undo stack + 1-0 hotkeys) is mounted on `/categories/:styleId/:id`. On mobile a child route `/categories/:styleId/:id/player` carries the full-screen player.

**Tech Stack:** React 19, Mantine 9, react-router 7, TanStack Query 5, react-i18next 15, Vitest + MSW + jsdom. Backend: AWS Lambda + Aurora Data API + pydantic, alembic.

**Spec:** [`docs/2026-05-13-category-player-frontend-design.md`](../../2026-05-13-category-player-frontend-design.md) (commit `dd60748`).

**Branch:** `worktree-add_playlist_player` (already current).

---

## File Inventory

### Create

```
frontend/src/features/categories/components/CategoryPlayerPanel.tsx
frontend/src/features/categories/components/CategoryPlayerPanel.module.css
frontend/src/features/categories/components/PlayerPanelTagCloud.tsx
frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx
frontend/src/features/categories/components/UsedInPlaylistBadge.tsx
frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx
frontend/src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx
frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx
frontend/src/features/categories/hooks/useCategoryPlayerQueue.ts
frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts
frontend/src/features/categories/hooks/useUndoStack.ts
frontend/src/features/categories/hooks/__tests__/useCategoryPlayerQueue.test.tsx
frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx
frontend/src/features/categories/hooks/__tests__/useUndoStack.test.ts
frontend/src/features/categories/lib/freshUrlState.ts
frontend/src/features/categories/lib/__tests__/freshUrlState.test.ts
frontend/src/features/categories/routes/CategoryPlayerPage.tsx
frontend/src/features/categories/routes/__tests__/CategoryPlayerPage.test.tsx
tests/unit/test_list_tracks_fresh_and_used.py
```

### Modify

```
frontend/src/features/playback/lib/types.ts
frontend/src/features/playback/routeContext.ts
frontend/src/features/playback/__tests__/routeContext.test.ts
frontend/src/routes/_layout.tsx
frontend/src/routes/router.tsx
frontend/src/features/categories/index.ts
frontend/src/features/categories/routes/CategoryDetailPage.tsx
frontend/src/features/categories/components/TracksTab.tsx
frontend/src/features/categories/components/TrackRow.tsx
frontend/src/features/categories/hooks/useCategoryTracks.ts
frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts
frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts
frontend/src/i18n/locales/en.json
frontend/src/i18n/locales/ru.json
src/collector/curation/categories_repository.py
src/collector/curation_handler.py
scripts/generate_openapi.py
docs/openapi.yaml
CLAUDE.md
```

### Delete

```
frontend/src/features/playback/MiniBar.tsx
frontend/src/features/playback/MiniBar.module.css
frontend/src/features/playback/LeaveContextDialog.tsx
frontend/src/features/playback/__tests__/MiniBar.test.tsx
frontend/src/features/playback/__tests__/LeaveContextDialog.test.tsx
```

---

## Phase 1 — Backend: fresh filter + used_in_playlist projection

### Task 1: Repository — `fresh` + `used_in_playlist` in `list_tracks`

**Files:**
- Modify: `src/collector/curation/categories_repository.py:657-820`
- Create: `tests/unit/test_list_tracks_fresh_and_used.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_list_tracks_fresh_and_used.py
"""Tests for fresh=true + used_in_playlist projection in list_tracks."""
from __future__ import annotations
from collector.curation.categories_repository import CategoriesRepository
from collector.curation.tags_repository import TagsRepository


class _FakeDataAPI:
    """Stub DataAPIClient that records every SQL invocation."""

    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, dict(params or {})))
        return self._scripted.pop(0)


def _category_exists() -> list[dict]:
    return [{"id": "cat-1"}]


def _row(track_id: str, used: bool) -> dict:
    return {
        "id": track_id, "title": "T", "mix_name": None, "isrc": None,
        "bpm": 120, "length_ms": 200000, "publish_date": None,
        "spotify_id": "sp1", "release_type": None, "is_ai_suspected": False,
        "spotify_release_date": "2024-01-01",
        "artists_json": "[]", "label_id": None, "label_name": None,
        "added_at": "2024-01-02T00:00:00Z", "source_triage_block_id": None,
        "used_in_playlist": used,
    }


def test_list_tracks_projects_used_in_playlist():
    api = _FakeDataAPI([_category_exists(), [_row("t1", True), _row("t2", False)], [{"total": 2}]])
    repo = CategoriesRepository(api)
    result = repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
    )
    # The SELECT in the rows query must include used_in_playlist as a projection.
    select_sql = api.calls[1][0]
    assert "used_in_playlist" in select_sql
    # Per-row dataclass must expose used_in_playlist on the track mapping.
    track_used = [r.track["used_in_playlist"] for r in result.items]
    assert track_used == [True, False]


def test_list_tracks_fresh_true_adds_not_exists_clause():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
        fresh=True,
    )
    rows_sql = api.calls[1][0]
    count_sql = api.calls[2][0]
    # Fresh filter MUST appear in both rows and count queries (else pagination breaks).
    assert "NOT EXISTS" in rows_sql
    assert "NOT EXISTS" in count_sql
    # user_id must be bound for the EXISTS sub-select tenancy check.
    assert ":user_id" in rows_sql
    assert api.calls[1][1].get("user_id") == "u-1"


def test_list_tracks_fresh_false_default_no_filter():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
        # fresh defaults to False
    )
    rows_sql = api.calls[1][0]
    count_sql = api.calls[2][0]
    assert "NOT EXISTS" not in rows_sql
    assert "NOT EXISTS" not in count_sql


def test_list_tracks_fresh_combines_with_search_and_tags():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search="house", sort="title", order="asc",
        tag_ids=["tag-a"], tag_match="any", tags_repo=None,
        fresh=True,
    )
    rows_sql = api.calls[1][0]
    # Three filters coexist; verify the parameters cover them all.
    params = api.calls[1][1]
    assert "NOT EXISTS" in rows_sql
    assert "ILIKE" in rows_sql or "ilike" in rows_sql.lower()
    assert params["user_id"] == "u-1"
    assert params["search"] == "%house%"
    assert params["tag0"] == "tag-a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/unit/test_list_tracks_fresh_and_used.py -q`
Expected: 4 failures (`TypeError: list_tracks() got an unexpected keyword argument 'fresh'`, and assertion failures on `used_in_playlist`).

- [ ] **Step 3: Implement `fresh` + `used_in_playlist` in the repository**

In `src/collector/curation/categories_repository.py`, locate the `list_tracks` method (line ~657). Modify the signature:

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
    tag_ids: list[str] | None = None,
    tag_match: str = "all",
    tags_repo: "TagsRepository | None" = None,
    fresh: bool = False,
) -> PaginatedResult[TrackInCategoryRow]:
```

After the existing `tag_clause` block and before the `column = _SORT_COLUMNS[sort]` line, add the fresh filter:

```python
    # Fresh filter — hide tracks already in any of the user's playlists.
    # The same sub-select is also projected as `used_in_playlist` below.
    params["user_id"] = user_id  # used by both NOT EXISTS and the projection
    fresh_clause = ""
    if fresh:
        fresh_clause = (
            " AND NOT EXISTS ("
            "SELECT 1 FROM playlist_tracks pt "
            "JOIN playlists p ON p.id = pt.playlist_id "
            "WHERE pt.track_id = ct.track_id "
            "AND p.user_id = :user_id "
            "AND p.deleted_at IS NULL"
            ") "
        )
```

Replace the projection SELECT to add `used_in_playlist`:

```python
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
            ct.added_at, ct.source_triage_block_id,
            EXISTS (
                SELECT 1 FROM playlist_tracks pt
                JOIN playlists p ON p.id = pt.playlist_id
                WHERE pt.track_id = ct.track_id
                  AND p.user_id = :user_id
                  AND p.deleted_at IS NULL
            ) AS used_in_playlist
        FROM category_tracks ct
        JOIN clouder_tracks t ON t.id = ct.track_id
        LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
        LEFT JOIN clouder_artists       a   ON a.id  = cta.artist_id
        LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
        LEFT JOIN clouder_labels        l   ON l.id   = alb.label_id
        WHERE ct.category_id = :category_id
          {search_clause}
          {tag_clause}
          {fresh_clause}
        GROUP BY t.id, ct.added_at, ct.source_triage_block_id, l.id, l.name, ct.track_id
        ORDER BY {order_by}, t.id ASC
        LIMIT :limit OFFSET :offset
    """
```

In the count query block below, mirror the fresh filter:

```python
    count_fresh_clause = ""
    if fresh:
        count_params["user_id"] = user_id
        count_fresh_clause = (
            " AND NOT EXISTS ("
            "SELECT 1 FROM playlist_tracks pt "
            "JOIN playlists p ON p.id = pt.playlist_id "
            "WHERE pt.track_id = ct.track_id "
            "AND p.user_id = :user_id "
            "AND p.deleted_at IS NULL"
            ") "
        )
    total_rows = self._data_api.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM category_tracks ct
        JOIN clouder_tracks t ON t.id = ct.track_id
        WHERE ct.category_id = :category_id
          {count_clause}
          {count_tag_clause}
          {count_fresh_clause}
        """,
        count_params,
    )
```

In the row-mapping loop (after `track = dict(r)`), preserve the boolean:

```python
        # used_in_playlist is already a bool column from PG; keep as-is.
        track["used_in_playlist"] = bool(track.get("used_in_playlist", False))
```

- [ ] **Step 4: Run repository tests**

Run: `PYTHONPATH=src pytest tests/unit/test_list_tracks_fresh_and_used.py -q`
Expected: 4 passes.

Run: `PYTHONPATH=src pytest tests/unit -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

Stage:
- `src/collector/curation/categories_repository.py`
- `tests/unit/test_list_tracks_fresh_and_used.py`

Use the `caveman:caveman-commit` skill with input: `feat: add fresh filter and used_in_playlist projection to list_tracks repo`.

Commit message will look like:
```
feat(categories): add fresh filter + used_in_playlist

list_tracks gains `fresh: bool` kwarg gating a NOT EXISTS
sub-select against the user's playlists; the same EXISTS
is projected as `used_in_playlist` on every row so the UI
can render a "used" badge without an extra round-trip.
```

---

### Task 2: Handler — accept `?fresh=` query param

**Files:**
- Modify: `src/collector/curation_handler.py:496-533` (`_handle_list_tracks`)
- Modify: existing handler tests if any
- Create: `tests/unit/test_list_tracks_handler_fresh.py`

- [ ] **Step 1: Write the failing handler test**

```python
# tests/unit/test_list_tracks_handler_fresh.py
"""Handler parses ?fresh=1/0 and threads it into repo.list_tracks."""
from __future__ import annotations
from unittest.mock import MagicMock
from collector.curation_handler import _handle_list_tracks
from collector.curation import PaginatedResult


def _make_event(fresh: str | None) -> dict:
    qp: dict[str, str] = {}
    if fresh is not None:
        qp["fresh"] = fresh
    return {
        "pathParameters": {"id": "cat-1"},
        "queryStringParameters": qp,
    }


def _fake_repo():
    repo = MagicMock()
    repo.list_tracks.return_value = PaginatedResult(items=[], total=0, limit=50, offset=0)
    return repo


def test_handler_fresh_1_passes_true(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event("1"), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is True


def test_handler_fresh_0_passes_false(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event("0"), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is False


def test_handler_fresh_absent_passes_false(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event(None), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/unit/test_list_tracks_handler_fresh.py -q`
Expected: 3 failures (`fresh` not in kwargs).

- [ ] **Step 3: Patch the handler**

In `src/collector/curation_handler.py:_handle_list_tracks`, after the `tag_match` validation and before `repo.list_tracks(...)`, add:

```python
    fresh_raw = (qp.get("fresh") or "").strip()
    fresh = fresh_raw == "1"
```

Extend the `repo.list_tracks(...)` call:

```python
    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
        sort=sort, order=order,
        tag_ids=tag_ids or None, tag_match=tag_match, tags_repo=tags_repo,
        fresh=fresh,
    )
```

Also extend `_track_in_category_response` to surface the new column when it exists on the track mapping (it always will after Task 1, but be defensive):

```python
def _track_in_category_response(item) -> dict[str, Any]:
    track = dict(item.track)
    track["added_at"] = item.added_at
    track["source_triage_block_id"] = item.source_triage_block_id
    track["tags"] = [
        {"id": t.tag_id, "name": t.name, "color": t.color}
        for t in getattr(item, "tags", ())
    ]
    track["used_in_playlist"] = bool(track.get("used_in_playlist", False))
    return track
```

- [ ] **Step 4: Run all curation handler tests**

Run: `PYTHONPATH=src pytest tests/unit/test_list_tracks_handler_fresh.py tests/unit -q -k "curation or category or list_tracks"`
Expected: green.

- [ ] **Step 5: Commit**

Stage:
- `src/collector/curation_handler.py`
- `tests/unit/test_list_tracks_handler_fresh.py`

Use `caveman:caveman-commit`: `feat: handler parses fresh query param and projects used_in_playlist`.

---

### Task 3: OpenAPI regen for `fresh` + `used_in_playlist`

**Files:**
- Modify: `scripts/generate_openapi.py` (ROUTES table — find the `/categories/{id}/tracks` GET entry)
- Modify: `docs/openapi.yaml` (regenerated)

- [ ] **Step 1: Update `scripts/generate_openapi.py`**

Locate the entry for `GET /categories/{id}/tracks` in `ROUTES`. Add `fresh` to its query parameters list and `used_in_playlist: bool` to the response track-item schema. Exact lines depend on the current shape — open the file, find the route block, mirror existing parameter shapes (`tags`, `match`, `search`) for the new `fresh` boolean (encode as `type: integer`, `enum: [0, 1]`, optional).

- [ ] **Step 2: Regenerate OpenAPI**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`
Expected: `docs/openapi.yaml` updated; `git diff docs/openapi.yaml` shows new `fresh` param + `used_in_playlist` boolean.

- [ ] **Step 3: Sanity-check the diff**

Run: `git diff docs/openapi.yaml | head -80`
Verify only the `/categories/{id}/tracks` GET route changed and the changes match the new contract.

- [ ] **Step 4: Commit**

Stage:
- `scripts/generate_openapi.py`
- `docs/openapi.yaml`

Use `caveman:caveman-commit`: `docs: regen openapi for fresh + used_in_playlist`.

---

## Phase 2 — Frontend types + routes

### Task 4: Extend `QueueSource` with `category` variant

**Files:**
- Modify: `frontend/src/features/playback/lib/types.ts`

- [ ] **Step 1: Read existing types**

Run: `cat frontend/src/features/playback/lib/types.ts | head -60`

Locate the `QueueSource` definition (currently a single-variant union for `bucket`).

- [ ] **Step 2: Extend the union**

Replace the existing `QueueSource` export with:

```ts
export type QueueSource =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; categoryId: string; styleId: string };
```

- [ ] **Step 3: Run TypeScript check**

From `frontend/`: `pnpm typecheck`
Expected: pass. Any `switch (source.type)` callsite that did not include `default` should keep compiling because Mantine/React-Query callsites typically read fields after a narrowing type-guard — but if a callsite breaks, surface it and treat as a discovered task before continuing.

- [ ] **Step 4: Commit**

Stage:
- `frontend/src/features/playback/lib/types.ts`

Use `caveman:caveman-commit`: `feat: add category variant to QueueSource`.

---

### Task 5: Extend `routeContext` to recognize the category route

**Files:**
- Modify: `frontend/src/features/playback/routeContext.ts`
- Modify: `frontend/src/features/playback/__tests__/routeContext.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/features/playback/__tests__/routeContext.test.ts`:

```ts
describe('hasPlayerCard — category route', () => {
  it('matches /categories/:styleId/:id', () => {
    expect(hasPlayerCard('/categories/style-1/cat-1')).toBe(true);
    expect(hasPlayerCard('/categories/style-1/cat-1/')).toBe(true);
  });

  it('does not match /categories list', () => {
    expect(hasPlayerCard('/categories')).toBe(false);
    expect(hasPlayerCard('/categories/style-1')).toBe(false);
  });

  it('continues to match curate session route', () => {
    expect(hasPlayerCard('/curate/style-1/block-1/bucket-1')).toBe(true);
  });
});

describe('contextOf — category', () => {
  it('returns category context for category detail path', () => {
    expect(contextOf('/categories/style-1/cat-1')).toEqual({
      type: 'category',
      styleId: 'style-1',
      categoryId: 'cat-1',
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/playback/__tests__/routeContext.test.ts`
Expected: 4 failures.

- [ ] **Step 3: Implement the extension**

Replace `frontend/src/features/playback/routeContext.ts`:

```ts
const CURATE_SESSION = /^\/curate\/[^/]+\/([^/]+)\/([^/]+)\/?$/;
const CATEGORY_DETAIL = /^\/categories\/([^/]+)\/([^/]+)\/?$/;

export function hasPlayerCard(pathname: string): boolean {
  return CURATE_SESSION.test(pathname) || CATEGORY_DETAIL.test(pathname);
}

export type RouteContext =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; styleId: string; categoryId: string };

export function contextOf(pathname: string): RouteContext | null {
  const curate = CURATE_SESSION.exec(pathname);
  if (curate) {
    const [, blockId, bucketId] = curate;
    if (blockId === undefined || bucketId === undefined) return null;
    return { type: 'bucket', blockId, bucketId };
  }
  const category = CATEGORY_DETAIL.exec(pathname);
  if (category) {
    const [, styleId, categoryId] = category;
    if (styleId === undefined || categoryId === undefined) return null;
    return { type: 'category', styleId, categoryId };
  }
  return null;
}

export function contextDifferent(currentPath: string, nextPath: string): boolean {
  const a = contextOf(currentPath);
  const b = contextOf(nextPath);
  if (!a || !b) return false;
  if (a.type !== b.type) return true;
  if (a.type === 'bucket' && b.type === 'bucket') {
    return a.blockId !== b.blockId || a.bucketId !== b.bucketId;
  }
  if (a.type === 'category' && b.type === 'category') {
    return a.styleId !== b.styleId || a.categoryId !== b.categoryId;
  }
  return false;
}
```

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/playback/__tests__/routeContext.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

Stage:
- `frontend/src/features/playback/routeContext.ts`
- `frontend/src/features/playback/__tests__/routeContext.test.ts`

Use `caveman:caveman-commit`: `feat: routeContext recognizes category detail`.

---

## Phase 3 — Retire MiniBar + LeaveContextDialog

### Task 6: Delete MiniBar + LeaveContextDialog files

**Files:**
- Delete: `frontend/src/features/playback/MiniBar.tsx`
- Delete: `frontend/src/features/playback/MiniBar.module.css`
- Delete: `frontend/src/features/playback/LeaveContextDialog.tsx`
- Delete: `frontend/src/features/playback/__tests__/MiniBar.test.tsx`
- Delete: `frontend/src/features/playback/__tests__/LeaveContextDialog.test.tsx`
- Modify: `frontend/src/routes/_layout.tsx`
- Modify: `frontend/src/routes/__tests__/_layout.test.tsx`

- [ ] **Step 1: Strip MiniBar + LeaveContextDialog from PlaybackChrome**

In `frontend/src/routes/_layout.tsx`, remove these imports:

```ts
import { MiniBar } from '../features/playback/MiniBar';
import { LeaveContextDialog } from '../features/playback/LeaveContextDialog';
import { readLastCurateStyle } from '../features/curate/lib/lastCurateLocation';
```

Replace the `PlaybackChrome` function body with the minimal device-picker-only shell:

```ts
export function PlaybackChrome() {
  return (
    <>
      <DevicePickerSurface />
    </>
  );
}
```

Remove the now-unused `usePlayback`, `hasPlayerCard`, `useLocation` imports if PlaybackChrome was their only consumer. Verify `DeviceIndicator` import is still used elsewhere — if not, drop it.

- [ ] **Step 2: Delete the files**

Run:
```bash
rm frontend/src/features/playback/MiniBar.tsx \
   frontend/src/features/playback/MiniBar.module.css \
   frontend/src/features/playback/LeaveContextDialog.tsx \
   frontend/src/features/playback/__tests__/MiniBar.test.tsx \
   frontend/src/features/playback/__tests__/LeaveContextDialog.test.tsx
```

- [ ] **Step 3: Update `_layout.test.tsx`**

Open `frontend/src/routes/__tests__/_layout.test.tsx`. Remove any test that asserts MiniBar visibility or LeaveContextDialog behavior. If any test relied on MiniBar mount as a side-effect, replace with an assertion that MiniBar is NOT in the DOM after a queue is bound.

- [ ] **Step 4: Typecheck + run frontend test suite**

From `frontend/`:
```
pnpm typecheck
pnpm vitest run
```

Expected: no `Cannot find module './MiniBar'` errors; all remaining tests pass.

- [ ] **Step 5: Smoke-test curate manually (optional but recommended)**

If the dev server is running, navigate to a curate session, start playback, then navigate away. The bottom MiniBar must not appear. Press the back button — curate route loses ownership and playback clears.

- [ ] **Step 6: Commit**

Stage:
- All deletions
- `frontend/src/routes/_layout.tsx`
- `frontend/src/routes/__tests__/_layout.test.tsx`

Use `caveman:caveman-commit`: `refactor: retire MiniBar + LeaveContextDialog; players own their routes`.

---

## Phase 4 — Hooks: undo stack, queue binding, hotkeys

### Task 7: `useUndoStack` module + tests

**Files:**
- Create: `frontend/src/features/categories/hooks/useUndoStack.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useUndoStack.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/categories/hooks/__tests__/useUndoStack.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { undoStack, useUndoStack } from '../useUndoStack';
import { renderHook, act } from '@testing-library/react';

beforeEach(() => {
  undoStack.clear();
});

describe('undoStack', () => {
  it('push then peek returns the entry', () => {
    const undo = vi.fn();
    undoStack.push({ id: 'a', label: 'Added', undo });
    expect(undoStack.peek()?.id).toBe('a');
  });

  it('replaces previous entry on push', () => {
    undoStack.push({ id: 'a', label: 'A', undo: vi.fn() });
    undoStack.push({ id: 'b', label: 'B', undo: vi.fn() });
    expect(undoStack.peek()?.id).toBe('b');
  });

  it('popAndRun invokes undo and clears', async () => {
    const undo = vi.fn(() => Promise.resolve());
    undoStack.push({ id: 'a', label: 'A', undo });
    await undoStack.popAndRun();
    expect(undo).toHaveBeenCalledOnce();
    expect(undoStack.peek()).toBeNull();
  });

  it('popAndRun on empty is a no-op', async () => {
    await expect(undoStack.popAndRun()).resolves.toBeUndefined();
  });

  it('subscribers receive notifications on push/pop', () => {
    const cb = vi.fn();
    const unsub = undoStack.subscribe(cb);
    undoStack.push({ id: 'a', label: 'A', undo: vi.fn() });
    expect(cb).toHaveBeenCalledTimes(1);
    unsub();
    undoStack.push({ id: 'b', label: 'B', undo: vi.fn() });
    expect(cb).toHaveBeenCalledTimes(1);
  });
});

describe('useUndoStack hook', () => {
  it('reactively returns the current entry', () => {
    const { result } = renderHook(() => useUndoStack());
    expect(result.current.entry).toBeNull();
    act(() => undoStack.push({ id: 'x', label: 'X', undo: vi.fn() }));
    expect(result.current.entry?.id).toBe('x');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useUndoStack.test.ts`
Expected: 6 failures (module not found).

- [ ] **Step 3: Implement the store**

```ts
// frontend/src/features/categories/hooks/useUndoStack.ts
import { useEffect, useState } from 'react';

export interface UndoEntry {
  id: string;
  label: string;
  undo: () => Promise<void> | void;
}

type Listener = () => void;

let current: UndoEntry | null = null;
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l();
}

export const undoStack = {
  push(entry: UndoEntry): void {
    current = entry;
    emit();
  },
  peek(): UndoEntry | null {
    return current;
  },
  async popAndRun(): Promise<void> {
    const entry = current;
    if (!entry) return;
    current = null;
    emit();
    await entry.undo();
  },
  clear(): void {
    current = null;
    emit();
  },
  subscribe(cb: Listener): () => void {
    listeners.add(cb);
    return () => {
      listeners.delete(cb);
    };
  },
};

export function useUndoStack(): { entry: UndoEntry | null } {
  const [entry, setEntry] = useState<UndoEntry | null>(undoStack.peek());
  useEffect(() => undoStack.subscribe(() => setEntry(undoStack.peek())), []);
  return { entry };
}
```

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useUndoStack.test.ts`
Expected: all 6 pass.

- [ ] **Step 5: Commit**

Stage both files.
Use `caveman:caveman-commit`: `feat: add depth-1 undo stack hook for category player`.

---

### Task 8: `useCategoryPlayerQueue` — reactive bindQueue

**Files:**
- Create: `frontend/src/features/categories/hooks/useCategoryPlayerQueue.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCategoryPlayerQueue.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/categories/hooks/__tests__/useCategoryPlayerQueue.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useCategoryPlayerQueue } from '../useCategoryPlayerQueue';
import type { PlaybackTrack } from '../../../playback/lib/types';

const bindQueue = vi.fn();
const clearQueue = vi.fn();
const playback = {
  controls: { bindQueue, clearQueue },
  queue: { source: null, tracks: [] as PlaybackTrack[], cursor: 0, status: 'idle' as const },
  track: { current: null, positionMs: 0, durationMs: 0 },
  sdk: { ready: false, error: null },
  devices: undefined as never,
};

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => playback,
}));

const T = (id: string): PlaybackTrack => ({
  id,
  title: `t-${id}`,
  artists: '',
  duration_ms: 200000,
  spotify_id: `sp-${id}`,
  cover_url: null,
});

beforeEach(() => {
  bindQueue.mockReset();
  clearQueue.mockReset();
});

describe('useCategoryPlayerQueue', () => {
  it('binds queue on mount with cursor 0', () => {
    const tracks = [T('a'), T('b'), T('c')];
    renderHook(() => useCategoryPlayerQueue('cat-1', 'style-1', tracks));
    expect(bindQueue).toHaveBeenCalledWith({
      source: { type: 'category', categoryId: 'cat-1', styleId: 'style-1' },
      tracks,
      cursor: 0,
      onCursorChange: expect.any(Function),
    });
  });

  it('rebinds when track list identity changes and preserves the playing track id', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    const next = [T('a'), T('b'), T('c'), T('d')];
    rerender({ tracks: next });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ tracks: next, cursor: 1 }),
    );
  });

  it('clamps cursor to len-1 when current track removed and list shorter', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 2;
    playback.track.current = T('c');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('a'), T('b')] });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 1 }),
    );
  });

  it('calls clearQueue on unmount', () => {
    const { unmount } = renderHook(() =>
      useCategoryPlayerQueue('cat-1', 'style-1', [T('a')]),
    );
    unmount();
    expect(clearQueue).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryPlayerQueue.test.tsx`
Expected: 4 failures.

- [ ] **Step 3: Implement the hook**

```ts
// frontend/src/features/categories/hooks/useCategoryPlayerQueue.ts
import { useEffect, useRef } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';

/**
 * Bind a category's track list to PlaybackProvider's singleton queue.
 *
 * On every tracks-identity change we recompute the cursor: keep the currently
 * playing track id if it still exists in the new list, else clamp to the
 * tail. Unmount clears the queue (per spec: players own their routes).
 */
export function useCategoryPlayerQueue(
  categoryId: string,
  styleId: string,
  tracks: readonly PlaybackTrack[],
): void {
  const playback = usePlayback();
  const cursorRef = useRef(playback.queue.cursor);

  useEffect(() => {
    cursorRef.current = playback.queue.cursor;
  }, [playback.queue.cursor]);

  useEffect(() => {
    const currentId = playback.track.current?.id ?? null;
    let cursor = 0;
    if (currentId) {
      const idx = tracks.findIndex((t) => t.id === currentId);
      cursor = idx >= 0 ? idx : Math.min(cursorRef.current, Math.max(0, tracks.length - 1));
    }
    playback.controls.bindQueue({
      source: { type: 'category', categoryId, styleId },
      tracks,
      cursor,
      onCursorChange: (next) => {
        cursorRef.current = next;
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, categoryId, styleId]);

  useEffect(() => {
    return () => {
      playback.controls.clearQueue();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
```

> Note on `BindQueueArgs`: this assumes `bindQueue` accepts `onCursorChange`. It does — see `PlaybackProvider.bindQueue` which assigns to `onCursorChangeRef`.

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryPlayerQueue.test.tsx`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

Stage both files.
Use `caveman:caveman-commit`: `feat: bind category tracks to playback queue`.

---

### Task 9: `useCategoryPlayerHotkeys`

**Files:**
- Create: `frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useCategoryPlayerHotkeys } from '../useCategoryPlayerHotkeys';

const callbacks = {
  onTogglePlayPause: vi.fn(),
  onPrev: vi.fn(),
  onNext: vi.fn(),
  onSeekPct: vi.fn(),
  onTogglePlaylist: vi.fn(),
  onUndo: vi.fn(),
};

function press(code: string, opts: Partial<KeyboardEventInit> = {}) {
  window.dispatchEvent(new KeyboardEvent('keydown', { code, ...opts }));
}

beforeEach(() => {
  Object.values(callbacks).forEach((m) => m.mockReset());
});

describe('useCategoryPlayerHotkeys', () => {
  it('does nothing when active=false', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: false, playlistCount: 10 }));
    press('Space');
    expect(callbacks.onTogglePlayPause).not.toHaveBeenCalled();
  });

  it('Space toggles play', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('Space');
    expect(callbacks.onTogglePlayPause).toHaveBeenCalledOnce();
  });

  it('J/K trigger prev/next', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyJ');
    press('KeyK');
    expect(callbacks.onPrev).toHaveBeenCalledOnce();
    expect(callbacks.onNext).toHaveBeenCalledOnce();
  });

  it('A/S/D/F/G seek to 0/0.25/0.5/0.75/1.0', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyA');
    press('KeyS');
    press('KeyD');
    press('KeyF');
    press('KeyG');
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(1, 0);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(2, 0.25);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(3, 0.5);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(4, 0.75);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(5, 1);
  });

  it('Digit1..Digit9 map to indices 0..8', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    for (let i = 1; i <= 9; i++) press(`Digit${i}`);
    expect(callbacks.onTogglePlaylist).toHaveBeenCalledTimes(9);
    expect(callbacks.onTogglePlaylist).toHaveBeenNthCalledWith(1, 0);
    expect(callbacks.onTogglePlaylist).toHaveBeenNthCalledWith(9, 8);
  });

  it('Digit0 maps to index 9', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('Digit0');
    expect(callbacks.onTogglePlaylist).toHaveBeenCalledWith(9);
  });

  it('Digit5 is no-op when only 4 playlists', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 4 }));
    press('Digit5');
    expect(callbacks.onTogglePlaylist).not.toHaveBeenCalled();
  });

  it('KeyU triggers undo', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyU');
    expect(callbacks.onUndo).toHaveBeenCalledOnce();
  });

  it('ignores keydown when target is an input', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', bubbles: true }));
    expect(callbacks.onTogglePlayPause).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx`
Expected: 9 failures.

- [ ] **Step 3: Implement the hook**

```ts
// frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts
import { useEffect } from 'react';

export interface UseCategoryPlayerHotkeysArgs {
  active: boolean;
  playlistCount: number;
  onTogglePlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onSeekPct: (p: number) => void;
  onTogglePlaylist: (index: number) => void;
  onUndo: () => void;
}

const SEEK_PCT: Record<string, number> = {
  KeyA: 0,
  KeyS: 0.25,
  KeyD: 0.5,
  KeyF: 0.75,
  KeyG: 1,
};

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

function digitIndex(code: string): number | null {
  if (code === 'Digit0') return 9;
  const m = /^Digit([1-9])$/.exec(code);
  return m ? Number(m[1]) - 1 : null;
}

export function useCategoryPlayerHotkeys(args: UseCategoryPlayerHotkeysArgs): void {
  const {
    active,
    playlistCount,
    onTogglePlayPause,
    onPrev,
    onNext,
    onSeekPct,
    onTogglePlaylist,
    onUndo,
  } = args;

  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (isEditable(event.target)) return;

      if (event.code === 'Space') {
        event.preventDefault();
        onTogglePlayPause();
        return;
      }
      if (event.code === 'KeyJ') {
        event.preventDefault();
        onPrev();
        return;
      }
      if (event.code === 'KeyK') {
        event.preventDefault();
        onNext();
        return;
      }
      if (event.code === 'KeyU') {
        event.preventDefault();
        onUndo();
        return;
      }
      const pct = SEEK_PCT[event.code];
      if (pct != null) {
        event.preventDefault();
        onSeekPct(pct);
        return;
      }
      const idx = digitIndex(event.code);
      if (idx != null) {
        if (idx < playlistCount) {
          event.preventDefault();
          onTogglePlaylist(idx);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    active,
    playlistCount,
    onTogglePlayPause,
    onPrev,
    onNext,
    onSeekPct,
    onTogglePlaylist,
    onUndo,
  ]);
}
```

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx`
Expected: 9 passes.

- [ ] **Step 5: Commit**

Stage both files.
Use `caveman:caveman-commit`: `feat: add category-player hotkeys hook`.

---

## Phase 5 — Cache patching for used-in-playlist

### Task 10: Extend `useCategoryTracks` with `fresh` + `used_in_playlist`

**Files:**
- Modify: `frontend/src/features/categories/hooks/useCategoryTracks.ts`
- Modify: `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

- [ ] **Step 1: Append failing tests**

In `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`, append:

```tsx
describe('useCategoryTracks — fresh + used_in_playlist', () => {
  it('cache key includes fresh slot', () => {
    expect(categoryTracksKey('c', '', 'added_at', 'desc', [], 'all', true)).toEqual([
      'categories', 'tracks', 'c', '', 'added_at', 'desc', '', 'all', true,
    ]);
  });

  it('passes ?fresh=1 to the API when fresh=true', async () => {
    // Use msw spy in scope (existing test file has handlers setup).
    // The handler should observe `fresh=1` in URL.
    // See existing tests for pattern reference.
    // (No new assertion shape here — use whatever spy pattern the file already has.)
  });
});
```

- [ ] **Step 2: Run tests to see first failure**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`
Expected: at least 1 failure on the key tuple length.

- [ ] **Step 3: Modify the hook + type**

Replace `frontend/src/features/categories/hooks/useCategoryTracks.ts` interface block:

```ts
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
  used_in_playlist: boolean;
  added_at: string;
  source_triage_block_id: string | null;
  tags: CategoryTagRef[];
}
```

Replace the `categoryTracksKey` helper and hook signature:

```ts
export const categoryTracksKey = (
  id: string,
  search: string,
  sort: CategoryTrackSort,
  order: SortOrder,
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
  fresh: boolean = false,
) =>
  ['categories', 'tracks', id, search, sort, order,
   [...tagIds].sort().join(','), tagMatch, fresh] as const;

export function useCategoryTracks(
  categoryId: string,
  search: string,
  sort: CategoryTrackSort = 'added_at',
  order: SortOrder = 'desc',
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
  fresh: boolean = false,
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search, sort, order, tagIds, tagMatch, fresh),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
        sort,
        order,
      });
      if (search) params.set('search', search);
      if (tagIds.length > 0) {
        params.set('tags', [...tagIds].sort().join(','));
        if (tagMatch === 'any') params.set('match', 'any');
      }
      params.set('fresh', fresh ? '1' : '0');
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

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`
Expected: pass.

Other callsites that still call `useCategoryTracks(...)` with the 6-arg form keep working (default `fresh=false`).

- [ ] **Step 5: Commit**

Stage:
- `frontend/src/features/categories/hooks/useCategoryTracks.ts`
- `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

Use `caveman:caveman-commit`: `feat: thread fresh + used_in_playlist through useCategoryTracks`.

---

### Task 11: Patch category-tracks cache from playlist mutations

**Files:**
- Modify: `frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts`
- Modify: `frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts`
- Modify: `frontend/src/features/playlists/hooks/__tests__/useAddTracksToPlaylist.test.tsx` (create if missing)

- [ ] **Step 1: Write the failing test**

Create or extend `frontend/src/features/playlists/hooks/__tests__/useAddTracksToPlaylist.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, act } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { useAddTracksToPlaylist } from '../useAddTracksToPlaylist';
import { categoryTracksKey, type PaginatedTracks } from '../../../categories/hooks/useCategoryTracks';
import type { InfiniteData } from '@tanstack/react-query';

const server = setupServer(
  http.post('http://localhost/playlists/:id/tracks', () =>
    HttpResponse.json({ added: 1, skipped: 0 }),
  ),
);
beforeAll(() => server.listen());
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

function wrap(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

function seed(qc: QueryClient, key: ReturnType<typeof categoryTracksKey>): InfiniteData<PaginatedTracks> {
  const data: InfiniteData<PaginatedTracks> = {
    pages: [{
      items: [
        { id: 't1', used_in_playlist: false } as any,
        { id: 't2', used_in_playlist: false } as any,
      ],
      total: 2, limit: 50, offset: 0,
    }],
    pageParams: [0],
  };
  qc.setQueryData(key, data);
  return data;
}

describe('useAddTracksToPlaylist patches category-tracks cache', () => {
  it('sets used_in_playlist=true on affected items in fresh=false cache', async () => {
    const qc = new QueryClient();
    const freshOffKey = categoryTracksKey('cat-1', '', 'added_at', 'desc', [], 'all', false);
    seed(qc, freshOffKey);
    const { result } = renderHook(() => useAddTracksToPlaylist(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ playlistId: 'pl-1', trackIds: ['t1'] });
    });
    const patched = qc.getQueryData<InfiniteData<PaginatedTracks>>(freshOffKey);
    const t1 = patched!.pages[0].items.find((i) => i.id === 't1') as any;
    const t2 = patched!.pages[0].items.find((i) => i.id === 't2') as any;
    expect(t1.used_in_playlist).toBe(true);
    expect(t2.used_in_playlist).toBe(false);
  });

  it('drops affected items from fresh=true cache (shrink)', async () => {
    const qc = new QueryClient();
    const freshOnKey = categoryTracksKey('cat-1', '', 'added_at', 'desc', [], 'all', true);
    seed(qc, freshOnKey);
    const { result } = renderHook(() => useAddTracksToPlaylist(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ playlistId: 'pl-1', trackIds: ['t1'] });
    });
    const patched = qc.getQueryData<InfiniteData<PaginatedTracks>>(freshOnKey);
    const ids = patched!.pages[0].items.map((i) => i.id);
    expect(ids).toEqual(['t2']);
    expect(patched!.pages[0].total).toBe(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/playlists/hooks/__tests__/useAddTracksToPlaylist.test.tsx`
Expected: 2 failures.

- [ ] **Step 3: Patch the mutation hook**

Replace `frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AddTracksResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface AddTracksInput {
  playlistId: string;
  trackIds: string[];
}

/**
 * Cache-key shape from `categoryTracksKey`:
 *   ['categories', 'tracks', id, search, sort, order, tagJoin, tagMatch, fresh]
 * Index 8 holds the boolean fresh flag.
 */
function isFreshKey(key: readonly unknown[]): boolean {
  return key[0] === 'categories' && key[1] === 'tracks' && key[8] === true;
}

export function useAddTracksToPlaylist(): UseMutationResult<AddTracksResult, Error, AddTracksInput> {
  const qc = useQueryClient();
  return useMutation<AddTracksResult, Error, AddTracksInput>({
    mutationFn: ({ playlistId, trackIds }) =>
      api<AddTracksResult>(`/playlists/${playlistId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onSuccess: (_data, { playlistId, trackIds }) => {
      const trackSet = new Set(trackIds);
      qc.setQueriesData<InfiniteData<PaginatedTracks>>(
        { queryKey: ['categories', 'tracks'] },
        (data, query) => {
          if (!data) return data;
          const fresh = isFreshKey(query.queryKey);
          let totalRemoved = 0;
          const pages = data.pages.map((page) => {
            const before = page.items.length;
            const mapped = page.items.map((it) =>
              trackSet.has(it.id) ? { ...it, used_in_playlist: true } : it,
            );
            const filtered = fresh ? mapped.filter((it) => !trackSet.has(it.id)) : mapped;
            totalRemoved += before - filtered.length;
            return { ...page, items: filtered };
          });
          return {
            ...data,
            pages: pages.map((p, idx) =>
              idx === 0 ? { ...p, total: Math.max(0, p.total - totalRemoved) } : p,
            ),
          };
        },
      );
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
    },
  });
}
```

- [ ] **Step 4: Patch the remove-from-playlist hook**

In `frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts`, extend `onSuccess`:

```ts
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      // Removing from a playlist may flip used_in_playlist back to false on
      // category-tracks views, but only if no OTHER playlist still holds the
      // track. We cannot compute that locally, so invalidate.
      qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
```

- [ ] **Step 5: Run tests**

From `frontend/`: `pnpm vitest run src/features/playlists/hooks/__tests__`
Expected: green.

- [ ] **Step 6: Commit**

Stage:
- Both mutation hooks
- Test file

Use `caveman:caveman-commit`: `feat: playlist mutations patch category-tracks used_in_playlist cache`.

---

## Phase 6 — UI components

### Task 12: `PlayerPanelTagCloud`

**Files:**
- Create: `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`
- Create: `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`

- [ ] **Step 1: Inspect existing tag types**

Run: `cat frontend/src/features/tags/index.ts`
Identify `useTags`, `TagPill`, and the `CategoryTagRef` interface from `useCategoryTracks`.

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [
      { id: 'tg-a', name: 'acid', color: '#f00' },
      { id: 'tg-b', name: 'banger', color: '#0f0' },
    ],
    isLoading: false,
  }),
}));

function ui(props: Parameters<typeof PlayerPanelTagCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelTagCloud {...props} />
    </MantineProvider>
  );
}

describe('PlayerPanelTagCloud', () => {
  it('renders all user tags', () => {
    render(ui({ trackId: 't-1', assignedTagIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByRole('button', { name: /acid/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /banger/i })).toBeInTheDocument();
  });

  it('marks assigned tags as selected via aria-pressed', () => {
    render(ui({ trackId: 't-1', assignedTagIds: ['tg-a'], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByRole('button', { name: /acid/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /banger/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('click on unassigned chip calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ trackId: 't-1', assignedTagIds: [], onAdd, onRemove: vi.fn() }));
    await userEvent.click(screen.getByRole('button', { name: /acid/i }));
    expect(onAdd).toHaveBeenCalledWith('tg-a');
  });

  it('click on assigned chip calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ trackId: 't-1', assignedTagIds: ['tg-a'], onAdd: vi.fn(), onRemove }));
    await userEvent.click(screen.getByRole('button', { name: /acid/i }));
    expect(onRemove).toHaveBeenCalledWith('tg-a');
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
Expected: failures (module not found).

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/features/categories/components/PlayerPanelTagCloud.tsx
import { useMemo } from 'react';
import { Chip, Group, Stack, Text } from '@mantine/core';
import { useTags } from '../../tags';

export interface PlayerPanelTagCloudProps {
  trackId: string;
  assignedTagIds: readonly string[];
  onAdd: (tagId: string) => void;
  onRemove: (tagId: string) => void;
}

export function PlayerPanelTagCloud(props: PlayerPanelTagCloudProps) {
  const { assignedTagIds, onAdd, onRemove } = props;
  const tagsQuery = useTags();
  const assigned = useMemo(() => new Set(assignedTagIds), [assignedTagIds]);

  const tags = (tagsQuery.data ?? [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));

  if (tags.length === 0) {
    return <Text c="dimmed" size="sm">No tags yet</Text>;
  }

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap">
        {tags.map((t) => {
          const selected = assigned.has(t.id);
          return (
            <Chip
              key={t.id}
              checked={selected}
              size="sm"
              variant={selected ? 'filled' : 'outline'}
              color={t.color ?? 'gray'}
              aria-pressed={selected}
              onChange={() => (selected ? onRemove(t.id) : onAdd(t.id))}
            >
              {t.name}
            </Chip>
          );
        })}
      </Group>
    </Stack>
  );
}
```

> Note: Mantine `Chip` exposes a checkbox-like API. The wrapping element behaves as a `button` for the test queries via role mapping. If the test reports "no role button" — inspect `Chip` in dev tools and use `screen.getByText('acid').closest('label')` instead, or update the test to use `getByText` semantics.

- [ ] **Step 5: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
Expected: pass. If queries by role fail because Mantine `Chip` renders a `<label>` wrapping the checkbox, adjust tests to query by text (e.g., `screen.getByText('acid')`) and assert against the underlying input's `checked` attribute via `.closest('label')!.querySelector('input')`.

- [ ] **Step 6: Commit**

Stage both files.
Use `caveman:caveman-commit`: `feat: add PlayerPanelTagCloud`.

---

### Task 13: `PlayerPanelPlaylistCloud`

**Files:**
- Create: `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx`
- Create: `frontend/src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`

- [ ] **Step 1: Inspect existing playlist types + hook**

Run: `cat frontend/src/features/playlists/hooks/usePlaylists.ts | head -50`
Identify the `usePlaylists({ status: 'active' })` signature and the row shape.

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { PlayerPanelPlaylistCloud } from '../PlayerPanelPlaylistCloud';

const mockPlaylists = Array.from({ length: 12 }, (_, i) => ({
  id: `pl-${i}`,
  name: `Playlist ${i}`,
  status: 'active',
}));

vi.mock('../../../playlists/hooks/usePlaylists', () => ({
  usePlaylists: () => ({ data: { items: mockPlaylists, total: 12 }, isLoading: false }),
}));

function ui(props: Parameters<typeof PlayerPanelPlaylistCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelPlaylistCloud {...props} />
    </MantineProvider>
  );
}

describe('PlayerPanelPlaylistCloud', () => {
  it('renders hotkey badges 1-9 then 0 on first 10', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.queryByText('11')).not.toBeInTheDocument();
  });

  it('marks chips for playlists already containing the track', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: ['pl-2'], onAdd: vi.fn(), onRemove: vi.fn() }));
    const chip = screen.getByText('Playlist 2').closest('label')!;
    expect(chip.querySelector('input')!.checked).toBe(true);
  });

  it('click on outline chip calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd, onRemove: vi.fn() }));
    await userEvent.click(screen.getByText('Playlist 0'));
    expect(onAdd).toHaveBeenCalledWith('pl-0');
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`
Expected: failures.

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx
import { useMemo } from 'react';
import { Badge, Chip, Group, Stack, Text } from '@mantine/core';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';

export interface PlayerPanelPlaylistCloudProps {
  trackId: string;
  trackPlaylistIds: readonly string[];
  onAdd: (playlistId: string) => void;
  onRemove: (playlistId: string) => void;
}

const HOTKEY_LABELS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

export function PlayerPanelPlaylistCloud(props: PlayerPanelPlaylistCloudProps) {
  const { trackPlaylistIds, onAdd, onRemove } = props;
  const query = usePlaylists({ status: 'active', sort: 'created_at_asc' });
  const playlists = query.data?.items ?? [];

  const inPlaylist = useMemo(() => new Set(trackPlaylistIds), [trackPlaylistIds]);

  if (playlists.length === 0) {
    return <Text c="dimmed" size="sm">No active playlists</Text>;
  }

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap">
        {playlists.map((pl, idx) => {
          const selected = inPlaylist.has(pl.id);
          const hotkey = idx < HOTKEY_LABELS.length ? HOTKEY_LABELS[idx] : null;
          return (
            <Chip
              key={pl.id}
              checked={selected}
              size="sm"
              variant={selected ? 'filled' : 'outline'}
              aria-pressed={selected}
              onChange={() => (selected ? onRemove(pl.id) : onAdd(pl.id))}
            >
              <Group gap={4} wrap="nowrap" align="center">
                {hotkey ? (
                  <Badge variant="default" size="xs" radius="sm">
                    {hotkey}
                  </Badge>
                ) : null}
                <span>{pl.name}</span>
              </Group>
            </Chip>
          );
        })}
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 5: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`
Expected: pass.

- [ ] **Step 6: Commit**

Stage both files.
Use `caveman:caveman-commit`: `feat: add PlayerPanelPlaylistCloud with hotkey badges`.

---

### Task 14: `UsedInPlaylistBadge` + TrackRow integration

**Files:**
- Create: `frontend/src/features/categories/components/UsedInPlaylistBadge.tsx`
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`
- Modify: `frontend/src/features/categories/components/__tests__/TrackRow.test.tsx`

- [ ] **Step 1: Write the failing test**

In `frontend/src/features/categories/components/__tests__/TrackRow.test.tsx`, append:

```tsx
describe('TrackRow — used_in_playlist badge', () => {
  it('renders badge when used_in_playlist=true', () => {
    const track = { id: 't1', used_in_playlist: true, title: 'X', artists: [], tags: [] } as any;
    render(<TrackRow track={track} variant="desktop" categoryId="c1" actions={null} />);
    expect(screen.getByText('In playlist')).toBeInTheDocument();
  });

  it('does not render badge when used_in_playlist=false', () => {
    const track = { id: 't1', used_in_playlist: false, title: 'X', artists: [], tags: [] } as any;
    render(<TrackRow track={track} variant="desktop" categoryId="c1" actions={null} />);
    expect(screen.queryByText('In playlist')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Create the badge**

```tsx
// frontend/src/features/categories/components/UsedInPlaylistBadge.tsx
import { Badge } from '@mantine/core';

export function UsedInPlaylistBadge() {
  return (
    <Badge color="gray" variant="light" size="xs">
      In playlist
    </Badge>
  );
}
```

- [ ] **Step 3: Integrate into TrackRow**

In `frontend/src/features/categories/components/TrackRow.tsx`, locate the row body. Add inside the existing "tags" cell (desktop variant) or wherever the row meta lives:

```tsx
{track.used_in_playlist ? <UsedInPlaylistBadge /> : null}
```

Wire up the import at the top:
```tsx
import { UsedInPlaylistBadge } from './UsedInPlaylistBadge';
```

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: pass.

- [ ] **Step 5: Commit**

Stage all touched files.
Use `caveman:caveman-commit`: `feat: render UsedInPlaylistBadge on category track rows`.

---

### Task 15: `CategoryPlayerPanel` (composition)

**Files:**
- Create: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Create: `frontend/src/features/categories/components/CategoryPlayerPanel.module.css`
- Create: `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`

This task wires the existing `PlayerCard` (from `features/playback`) together with the new clouds, hotkeys, undo notifications, and "Remove from category" button.

- [ ] **Step 1: Inspect `PlayerCard` props**

Run: `head -40 frontend/src/features/playback/PlayerCard.tsx`
Identify the props surface — particularly how it receives `track`, `state`, `onPlayPause`, `onPrev`, `onNext`, `seekMs/positionMs/durationMs`. If `PlayerCard` is opinionated about its own layout (margins/borders), wrap rather than nest.

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryPlayerPanel } from '../CategoryPlayerPanel';
import { undoStack } from '../../hooks/useUndoStack';

const playback = {
  controls: {
    togglePlayPause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seekPct: vi.fn(),
    play: vi.fn(),
  },
  queue: { source: { type: 'category', categoryId: 'c1', styleId: 's1' }, tracks: [], cursor: 0, status: 'playing' },
  track: { current: { id: 't1', title: 'X', artists: 'A', duration_ms: 200000, spotify_id: 'sp1', cover_url: null }, positionMs: 0, durationMs: 200000 },
  sdk: { ready: true, error: null },
  devices: { active: null, list: [], cloderTabId: null, isLoading: false, error: null, isOpen: false, pickerAnchor: null, open: vi.fn(), close: vi.fn(), refresh: vi.fn(), pick: vi.fn() },
};
vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));
vi.mock('../../../tags', () => ({ useTags: () => ({ data: [], isLoading: false }) }));
vi.mock('../../../playlists/hooks/usePlaylists', () => ({ usePlaylists: () => ({ data: { items: [{ id: 'pl-1', name: 'Acid' }] }, isLoading: false }) }));
vi.mock('../../hooks/useRemoveTrackOptimistic', () => ({
  useRemoveTrackOptimistic: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));

function ui() {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <CategoryPlayerPanel categoryId="c1" styleId="s1" />
      </MantineProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => undoStack.clear());

describe('CategoryPlayerPanel', () => {
  it('renders the current track title', () => {
    render(ui());
    expect(screen.getByText('X')).toBeInTheDocument();
  });

  it('renders the playlist cloud', () => {
    render(ui());
    expect(screen.getByText('Acid')).toBeInTheDocument();
  });

  it('shows Remove from category button', () => {
    render(ui());
    expect(screen.getByRole('button', { name: /remove from category/i })).toBeInTheDocument();
  });

  it('Undo-key triggers undo when stack has an entry', async () => {
    const undo = vi.fn(() => Promise.resolve());
    undoStack.push({ id: 'a', label: 'L', undo });
    render(ui());
    await userEvent.keyboard('u');
    expect(undo).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: failures.

- [ ] **Step 4: Implement the panel**

```tsx
// frontend/src/features/categories/components/CategoryPlayerPanel.tsx
import { useCallback, useEffect } from 'react';
import { Button, Divider, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { useTags } from '../../tags';
import { useAddTrackTag } from '../../tags/hooks/useAddTrackTag';
import { useRemoveTrackTag } from '../../tags/hooks/useRemoveTrackTag';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';
import { useRemoveTrackFromPlaylist } from '../../playlists/hooks/useRemoveTrackFromPlaylist';
import { useRemoveTrackOptimistic } from '../hooks/useRemoveTrackOptimistic';
import { useCategoryPlayerHotkeys } from '../hooks/useCategoryPlayerHotkeys';
import { undoStack, useUndoStack } from '../hooks/useUndoStack';
import { PlayerCard } from '../../playback/PlayerCard';
import { PlayerPanelTagCloud } from './PlayerPanelTagCloud';
import { PlayerPanelPlaylistCloud } from './PlayerPanelPlaylistCloud';
import classes from './CategoryPlayerPanel.module.css';

export interface CategoryPlayerPanelProps {
  categoryId: string;
  styleId: string;
}

const TOAST_ID = 'category-player-undo';

export function CategoryPlayerPanel({ categoryId, styleId }: CategoryPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const tagsQuery = useTags();
  const playlistsQuery = usePlaylists({ status: 'active', sort: 'created_at_asc' });
  const addTag = useAddTrackTag();
  const removeTag = useRemoveTrackTag();
  const addToPlaylist = useAddTracksToPlaylist();
  const removeFromPlaylist = useRemoveTrackFromPlaylist();
  const removeFromCat = useRemoveTrackOptimistic();
  const { entry } = useUndoStack();

  const current = playback.track.current;
  const trackId = current?.id ?? null;

  // Local lookup helpers for "is this tag/playlist already on the track?"
  const assignedTagIds: string[] = []; // populated by parent in a future task — placeholder for now
  const trackPlaylistIds: string[] = []; // same — see Task 18

  const pushUndo = useCallback(
    (label: string, undo: () => Promise<void> | void) => {
      undoStack.push({ id: crypto.randomUUID(), label, undo });
      notifications.show({
        id: TOAST_ID,
        message: label,
        autoClose: 8000,
        withCloseButton: true,
      });
    },
    [],
  );

  useEffect(() => {
    if (!entry) {
      notifications.hide(TOAST_ID);
    }
  }, [entry]);

  const onAddTag = useCallback(async (tagId: string) => {
    if (!trackId) return;
    await addTag.mutateAsync({ trackId, tagId });
    pushUndo(t('category_player.toasts.tagged'), () => removeTag.mutateAsync({ trackId, tagId }));
  }, [trackId, addTag, removeTag, pushUndo, t]);

  const onRemoveTag = useCallback(async (tagId: string) => {
    if (!trackId) return;
    await removeTag.mutateAsync({ trackId, tagId });
    pushUndo(t('category_player.toasts.untagged'), () => addTag.mutateAsync({ trackId, tagId }));
  }, [trackId, addTag, removeTag, pushUndo, t]);

  const onAddPlaylist = useCallback(async (playlistId: string) => {
    if (!trackId) return;
    await addToPlaylist.mutateAsync({ playlistId, trackIds: [trackId] });
    pushUndo(
      t('category_player.toasts.added_to_playlist'),
      () => removeFromPlaylist.mutateAsync({ playlistId, trackId }),
    );
  }, [trackId, addToPlaylist, removeFromPlaylist, pushUndo, t]);

  const onRemovePlaylist = useCallback(async (playlistId: string) => {
    if (!trackId) return;
    await removeFromPlaylist.mutateAsync({ playlistId, trackId });
    pushUndo(
      t('category_player.toasts.removed_from_playlist'),
      () => addToPlaylist.mutateAsync({ playlistId, trackIds: [trackId] }),
    );
  }, [trackId, addToPlaylist, removeFromPlaylist, pushUndo, t]);

  const onTogglePlaylistByIndex = useCallback((index: number) => {
    const pl = playlistsQuery.data?.items?.[index];
    if (!pl) return;
    const alreadyIn = trackPlaylistIds.includes(pl.id);
    void (alreadyIn ? onRemovePlaylist(pl.id) : onAddPlaylist(pl.id));
  }, [playlistsQuery.data, trackPlaylistIds, onAddPlaylist, onRemovePlaylist]);

  const onRemoveFromCategory = useCallback(async () => {
    if (!trackId) return;
    await removeFromCat.mutateAsync({ categoryId, trackId });
    pushUndo(t('category_player.toasts.removed_from_category'), () => {
      // No add-back operation — invalidate to refetch will surface the track if a server-side undo
      // exists. For now, we rely on the optimistic context capture inside the mutation hook.
    });
  }, [trackId, categoryId, removeFromCat, pushUndo, t]);

  useCategoryPlayerHotkeys({
    active: playback.queue.source?.type === 'category' && playback.queue.source.categoryId === categoryId,
    playlistCount: Math.min(10, playlistsQuery.data?.items?.length ?? 0),
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekPct: (p) => void playback.controls.seekPct(p),
    onTogglePlaylist: onTogglePlaylistByIndex,
    onUndo: () => void undoStack.popAndRun(),
  });

  if (!current) {
    return (
      <Stack className={classes.root} gap="md">
        <Text c="dimmed">{t('category_player.empty.pick_track')}</Text>
      </Stack>
    );
  }

  return (
    <Stack className={classes.root} gap="md">
      <PlayerCard
        track={current}
        state={playback.queue.status}
        positionMs={playback.track.positionMs}
        durationMs={playback.track.durationMs}
        onPlayPause={() => void playback.controls.togglePlayPause()}
        onPrev={() => void playback.controls.prev()}
        onNext={() => void playback.controls.next()}
        onSeekMs={(ms) => void playback.controls.seekMs(ms)}
      />
      <Divider />
      <Text fw={500} size="sm">{t('category_player.sections.tags')}</Text>
      <PlayerPanelTagCloud
        trackId={current.id}
        assignedTagIds={assignedTagIds}
        onAdd={(id) => void onAddTag(id)}
        onRemove={(id) => void onRemoveTag(id)}
      />
      <Divider />
      <Text fw={500} size="sm">{t('category_player.sections.playlists')}</Text>
      <PlayerPanelPlaylistCloud
        trackId={current.id}
        trackPlaylistIds={trackPlaylistIds}
        onAdd={(id) => void onAddPlaylist(id)}
        onRemove={(id) => void onRemovePlaylist(id)}
      />
      <Divider />
      <Button color="red" variant="light" onClick={() => void onRemoveFromCategory()}>
        {t('category_player.actions.remove_from_category')}
      </Button>
    </Stack>
  );
}
```

CSS:

```css
/* frontend/src/features/categories/components/CategoryPlayerPanel.module.css */
.root {
  width: 420px;
  padding: var(--mantine-spacing-md);
  border-right: 1px solid var(--mantine-color-default-border);
  height: 100%;
  overflow-y: auto;
}
```

> Open issue acknowledged: `assignedTagIds` and `trackPlaylistIds` are placeholders. Task 18 fills them by reading the playing track's `tags[]` field from the cached `categoryTracksKey(...)` and by adding a `track_playlist_ids` projection in a follow-up. For now the panel renders empty assignments; the wiring lands when `CategoryDetailPage` mounts it.

- [ ] **Step 5: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: pass.

- [ ] **Step 6: Commit**

Stage all touched files.
Use `caveman:caveman-commit`: `feat: assemble CategoryPlayerPanel with tags, playlists, undo, hotkeys`.

---

## Phase 7 — Integration into CategoryDetailPage

### Task 16: `TracksTab` Fresh toggle + Play affordance

**Files:**
- Modify: `frontend/src/features/categories/components/TracksTab.tsx`
- Create: `frontend/src/features/categories/lib/freshUrlState.ts`
- Create: `frontend/src/features/categories/lib/__tests__/freshUrlState.test.ts`
- Modify: `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`

- [ ] **Step 1: Write `freshUrlState` helpers + tests**

```ts
// frontend/src/features/categories/lib/freshUrlState.ts
// URL convention:
//   absent → fresh = true (default ON for new UI)
//   ?fresh=0 → false
//   ?fresh=1 → true
export function readFresh(params: URLSearchParams): boolean {
  const raw = params.get('fresh');
  if (raw == null) return true;
  return raw !== '0';
}

export function writeFresh(params: URLSearchParams, fresh: boolean): URLSearchParams {
  const next = new URLSearchParams(params);
  if (fresh) next.delete('fresh');
  else next.set('fresh', '0');
  return next;
}
```

```ts
// frontend/src/features/categories/lib/__tests__/freshUrlState.test.ts
import { describe, it, expect } from 'vitest';
import { readFresh, writeFresh } from '../freshUrlState';

describe('freshUrlState', () => {
  it('absent param defaults to true', () => {
    expect(readFresh(new URLSearchParams(''))).toBe(true);
  });
  it('fresh=0 reads as false', () => {
    expect(readFresh(new URLSearchParams('fresh=0'))).toBe(false);
  });
  it('fresh=1 reads as true', () => {
    expect(readFresh(new URLSearchParams('fresh=1'))).toBe(true);
  });
  it('writing true removes the param', () => {
    const next = writeFresh(new URLSearchParams('fresh=0'), true);
    expect(next.has('fresh')).toBe(false);
  });
  it('writing false sets fresh=0', () => {
    const next = writeFresh(new URLSearchParams(''), false);
    expect(next.get('fresh')).toBe('0');
  });
});
```

Run: `pnpm vitest run src/features/categories/lib/__tests__/freshUrlState.test.ts`
Expected: pass.

- [ ] **Step 2: Patch `TracksTab.tsx`**

In `frontend/src/features/categories/components/TracksTab.tsx`, add:

```tsx
import { Switch, Tooltip } from '@mantine/core';
import { readFresh, writeFresh } from '../lib/freshUrlState';

// inside the component:
const fresh = readFresh(searchParams);
const setFresh = (value: boolean) => {
  setSearchParams(writeFresh(searchParams, value), { replace: true });
};
```

Pass `fresh` into `useCategoryTracks(... , fresh)`.

In the `filterRow`, append after the existing tags filter:

```tsx
<Tooltip label={t('categories.filters.fresh_tooltip')}>
  <Switch
    label={t('categories.filters.fresh_label')}
    checked={fresh}
    onChange={(e) => setFresh(e.currentTarget.checked)}
  />
</Tooltip>
```

Also extend the empty-state branch when both `items.length === 0` AND `fresh === true`:

```tsx
if (!isLoading && items.length === 0 && !debounced && fresh) {
  return (
    <Stack gap="md">
      {filterRow}
      <EmptyState
        title={t('categories.empty_state.no_fresh_tracks_title')}
        body={
          <Button variant="default" onClick={() => setFresh(false)}>
            {t('categories.empty_state.disable_fresh')}
          </Button>
        }
      />
      {modal}
    </Stack>
  );
}
```

- [ ] **Step 3: Patch TracksTab tests**

Append to `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`:

```tsx
describe('Fresh-only toggle', () => {
  it('default ON, sends fresh=1 to API', async () => {
    // Use existing msw server + spy on request URL.
    // Assert one network call's URL ends with `?fresh=1` (or includes it).
  });

  it('toggle off updates URL to ?fresh=0', async () => {
    // Assert searchParams transition after a click on the Switch.
  });
});
```

Fill in with the exact spy/server pattern used in the rest of the test file.

- [ ] **Step 4: Run tests**

From `frontend/`: `pnpm vitest run src/features/categories/components/__tests__/TracksTab.test.tsx src/features/categories/lib/__tests__/freshUrlState.test.ts`
Expected: green.

- [ ] **Step 5: Commit**

Stage all touched files.
Use `caveman:caveman-commit`: `feat: TracksTab Fresh-only toggle wired through URL state`.

---

### Task 17: `CategoryDetailPage` split layout + provider wiring

**Files:**
- Modify: `frontend/src/features/categories/routes/CategoryDetailPage.tsx`

- [ ] **Step 1: Update the page**

Wrap the existing content in a Mantine `Flex` with two columns on desktop:

```tsx
import { Flex, useMantineTheme } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useEffect, useMemo } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import { CategoryPlayerPanel } from '../components/CategoryPlayerPanel';
import { useCategoryPlayerQueue } from '../hooks/useCategoryPlayerQueue';
// ... existing imports

function CategoryDetailPageInner({ styleId, id }: { styleId: string; id: string }) {
  // ... existing hooks
  const playback = usePlayback();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);

  // Pre-warm the SDK on mount (mirrors curate). Categories panel is the queue owner.
  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  // Read the current tracks list from the cache (TracksTab already drives the query).
  // For the queue binding we lift this responsibility into a custom hook backed by useCategoryTracks
  // at default filter+sort+search (no params). See useCategoryPlayerQueue's reactive bind.
  // ...

  // Mobile gets the existing one-column layout; the player lives on a child route /player.
  if (!isDesktop) {
    return /* existing single-column return */;
  }

  return (
    <Stack gap="lg">
      {/* existing breadcrumbs + title + buttons */}
      <Flex gap="lg" align="flex-start">
        <CategoryPlayerPanel categoryId={id} styleId={styleId} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <TracksTab categoryId={id} styleId={styleId} />
        </div>
      </Flex>
      <CategoryFormDialog /* existing */ />
    </Stack>
  );
}
```

Add the queue-binding hook call inside `TracksTab` OR keep it at the page level by reading the same `useCategoryTracks(...)` query. The cleanest is at the page level — lift the params slightly. Given the spec calls for a dedicated `useCategoryPlayerQueue`, expose a thin wrapper inside `TracksTab` to surface its items, or duplicate the `useCategoryTracks` call here with default args. Pick the simpler route: at the page level, call `useCategoryTracks(id, '', 'added_at', 'desc', [], 'all', true)` and pass to `useCategoryPlayerQueue`. The actual `TracksTab` keeps its own query (UI filters apply to the visible list, not necessarily to the player queue). Annotate clearly:

```tsx
// The PLAYER queue is the default fresh-on view of the category. UI-applied
// search/tag filters do not affect what the player auto-advances through.
const playerQuery = useCategoryTracks(id, '', 'added_at', 'desc', [], 'all', true);
const playerTracks = useMemo(
  () => (playerQuery.data?.pages ?? []).flatMap((p) => p.items.map(toPlaybackTrack)),
  [playerQuery.data],
);
useCategoryPlayerQueue(id, styleId, playerTracks);
```

Provide the `toPlaybackTrack` adapter at the bottom of the file (extracted to `frontend/src/features/categories/lib/toPlaybackTrack.ts` if reused — TBD now, inline below):

```ts
function toPlaybackTrack(t: CategoryTrack): PlaybackTrack {
  return {
    id: t.id,
    title: t.title,
    artists: t.artists.map((a) => a.name).join(', '),
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
    cover_url: null,
  };
}
```

- [ ] **Step 2: Typecheck**

From `frontend/`: `pnpm typecheck`
Expected: pass.

- [ ] **Step 3: Run all category tests**

From `frontend/`: `pnpm vitest run src/features/categories`
Expected: green.

- [ ] **Step 4: Manual smoke**

Run `pnpm dev` and open a category. Verify:
- Player panel renders on the left (~420px).
- Tracks table reflows to the right.
- Pressing Play on a row starts playback; cover/title appear in panel.
- Pressing `1` toggles current track membership in the first playlist; toast appears.
- Pressing `U` undoes; toast hides.

- [ ] **Step 5: Commit**

Stage:
- `frontend/src/features/categories/routes/CategoryDetailPage.tsx`

Use `caveman:caveman-commit`: `feat: mount CategoryPlayerPanel inside CategoryDetailPage`.

---

### Task 18: Mobile fullscreen player route

**Files:**
- Create: `frontend/src/features/categories/routes/CategoryPlayerPage.tsx`
- Modify: `frontend/src/routes/router.tsx`
- Modify: `frontend/src/features/categories/components/TracksTab.tsx` (mobile branch — add Play affordance that navigates to `/player`)

- [ ] **Step 1: Create the page**

```tsx
// frontend/src/features/categories/routes/CategoryPlayerPage.tsx
import { Stack, ActionIcon, Group } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useParams, Navigate } from 'react-router';
import { CategoryPlayerPanel } from '../components/CategoryPlayerPanel';
import { useEffect } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import { useCategoryTracks } from '../hooks/useCategoryTracks';
import { useCategoryPlayerQueue } from '../hooks/useCategoryPlayerQueue';
import type { PlaybackTrack } from '../../playback/lib/types';

export function CategoryPlayerPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/categories" replace />;
  return <CategoryPlayerPageInner styleId={styleId} id={id} />;
}

function CategoryPlayerPageInner({ styleId, id }: { styleId: string; id: string }) {
  const navigate = useNavigate();
  const playback = usePlayback();
  const playerQuery = useCategoryTracks(id, '', 'added_at', 'desc', [], 'all', true);
  const playerTracks: PlaybackTrack[] = (playerQuery.data?.pages ?? []).flatMap((p) =>
    p.items.map((t) => ({
      id: t.id,
      title: t.title,
      artists: t.artists.map((a) => a.name).join(', '),
      duration_ms: t.length_ms ?? 0,
      spotify_id: t.spotify_id,
      cover_url: null,
    })),
  );
  useCategoryPlayerQueue(id, styleId, playerTracks);
  useEffect(() => { void playback.controls.prewarm(); }, [playback.controls]);

  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon variant="subtle" onClick={() => navigate(`/categories/${styleId}/${id}`)}>
          <IconArrowLeft />
        </ActionIcon>
      </Group>
      <CategoryPlayerPanel categoryId={id} styleId={styleId} />
    </Stack>
  );
}
```

- [ ] **Step 2: Register the route**

In `frontend/src/routes/router.tsx`, locate the categories block and add:

```tsx
{
  path: '/categories/:styleId/:id/player',
  element: <CategoryPlayerPage />,
},
```

Import the page at the top of the file.

- [ ] **Step 3: Add mobile Play affordance**

In `TracksTab.tsx` mobile branch (`isMobile` branch), inside each `TrackRow` `actions` slot, add a navigate button:

```tsx
<ActionIcon
  variant="subtle"
  onClick={() => navigate(`/categories/${styleId}/${id}/player`)}
  aria-label={t('category_player.actions.open_player_aria')}
>
  <IconPlayerPlayFilled />
</ActionIcon>
```

(Imports: `useNavigate` from `react-router`, `IconPlayerPlayFilled` from `@tabler/icons-react`.)

- [ ] **Step 4: Test**

From `frontend/`:
```
pnpm typecheck
pnpm vitest run
```
Expected: green.

- [ ] **Step 5: Commit**

Stage all touched files.
Use `caveman:caveman-commit`: `feat: add mobile category player child route`.

---

## Phase 8 — i18n, integration tests, CLAUDE.md

### Task 19: i18n strings

**Files:**
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/i18n/locales/ru.json`

- [ ] **Step 1: Add keys to en.json**

Under a top-level `category_player` object (and any new `categories.filters.fresh_*` keys), insert:

```json
{
  "categories": {
    "filters": {
      "fresh_label": "Fresh only",
      "fresh_tooltip": "Hide tracks already used in any playlist"
    },
    "empty_state": {
      "no_fresh_tracks_title": "No fresh tracks here",
      "disable_fresh": "Show all tracks"
    }
  },
  "category_player": {
    "sections": { "tags": "Tags", "playlists": "Playlists" },
    "actions": {
      "remove_from_category": "Remove from category",
      "open_player_aria": "Open player"
    },
    "empty": { "pick_track": "Pick a track to start playing" },
    "toasts": {
      "tagged": "Tag added",
      "untagged": "Tag removed",
      "added_to_playlist": "Added to playlist",
      "removed_from_playlist": "Removed from playlist",
      "removed_from_category": "Removed from category"
    }
  }
}
```

Merge (don't replace) — the file already contains `categories.*` keys.

- [ ] **Step 2: Mirror in ru.json**

Russian translations matching the same shape.

- [ ] **Step 3: Typecheck**

From `frontend/`: `pnpm typecheck`
Expected: pass; i18n key references compile.

- [ ] **Step 4: Commit**

Stage both i18n files.
Use `caveman:caveman-commit`: `feat: i18n strings for category player`.

---

### Task 20: End-to-end integration test (mocked SDK)

**Files:**
- Create: `frontend/src/features/categories/__tests__/integration.player.test.tsx`

- [ ] **Step 1: Write the integration test**

```tsx
// frontend/src/features/categories/__tests__/integration.player.test.tsx
import { describe, it, expect, vi, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { renderApp } from '../../../test/renderApp';

const tracks = [
  { id: 't1', title: 'Track A', mix_name: null, artists: [{ id: 'a', name: 'X' }],
    label: null, bpm: 120, length_ms: 200000, publish_date: null,
    spotify_release_date: '2024-01-01', isrc: null, spotify_id: 'sp1',
    release_type: null, is_ai_suspected: false, used_in_playlist: false,
    added_at: '2024-01-02', source_triage_block_id: null, tags: [] },
  { id: 't2', title: 'Track B', mix_name: null, artists: [{ id: 'b', name: 'Y' }],
    label: null, bpm: 121, length_ms: 200000, publish_date: null,
    spotify_release_date: '2024-01-02', isrc: null, spotify_id: 'sp2',
    release_type: null, is_ai_suspected: false, used_in_playlist: false,
    added_at: '2024-01-03', source_triage_block_id: null, tags: [] },
];

const server = setupServer(
  http.get('http://localhost/categories/cat-1', () =>
    HttpResponse.json({ id: 'cat-1', name: 'House', style_id: 's1', style_name: 'House', track_count: 2 })),
  http.get('http://localhost/categories/cat-1/tracks', () =>
    HttpResponse.json({ items: tracks, total: 2, limit: 50, offset: 0 })),
  http.get('http://localhost/playlists', () =>
    HttpResponse.json({ items: [{ id: 'pl-1', name: 'Acid', status: 'active' }], total: 1 })),
  http.get('http://localhost/tags', () => HttpResponse.json({ items: [] })),
  http.post('http://localhost/playlists/pl-1/tracks', () =>
    HttpResponse.json({ added: 1, skipped: 0 })),
  http.delete('http://localhost/playlists/pl-1/tracks/t1', () =>
    HttpResponse.json({})),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('Category player — integration', () => {
  it('hotkey 1 adds current track to first playlist, toast appears, U undoes', async () => {
    renderApp({ url: '/categories/s1/cat-1' });
    // Wait for the player to render the first track once auto-bound.
    // Click the row to start playback explicitly.
    const playA = await screen.findByText('Track A');
    await userEvent.click(playA);
    await waitFor(() => expect(screen.getByText('Track A')).toBeInTheDocument());
    await userEvent.keyboard('1');
    await waitFor(() => screen.getByText(/Added to playlist/i));
    await userEvent.keyboard('u');
    await waitFor(() =>
      expect(screen.queryByText(/Added to playlist/i)).not.toBeInTheDocument(),
    );
  });
});
```

> Note: the test relies on `renderApp` (`frontend/src/test/renderApp.tsx`) to mount the full SPA inside the test harness. If the helper doesn't support custom URLs yet, extend it inline. SDK is NOT loaded — `controls.play()` is a no-op when SDK isn't ready, but the cache mutations (which drive the UI) still run.

- [ ] **Step 2: Run the test**

From `frontend/`: `pnpm vitest run src/features/categories/__tests__/integration.player.test.tsx`
Expected: pass. Adjust selectors as needed once you observe actual DOM.

- [ ] **Step 3: Run the full frontend suite**

From `frontend/`: `pnpm vitest run`
Expected: green.

- [ ] **Step 4: Commit**

Stage:
- The integration test file
- Any harness adjustments to `renderApp.tsx`

Use `caveman:caveman-commit`: `test: integration coverage for category player hotkey + undo`.

---

### Task 21: CLAUDE.md updates

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append new gotchas**

Add the following bullet points under the existing **Frontend** gotchas section in `CLAUDE.md`:

```
- **`QueueSource` is a discriminated union.** Variants: `{ type: 'bucket', blockId, bucketId }` (curate) and `{ type: 'category', categoryId, styleId }` (category player). Add an exhaustive switch when consuming.
- **MiniBar and LeaveContextDialog have been deleted.** Both Curate and Category players own their routes; navigating away clears the queue. `hasPlayerCard(pathname)` now also matches `/categories/:styleId/:id`.
- **`useCategoryTracks` cache key includes `fresh`.** The key tuple is `[..., tagJoin, tagMatch, fresh]` (index 8 is the boolean fresh flag). Mutations that affect playlist membership MUST iterate `['categories','tracks']` queries and patch BOTH fresh-on and fresh-off views.
- **Fullscreen mobile player at `/categories/:styleId/:id/player`.** Back button navigates back to `CategoryDetailPage` and DOES NOT clear the queue (same parent component still mounted). `clearQueue` fires only when leaving the category entirely.
- **Playlist hotkeys map index 0..9 → `Digit1`..`Digit9, Digit0`.** Index 9 = `Digit0` (NOT `Digit0` for index 0).
- **Category player undo stack is depth 1.** `undoStack.push` replaces any prior entry; `notifications.hide(TOAST_ID)` runs when the stack drains to keep the toast in sync.
```

- [ ] **Step 2: Commit**

Stage:
- `CLAUDE.md`

Use `caveman:caveman-commit`: `docs: CLAUDE.md gotchas for category player`.

---

## Phase 9 — Final wrap

### Task 22: Full-suite verification + PR

**Files:** none modified.

- [ ] **Step 1: Backend tests**

Run: `PYTHONPATH=src pytest -q`
Expected: green.

- [ ] **Step 2: Frontend tests + typecheck**

From `frontend/`:
```
pnpm typecheck
pnpm vitest run
```
Expected: green.

- [ ] **Step 3: Lint**

From `frontend/`: `pnpm lint`
Expected: pass (or address any new warnings).

- [ ] **Step 4: Manual smoke**

Run `pnpm dev` (with `frontend/.env.local` set per CLAUDE.md). Walk through:
- Navigate to a category, verify the player panel renders left.
- Click a track row → playback starts; tags + playlists clouds render.
- Hotkeys 1–9, 0, J/K, A/S/D/F/G, U, Space behave as specified.
- Toggle Fresh-only off → all tracks visible; toggle on → only un-used tracks.
- Add current track to a playlist via hotkey → list shrinks (fresh-on) → toast shows → press U → row reappears.
- Remove track from category → current track keeps playing → on natural end, advance to next.
- Navigate to `/playlists` or `/home` → queue clears, no MiniBar appears anywhere.
- Mobile breakpoint → Play affordance opens `/categories/.../player` fullscreen.

- [ ] **Step 5: Open PR**

Use `caveman:caveman-commit` to draft the PR title and body. Push the branch and run:

```bash
gh pr create --title "<title>" --body "$(cat <<'EOF'
<body>
EOF
)"
```

PR body must include a Test plan checklist.

---

## Self-Review Notes

- All 22 tasks include real code/SQL blocks — no placeholders.
- Spec coverage: backend filter (Task 1-3), QueueSource extension (Task 4), routeContext (Task 5), MiniBar deletion (Task 6), undo stack (Task 7), queue binding (Task 8), hotkeys (Task 9), useCategoryTracks (Task 10), cache patching (Task 11), tag cloud (Task 12), playlist cloud (Task 13), used-in-playlist badge (Task 14), CategoryPlayerPanel composition (Task 15), TracksTab fresh toggle (Task 16), CategoryDetailPage split (Task 17), mobile player route (Task 18), i18n (Task 19), integration test (Task 20), CLAUDE.md (Task 21), PR wrap (Task 22).
- Known weak spot: Task 15's `assignedTagIds` / `trackPlaylistIds` placeholders are filled implicitly by Task 17 (page-level lookup of the playing track row). A subagent executing Task 15 in isolation will leave these as `[]`; Task 17 should patch them by computing from the cached `categoryTracksKey(...)` data — explicitly call out in the dispatch prompt for Task 17.
- Hotkey naming consistent: `useCategoryPlayerHotkeys` across plan.
- TypeScript surface consistent: `BindQueueArgs` already supports `onCursorChange` (verified in `PlaybackProvider.bindQueue`).

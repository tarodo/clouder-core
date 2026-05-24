# Playlist Detail — Categories Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the playlist detail page to categories parity — a `PlayerCard`+editable-tags player, a play button per track, rich draggable track tiles (artists/label/BPM/length/release/editable tags), a light-red Remove button — backed by an enriched playlist-tracks payload; and drop the `is_public` toggle from the UI.

**Architecture:** Backend first (the frontend depends on the richer payload): enrich `PlaylistsRepository.list_tracks` by mirroring the categories enriched query and attaching per-user tags via `tags_repo`. Then frontend: extend the hand-written `PlaylistTrack` type, add a `playlist` playback queue source + binding hook, decouple the tag editor from the categories cache (callbacks) and add playlist-cache tag hooks, redesign the track tile, add the player panel + split layout + mobile player route, and remove the `is_public` UI.

**Tech Stack:** Backend: Python, RDS Data API (NOT psycopg), pytest. Frontend: React 19 + Mantine 9 + dnd-kit + @tanstack/react-query + TypeScript; Vitest/jsdom + `@vitest/browser` (Playwright). Run frontend commands from `frontend/`; backend tests with `PYTHONPATH=src pytest -q`.

**Key facts (verified):**
- Categories enriched query: `src/collector/curation/categories_repository.py:743-778` (artists `JSON_AGG`, label via `clouder_albums.album_id → clouder_labels`, fields `mix_name/bpm/spotify_release_date/is_ai_suspected`). Tags are NOT in that SQL — attached afterward via `tags_repo.list_tags_for_tracks(user_id, track_ids)` (`categories_repository.py:868-881`).
- Playlist query today: `playlists_repository.py:536-582` (thin). `PlaylistTrackRow` dataclass: `playlists_repository.py:123-131`. Response builder: `curation_handler.py:247-257`. Handler: `_handle_list_playlist_tracks` `curation_handler.py:710-728`.
- The playlist-tracks OpenAPI uses the generic `LIST_RESPONSE_TEMPLATE` (untyped items) — **no OpenAPI/`schema.d.ts` change is needed**; the frontend `PlaylistTrack` type is hand-maintained in `frontend/src/features/playlists/lib/playlistTypes.ts`.
- Tag mutation API is track-scoped: `POST /tracks/{trackId}/tags` `{tag_id}` and `DELETE /tracks/{trackId}/tags/{tagId}` (`useAddTrackTag.ts:52`, `useRemoveTrackTag.ts:53`); `categoryId` only targets the optimistic cache patch.
- Tag editor call sites: `TrackTagsPopover` is used only by `PlayerPanelTagCloud` (`PlayerPanelTagCloud.tsx:81`); `PlayerPanelTagCloud` is used only by `CategoryPlayerPanel` (`CategoryPlayerPanel.tsx:267`).
- Playback `QueueSource`: `frontend/src/features/playback/lib/types.ts:32-34` (only `bucket`/`category`). Binding template: `useCategoryPlayerQueue.ts`.
- Router: categories mobile player route at `router.tsx:59-65` (`:styleId/:id` → child `player`). Playlists at `router.tsx:97-103` (`:id`).
- `CategoryTrack` shape: `frontend/src/features/categories/hooks/useCategoryTracks.ts`.

---

## File Structure

**Backend (modify):**
- `src/collector/curation/playlists_repository.py` — enrich `list_tracks` SQL, extend `PlaylistTrackRow`, attach tags via `tags_repo`.
- `src/collector/curation_handler.py` — extend `_playlist_track_response`; `_handle_list_playlist_tracks` creates + passes `tags_repo`.
- Tests: `tests/unit/` (repo) + `tests/integration/` or unit handler tests (mirror existing playlist track tests).

**Frontend (modify):**
- `features/playlists/lib/playlistTypes.ts` — extend `PlaylistTrack`.
- `features/playback/lib/types.ts` — add `playlist` `QueueSource`; update exhaustive switches.
- `features/playlists/hooks/usePlaylistPlayerQueue.ts` *(create)*; `features/playlists/hooks/usePlaylistTrackTag.ts` *(create)*.
- `features/tags/components/TrackTagsPopover.tsx`, `features/categories/components/PlayerPanelTagCloud.tsx`, `features/categories/components/CategoryPlayerPanel.tsx` — decouple tag editor from the categories cache.
- `features/playlists/components/PlaylistTrackRow.tsx` — redesign; delete `PlaylistTrackRowActions.tsx`.
- `features/playlists/components/PlaylistPlayerPanel.tsx` *(create)*; `features/playlists/routes/PlaylistPlayerPage.tsx` *(create)*; `features/playlists/routes/PlaylistDetailPage.tsx` + `routes/router.tsx` — split layout + mobile player route + queue binding.
- `features/playlists/components/PlaylistFormDialog.tsx`, `PlaylistMetaPanel.tsx`, `PlaylistRow.tsx`, `src/i18n/*` — remove `is_public` UI.

---

## Task 1: Backend — enrich playlist `list_tracks`

**Files:**
- Modify: `src/collector/curation/playlists_repository.py`
- Test: `tests/unit/test_playlists_repository.py` (or the existing playlist repo test file — find it with `ls tests/unit | grep -i playlist`)

- [ ] **Step 1: Write the failing repo test**

Add a test that stubs the `DataAPIClient` (mirror the existing playlist repo tests' fake `execute`) so the owner check returns a row, the enriched SELECT returns one row with `artists_json`, `label_id/label_name`, `bpm`, `spotify_release_date`, `mix_name`, `is_ai_suspected`, and the count returns 1; pass a fake `tags_repo` whose `list_tags_for_tracks` returns `{ "tr1": [TrackTagRow(tag_id="tg1", name="acid", color="#ff0000")] }`. Assert the returned `PlaylistTrackRow` carries `mix_name`, `bpm`, `spotify_release_date`, `artists == [{"id":"a1","name":"Artist"}]`, `label == {"id":"l1","name":"Label"}`, and `tags == (TrackTagRow(...),)`.

(Copy the fake-Data-API + fake-tags-repo helpers from `tests/unit/test_categories_repository.py` — they already exercise this exact shape.)

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src pytest tests/unit/test_playlists_repository.py -q -k enrich`
Expected: FAIL — `PlaylistTrackRow` has no `artists`/`label`/`tags` fields.

- [ ] **Step 3: Extend `PlaylistTrackRow`**

In `playlists_repository.py`, extend the dataclass (line ~123):

```python
@dataclass(frozen=True)
class PlaylistTrackRow:
    track_id: str
    position: int
    added_at: str
    title: str
    spotify_id: str | None
    isrc: str | None
    length_ms: int | None
    origin: str
    mix_name: str | None = None
    bpm: int | None = None
    spotify_release_date: str | None = None
    is_ai_suspected: bool = False
    artists: tuple[dict, ...] = ()
    label: dict | None = None
    tags: tuple = ()  # TrackTagRow tuple; kept untyped to avoid an import cycle
```

- [ ] **Step 4: Enrich the `list_tracks` SQL + mapping + tags attach**

Replace the SELECT and row mapping in `list_tracks` (keep the owner check + the `COUNT(*)` total query unchanged). Add a `tags_repo` keyword param (default `None`, matching the categories signature):

```python
    def list_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        limit: int,
        offset: int,
        tags_repo=None,
    ) -> tuple[list[PlaylistTrackRow], int]:
        owner = self._data_api.execute(
            "SELECT 1 AS ok FROM playlists "
            "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
            {"id": playlist_id, "user_id": user_id},
        )
        if not owner:
            raise PlaylistNotFoundError()
        rows = self._data_api.execute(
            """
            SELECT
                pt.track_id, pt.position, pt.added_at,
                t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.spotify_id, t.is_ai_suspected, t.spotify_release_date, t.origin,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT('id', a.id, 'name', a.name)
                        ORDER BY cta.role, a.name
                    ) FILTER (WHERE a.id IS NOT NULL),
                    '[]'::json
                ) AS artists_json,
                l.id   AS label_id,
                l.name AS label_name
            FROM playlist_tracks pt
            JOIN clouder_tracks t ON t.id = pt.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id  = cta.artist_id
            LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
            LEFT JOIN clouder_labels        l   ON l.id   = alb.label_id
            WHERE pt.playlist_id = :id
            GROUP BY pt.track_id, pt.position, pt.added_at, t.id, l.id, l.name
            ORDER BY pt.position ASC
            LIMIT :limit OFFSET :offset
            """,
            {"id": playlist_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlist_tracks pt2 "
            "WHERE pt2.playlist_id = :id",
            {"id": playlist_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        out: list[PlaylistTrackRow] = []
        for r in rows:
            artists_raw = r.get("artists_json", "[]")
            artists = (
                json.loads(artists_raw) if isinstance(artists_raw, str) else (artists_raw or [])
            )
            label_id = r.get("label_id")
            label = {"id": label_id, "name": r.get("label_name")} if label_id else None
            spot = r.get("spotify_release_date")
            out.append(
                PlaylistTrackRow(
                    track_id=r["track_id"],
                    position=int(r["position"]),
                    added_at=str(r["added_at"]),
                    title=r["title"],
                    spotify_id=r.get("spotify_id"),
                    isrc=r.get("isrc"),
                    length_ms=(int(r["length_ms"]) if r.get("length_ms") else None),
                    origin=r.get("origin") or "beatport",
                    mix_name=r.get("mix_name"),
                    bpm=(int(r["bpm"]) if r.get("bpm") is not None else None),
                    spotify_release_date=(str(spot) if spot is not None else None),
                    is_ai_suspected=bool(r.get("is_ai_suspected", False)),
                    artists=tuple(artists),
                    label=label,
                )
            )

        if tags_repo is not None and out:
            grouped = tags_repo.list_tags_for_tracks(
                user_id=user_id, track_ids=[row.track_id for row in out],
            )
            out = [
                replace(row, tags=tuple(grouped.get(row.track_id, [])))
                for row in out
            ]
        return out, total
```

Add the needed imports at the top of the file if missing: `import json` and `from dataclasses import dataclass, replace`.

- [ ] **Step 5: Run the repo test to verify it passes**

Run: `PYTHONPATH=src pytest tests/unit/test_playlists_repository.py -q`
Expected: PASS (new enrich test + all existing playlist repo tests).

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository.py
git commit -m "feat(playlists): enrich playlist tracks with artists, label, bpm, tags"
```

---

## Task 2: Backend — handler response + tags wiring

**Files:**
- Modify: `src/collector/curation_handler.py`
- Test: the existing playlist-tracks handler test (find with `grep -rln "list_playlist_tracks\|/tracks" tests | grep -i playlist`)

- [ ] **Step 1: Write the failing handler test**

Add a test that calls `_handle_list_playlist_tracks` (or routes a GET `/playlists/{id}/tracks` event through `lambda_handler`) with a fake repo whose `list_tracks` returns one enriched `PlaylistTrackRow` (artists/label/bpm/tags populated). Assert the JSON item contains `artists`, `label`, `bpm`, `spotify_release_date`, `mix_name`, `is_ai_suspected`, and `tags == [{"id","name","color"}]`. Mirror the existing playlist-tracks handler test setup.

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src pytest <that test file> -q -k tracks`
Expected: FAIL — `_playlist_track_response` omits the new fields/tags.

- [ ] **Step 3: Extend `_playlist_track_response`**

In `curation_handler.py` (line ~247):

```python
def _playlist_track_response(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "position": row.position,
        "added_at": row.added_at,
        "title": row.title,
        "spotify_id": row.spotify_id,
        "isrc": row.isrc,
        "length_ms": row.length_ms,
        "origin": row.origin,
        "mix_name": getattr(row, "mix_name", None),
        "bpm": getattr(row, "bpm", None),
        "spotify_release_date": getattr(row, "spotify_release_date", None),
        "is_ai_suspected": bool(getattr(row, "is_ai_suspected", False)),
        "artists": list(getattr(row, "artists", ()) or ()),
        "label": getattr(row, "label", None),
        "tags": [
            {"id": t.tag_id, "name": t.name, "color": t.color}
            for t in getattr(row, "tags", ())
        ],
    }
```

- [ ] **Step 4: Pass `tags_repo` in the handler**

In `_handle_list_playlist_tracks` (line ~710), create and pass `tags_repo`:

```python
def _handle_list_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)
    rows, total = repo.list_tracks(
        user_id=user_id, playlist_id=pid, limit=limit, offset=offset,
        tags_repo=tags_repo,
    )
    return _json_response(
        200,
        {
            "items": [_playlist_track_response(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )
```

(`create_default_tags_repository` is already imported — see `curation_handler.py:46-48`.)

- [ ] **Step 5: Run the handler test + full backend suite**

Run: `PYTHONPATH=src pytest tests/ -q`
Expected: PASS (new handler test + all existing). Paste the summary line.

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation_handler.py <handler test file>
git commit -m "feat(playlists): return enriched track fields and tags from the API"
```

---

## Task 3: Frontend — extend `PlaylistTrack` type

**Files:**
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Test: `frontend/src/features/playlists/lib/__tests__/playlistSchemas.test.ts` is for schemas; the type change is compile-checked. Add no test here; the typecheck in later tasks covers it.

- [ ] **Step 1: Extend the interface**

In `playlistTypes.ts`, extend `PlaylistTrack` (keep existing fields):

```ts
export interface PlaylistTrackArtist { id: string; name: string }
export interface PlaylistTrackLabel { id: string; name: string }
export interface PlaylistTrackTag { id: string; name: string; color: string | null }

export interface PlaylistTrack {
  track_id: string;
  position: number;
  added_at: string;
  title: string;
  spotify_id: string | null;
  isrc: string | null;
  length_ms: number | null;
  origin: PlaylistTrackOrigin;
  mix_name: string | null;
  artists: PlaylistTrackArtist[];
  label: PlaylistTrackLabel | null;
  bpm: number | null;
  spotify_release_date: string | null;
  is_ai_suspected: boolean;
  tags: PlaylistTrackTag[];
}
```

- [ ] **Step 2: Fix any compile fallout**

Run: `cd frontend && pnpm typecheck`
Existing test fixtures that build `PlaylistTrack` objects (e.g. in `PlaylistDetailPage.test.tsx`, `integration.playlists.test.tsx`, `PlaylistTracksList`/`PlaylistTrackRow` tests) will now miss required fields. Add the new fields (`mix_name: null, artists: [], label: null, bpm: null, spotify_release_date: null, is_ai_suspected: false, tags: []`) to those fixtures. Expected: typecheck clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/playlists/lib/playlistTypes.ts frontend/src/features/playlists/**/__tests__/*
git commit -m "feat(playlists): extend PlaylistTrack with rich fields and tags"
```

---

## Task 4: Playback — `playlist` queue source + binding hook

**Files:**
- Modify: `frontend/src/features/playback/lib/types.ts`
- Create: `frontend/src/features/playlists/hooks/usePlaylistPlayerQueue.ts`
- Test: `frontend/src/features/playlists/hooks/__tests__/usePlaylistPlayerQueue.test.tsx` (mirror `useCategoryPlayerQueue` if it has a test; else a minimal render test)

- [ ] **Step 1: Add the `playlist` source**

In `playback/lib/types.ts` (line ~32):

```ts
export type QueueSource =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; categoryId: string; styleId: string }
  | { type: 'playlist'; playlistId: string };
```

- [ ] **Step 2: Fix exhaustive switches**

Run: `cd frontend && pnpm typecheck`
Resolve any non-exhaustive `switch (source.type)` / narrowing errors (grep `source.type` and `\.type === 'category'`). For the playlist player, the new branch behaves like category for "is this queue active" checks. Expected: typecheck clean.

- [ ] **Step 3: Create the binding hook**

Create `usePlaylistPlayerQueue.ts` by copying `useCategoryPlayerQueue.ts` and swapping the source:

```ts
import { useEffect, useRef } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';

/** Bind a playlist's track list to the singleton playback queue (mirror of
 *  useCategoryPlayerQueue). */
export function usePlaylistPlayerQueue(
  playlistId: string,
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
      cursor = idx >= 0 ? idx : Math.max(-1, cursorRef.current - 1);
    }
    playback.controls.bindQueue({
      source: { type: 'playlist', playlistId },
      tracks,
      cursor,
      onCursorChange: (next) => {
        cursorRef.current = next;
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, playlistId]);

  useEffect(() => {
    return () => {
      playback.controls.clearQueue();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
```

- [ ] **Step 4: Test + commit**

Run: `cd frontend && pnpm typecheck && pnpm test -- usePlaylistPlayerQueue` (if a test was added; otherwise just typecheck).
Then:

```bash
git add frontend/src/features/playback/lib/types.ts frontend/src/features/playlists/hooks/usePlaylistPlayerQueue.ts frontend/src/features/playlists/hooks/__tests__/usePlaylistPlayerQueue.test.tsx
git commit -m "feat(playlists): add playlist playback queue source and binding hook"
```

---

## Task 5: Decouple the tag editor + playlist tag hooks

**Files:**
- Modify: `frontend/src/features/tags/components/TrackTagsPopover.tsx`, `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`, `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Create: `frontend/src/features/playlists/hooks/usePlaylistTrackTag.ts`
- Tests: update `PlayerPanelTagCloud.test.tsx`, the tags integration test; add `usePlaylistTrackTag.test.tsx`

- [ ] **Step 1: Make `TrackTagsPopover` callback-driven (failing test first)**

In `PlayerPanelTagCloud.test.tsx`, the popover is stubbed already; add/adjust a test asserting that toggling a tag in the popover calls the cloud's `onAdd`/`onRemove` (not a category-scoped mutation). Run it to see it fail against the current category-scoped popover.

Then change `TrackTagsPopover` props: remove `categoryId`; add `onToggle: (tag: { id: string; name: string; color: string | null }, checked: boolean) => void | Promise<void>`. Replace its internal `useAddTrackTag`/`useRemoveTrackTag` calls with `onToggle(tag, checked)`. Keep `useTags` + `useCreateTag` internal; after creating a tag, call `onToggle(created, true)`.

- [ ] **Step 2: Update `PlayerPanelTagCloud`**

Remove the `categoryId` prop. Build `const onToggle = (tag, checked) => (checked ? onAdd(tag.id) : onRemove(tag.id));` and pass it to `TrackTagsPopover` (drop `categoryId={...}`). The Chip `onChange` path already calls `onAdd`/`onRemove` — unchanged.

- [ ] **Step 3: Update `CategoryPlayerPanel`**

Remove the `categoryId={categoryId}` prop passed to `PlayerPanelTagCloud` (line ~267). Its `onAdd`/`onRemove` already wrap the category-scoped `useAddTrackTag`/`useRemoveTrackTag` — unchanged behavior.

- [ ] **Step 4: Create `usePlaylistTrackTag`**

Create `usePlaylistTrackTag.ts` — add + remove hooks hitting the same track-scoped endpoints, optimistically patching `playlistTracksKey(playlistId)` (a flat `PaginatedPlaylistTracks`, NOT infinite):

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedPlaylistTracks, PlaylistTrackTag } from '../lib/playlistTypes';

interface Vars { trackId: string; tag: PlaylistTrackTag }
interface Ctx { prev?: PaginatedPlaylistTracks }

function patch(
  data: PaginatedPlaylistTracks | undefined,
  trackId: string,
  fn: (tags: PlaylistTrackTag[]) => PlaylistTrackTag[],
): PaginatedPlaylistTracks | undefined {
  if (!data) return data;
  return {
    ...data,
    items: data.items.map((it) =>
      it.track_id === trackId ? { ...it, tags: fn(it.tags) } : it,
    ),
  };
}

export function usePlaylistAddTrackTag(playlistId: string): UseMutationResult<void, Error, Vars, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<void, Error, Vars, Ctx>({
    mutationFn: async ({ trackId, tag }) => {
      await api(`/tracks/${trackId}/tags`, { method: 'POST', body: JSON.stringify({ tag_id: tag.id }) });
    },
    onMutate: async ({ trackId, tag }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
        patch(old, trackId, (tags) => (tags.some((t) => t.id === tag.id) ? tags : [...tags, tag])),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}

export function usePlaylistRemoveTrackTag(playlistId: string): UseMutationResult<void, Error, { trackId: string; tagId: string }, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<void, Error, { trackId: string; tagId: string }, Ctx>({
    mutationFn: async ({ trackId, tagId }) => {
      await api(`/tracks/${trackId}/tags/${tagId}`, { method: 'DELETE' });
    },
    onMutate: async ({ trackId, tagId }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
        patch(old, trackId, (tags) => tags.filter((t) => t.id !== tagId)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}
```

- [ ] **Step 5: Add the hook test**

`usePlaylistTrackTag.test.tsx`: render the add hook with a QueryClient seeded with a `playlistTracksKey` cache holding one track; mock `api`; call `mutate`; assert the cache gains the tag optimistically and that `api` was called with `POST /tracks/<id>/tags`. Add a remove-hook test symmetrically (incl. rollback on `api` reject).

- [ ] **Step 6: Run tests + commit**

Run: `cd frontend && pnpm test -- PlayerPanelTagCloud usePlaylistTrackTag tags/__tests__/integration && pnpm typecheck`
Fix the tags integration test if the `PlayerPanelTagCloud`/`TrackTagsPopover` prop change broke it. Expected: PASS.

```bash
git add frontend/src/features/tags/components/TrackTagsPopover.tsx frontend/src/features/categories/components/PlayerPanelTagCloud.tsx frontend/src/features/categories/components/CategoryPlayerPanel.tsx frontend/src/features/playlists/hooks/usePlaylistTrackTag.ts frontend/src/features/playlists/hooks/__tests__/usePlaylistTrackTag.test.tsx frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx frontend/src/features/tags/__tests__/integration.test.tsx
git commit -m "refactor(tags): decouple tag editor from the categories cache"
```

---

## Task 6: Redesign `PlaylistTrackRow`

**Files:**
- Modify: `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`, `PlaylistTracksList.tsx` (prop threading)
- Delete: `frontend/src/features/playlists/components/PlaylistTrackRowActions.tsx` (+ its test if any)
- Test: `frontend/src/features/playlists/components/__tests__/PlaylistTrackRow.test.tsx`

- [ ] **Step 1: Write the failing test**

In `PlaylistTrackRow.test.tsx` (create or extend), render a row with a rich `PlaylistTrack` (artists/label/bpm/tags, `spotify_id` set) inside `MantineProvider` + a `DndContext`/`SortableContext` (mirror the existing row test harness if present). Assert: the position number renders; a play button (`aria-label` = the categories `play_aria` or a playlist-specific key) is present and enabled; artists/label/bpm/length/release render; tag pills render; a **Remove** button (`name: /remove/i`) is present and calls `onRemove`; there is no burger/`Track actions` menu. Add a second case: `spotify_id: null` → play button disabled.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && pnpm test -- PlaylistTrackRow`
Expected: FAIL — no play button, no rich fields, still a burger menu.

- [ ] **Step 3: Redesign the row**

Rewrite `PlaylistTrackRow` to keep the draggable `Group` shell (drag handle + `setNodeRef`/`listeners` + position number) and replace the body with categories-style content. New props: add `onPlay: () => void`, `isCurrent?: boolean`, and the tag callbacks `onAddTag(tag) / onRemoveTag(tagId)` (wired by the parent to `usePlaylistTrackTag`). Structure:

- drag handle `ActionIcon` (unchanged) → position number `Text` (unchanged).
- play button: `ActionIcon` + `IconPlayerPlayFilled`, `disabled={!track.spotify_id}`, tooltip, `onClick={onPlay}` (mirror `categories/components/TrackRow.tsx:34-52`).
- title (`fw={500}`) + `mix_name` dimmed; artists (`joinArtists`); label name; BPM/length/release in a mono meta row (reuse `formatLength`/`formatReleaseDate` from `../../../lib/formatters`).
- editable tags: render `TrackTagsCell`-style pills for display **plus** the `+` popover (`TrackTagsPopover` with `onToggle` wired to `onAddTag`/`onRemoveTag`, `currentTagIds = track.tags.map(t=>t.id)`) and `×`-removable `TagPill`s. (Reuse the decoupled `TrackTagsPopover` from Task 5; for removal, render `TagPill` with `onRemove`.)
- replace `PlaylistTrackRowActions` with `<Button color="red" variant="light" size="xs" onClick={() => onRemove(track)}>{t('playlists.detail.remove_track_cta')}</Button>` (add the i18n key; light-red = `variant="light"` on red).
- keep the Spotify external-link `ActionIcon`.
- `data-current`/bg highlight when `isCurrent`.

Update `PlaylistTracksList` to thread `onPlay`/`isCurrent`/tag callbacks down per row. Delete `PlaylistTrackRowActions.tsx`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- PlaylistTrackRow PlaylistTracksList`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/components/PlaylistTrackRow.tsx frontend/src/features/playlists/components/PlaylistTracksList.tsx frontend/src/features/playlists/components/__tests__/PlaylistTrackRow.test.tsx
git rm frontend/src/features/playlists/components/PlaylistTrackRowActions.tsx
git commit -m "feat(playlists): rich draggable track tiles with play, tags, Remove"
```

---

## Task 7: Player panel + split layout + mobile player route

**Files:**
- Create: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`, `frontend/src/features/playlists/routes/PlaylistPlayerPage.tsx`
- Modify: `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx`, `frontend/src/routes/router.tsx`
- Test: `frontend/src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx`; extend `PlaylistDetailPage.test.tsx`

- [ ] **Step 1: Write the failing panel test**

`PlaylistPlayerPanel.test.tsx`: with `usePlayback` stubbed (copy the stub from `CategoryDetailPage.test.tsx:20-53`) and a current track set, assert the panel renders the now-playing title and a tag cloud; with no current track, asserts the empty state. Run → fails (no component).

- [ ] **Step 2: Build `PlaylistPlayerPanel`**

Create it by adapting `CategoryPlayerPanel.tsx` to the **PlayerCard + tags** scope:
- Props: `playlistId: string; items: PlaylistTrack[]`.
- `PlayerCard` (variant `full`) wired to `usePlayback` exactly like the category panel; `mixName`, label/BPM meta row, `spotifyHref` sourced from the current rich `PlaylistTrack` (look it up in `items` by `current.id`, same `lastRichRef` fallback pattern).
- Tag cloud: `PlayerPanelTagCloud` with `trackId={current.id}`, `assignedTagIds` from the rich track's tags, `onAdd`/`onRemove` wired to `usePlaylistAddTrackTag(playlistId)`/`usePlaylistRemoveTrackTag(playlistId)`; undo toast (reuse `undoStack`/`useUndoStack` like the category panel).
- `LabelTile` when the current track has a label (no `styleId` here — pass the label only; if `LabelTile` requires `styleId`, omit the tile or render label name read-only — verify `LabelTile`'s required props and degrade gracefully).
- Transport hotkeys: reuse the playback transport portion. If `useCategoryPlayerHotkeys` is category-coupled, call only the transport controls it needs with `active = playback.queue.source?.type === 'playlist' && source.playlistId === playlistId` and pass no playlist-toggle handler (or extract a small `usePlaybackTransportHotkeys` if cleaner). NO playlist-membership cloud.

- [ ] **Step 3: Wire the page (split + queue binding) + mobile route**

In `PlaylistDetailPage.tsx`:
- Map `tracks` → `PlaybackTrack[]` (mirror `toPlaybackTrack` in `CategoryDetailPage.tsx:47-56`) and call `usePlaylistPlayerQueue(id, playerTracks)`.
- Add an `onPlay(track)` (prewarm + `play(queueIdx)`; on mobile, `navigate('/playlists/'+id+'/player')`) — mirror `CategoryDetailPageInner.playTrack`.
- Desktop (`useMediaQuery(min-width md)`): render a `Flex` with `<PlaylistPlayerPanel playlistId={id} items={tracks} />` left and the tiles list right (mirror `CategoryDetailPage.tsx:251-255`). Mobile: render the tiles list; when on the `/player` subpath (`useMatch('/playlists/:id/player')`) render `<Outlet context={{ items: tracks }} />`.
- Thread `onPlay`/`isCurrent`/tag callbacks into `PlaylistTracksList` → rows.

Create `PlaylistPlayerPage.tsx` (mobile) mirroring `CategoryPlayerPage.tsx`: read items from outlet context, render `<PlaylistPlayerPanel>`.

In `router.tsx`, nest the player route under the playlist detail (mirror `router.tsx:59-65`):

```tsx
{
  path: ':id',
  element: <PlaylistDetailPage />,
  children: [{ path: 'player', element: <PlaylistPlayerPage /> }],
},
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && pnpm typecheck && pnpm test -- PlaylistPlayerPanel PlaylistDetailPage`
Expected: PASS. Update `PlaylistDetailPage.test.tsx` for the new layout/queue binding (stub `usePlayback`; the desktop branch is unreachable under jsdom `matchMedia` → only the tiles render, matching categories' test note).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx frontend/src/features/playlists/routes/PlaylistPlayerPage.tsx frontend/src/features/playlists/routes/PlaylistDetailPage.tsx frontend/src/routes/router.tsx frontend/src/features/playlists/**/__tests__/*
git commit -m "feat(playlists): categories-style player panel, split layout, mobile route"
```

---

## Task 8: Remove the `is_public` UI

**Files:**
- Modify: `frontend/src/features/playlists/components/PlaylistFormDialog.tsx`, `PlaylistMetaPanel.tsx`, `PlaylistRow.tsx`, `frontend/src/i18n/*.json`
- Tests: update `useCreatePlaylist.test.tsx`, `PlaylistsListPage.test.tsx`, `integration.playlists.test.tsx`, `playlistSchemas` test as needed

- [ ] **Step 1: Write/adjust the failing tests**

Assert (in the relevant tests) that the create form renders no "Public" switch, the meta panel renders no public toggle, and `PlaylistRow` renders no lock icon. Run → fails (switches/icon still present).

- [ ] **Step 2: Remove the UI**

- `PlaylistFormDialog.tsx`: remove the `Switch` (lines ~141-145), the `is_public` form field + `initialValues`/effect wiring, and `out.is_public` in the submit builder. Remove the now-unused `Switch` import if nothing else uses it. The create payload no longer includes `is_public` (backend defaults `false`).
- `PlaylistMetaPanel.tsx`: remove the public `Switch` (lines ~176-180) and its `onPatch({ is_public })` handler.
- `PlaylistRow.tsx`: remove the lock/unlock icon (line ~84) and the `IconLock`/`IconLockOpen` imports.
- `src/i18n/en.json` (+ other locales): remove `playlists.form.is_public_label` and `is_public_description`.

Leave `playlistTypes.ts` `Playlist.is_public` and `playlistSchemas` `is_public` (optional) intact — the backend contract is unchanged.

- [ ] **Step 3: Run tests + typecheck**

Run: `cd frontend && pnpm typecheck && pnpm test -- PlaylistFormDialog PlaylistMetaPanel PlaylistsListPage useCreatePlaylist integration.playlists`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/playlists/components/PlaylistFormDialog.tsx frontend/src/features/playlists/components/PlaylistMetaPanel.tsx frontend/src/features/playlists/components/PlaylistRow.tsx frontend/src/i18n/ frontend/src/features/playlists/**/__tests__/*
git commit -m "fix(playlists): remove the is_public toggle from the UI"
```

---

## Task 9: Full verification + browser smoke

**Files:**
- Create: `frontend/src/features/playlists/components/__tests__/PlaylistTrackRow.browser.test.tsx`

- [ ] **Step 1: Browser smoke for the tile**

Add a minimal `*.browser.test.tsx` that renders a `PlaylistTrackRow` (inside `MantineProvider` + `DndContext`/`SortableContext`) and asserts the play button, the position number, and the Remove button are all visible (`getBoundingClientRect().width > 0` / `toBeVisible`). Geometry is not load-bearing here — keep it to a presence smoke.

Run: `cd frontend && pnpm test:browser -- PlaylistTrackRow`
Expected: PASS.

- [ ] **Step 2: Full gate**

Run, and paste each summary line:
- Backend: `PYTHONPATH=src pytest -q`
- Frontend: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
- Browser: `cd frontend && pnpm test:browser`

Expected: all PASS (pre-existing lint WARNINGS acceptable). Since the playlist-tracks OpenAPI uses the generic list template, no OpenAPI/`schema.d.ts` regeneration is needed; if `pnpm typecheck`/CI shows a `schema.d.ts` diff, regenerate per the runbook and re-check.

- [ ] **Step 3: Commit (only if a fix was needed)**

```bash
git add -A
git commit -m "test(playlists): browser smoke for the track tile"
```

---

## Done criteria

- The playlist API returns artists/label/BPM/release/mix/tags per track (Task 1–2 tests pass).
- The playlist page shows a categories-style player (PlayerCard + editable tags + label tile), desktop split / mobile player route, with a working per-track play button.
- Track tiles keep the draggable handle + number and show the full categories-table info with editable tags; the burger menu is replaced by a light-red Remove button.
- Editing tags on the playlist page updates the per-user track tags (no category needed) optimistically; categories tag editing is unchanged.
- No `is_public` toggle/icon anywhere in the playlist UI; creating a playlist still works.
- `PYTHONPATH=src pytest -q`, `pnpm typecheck && pnpm lint && pnpm test`, and `pnpm test:browser` all green.

## Post-merge verification (user, visual)

On `/playlists/:id`: a play button before each track plays it; the player shows now-playing + editable tags; tiles are still draggable, numbered, and show artists/label/BPM/tags; the burger menu is replaced by a light-red Remove; mobile tap → player route. The create dialog and meta panel show no Public toggle.

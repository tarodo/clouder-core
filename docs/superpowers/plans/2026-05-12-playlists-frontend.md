# Playlists Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a fully functional Playlists section on the CLOUDER SPA (list view, detail view with cover/tracks/publish, cross-feature add-to-playlist from categories, Spotify track import, publish to Spotify with confirm-overwrite) wired against the 14 backend routes already live on the curation Lambda.

**Architecture:** Feature folder `frontend/src/features/playlists/` (routes / components / hooks / lib + tests), following the F1 categories pattern. TanStack Query 5 owns server state with three keyspaces (`playlistsKey`, `playlistDetailKey`, `playlistTracksKey`); optimistic for reversible ops, pessimistic for delete/publish/cover. dnd-kit reorder mirrors `CategoriesList`. One cross-feature touchpoint: extend `TrackRowActions` Menu with an `Add to playlist ▶` submenu.

**Tech Stack:** React 19, Mantine 9 (`@mantine/core`, `@mantine/form`, `@mantine/modals`, `@mantine/notifications`, `@mantine/hooks`), react-router 7, TanStack Query 5, `@dnd-kit/core` + `@dnd-kit/sortable`, zod 3 + `mantine-form-zod-resolver`, react-i18next 15, Vitest + MSW + jsdom for tests.

**Spec:** [`2026-05-12-playlists-frontend-design.md`](../specs/2026-05-12-playlists-frontend-design.md).

**Branch:** `feat/playlists-frontend` (already created from `origin/main`).

---

## File Inventory

### Create

```
frontend/src/features/playlists/
├── index.ts
├── routes/
│   ├── PlaylistsListPage.tsx
│   ├── PlaylistDetailPage.tsx
│   └── __tests__/
│       ├── PlaylistsListPage.test.tsx
│       └── PlaylistDetailPage.test.tsx
├── components/
│   ├── PlaylistsTable.tsx
│   ├── PlaylistRow.tsx
│   ├── PlaylistFormDialog.tsx
│   ├── PlaylistMetaPanel.tsx
│   ├── PlaylistTracksList.tsx
│   ├── PlaylistTrackRow.tsx
│   ├── PlaylistTrackRowActions.tsx
│   ├── CoverPicker.tsx
│   ├── PublishButton.tsx
│   ├── PublishConfirmModal.tsx
│   ├── PublishResultModal.tsx
│   ├── ImportSpotifyModal.tsx
│   ├── AddTracksModal.tsx
│   ├── DriftBadge.tsx
│   ├── OriginBadge.tsx
│   └── __tests__/
│       ├── PlaylistRow.test.tsx
│       ├── DriftBadge.test.tsx
│       ├── OriginBadge.test.tsx
│       ├── CoverPicker.test.tsx
│       ├── PublishButton.test.tsx
│       ├── ImportSpotifyModal.test.tsx
│       └── AddTracksModal.test.tsx
├── hooks/
│   ├── usePlaylists.ts
│   ├── usePlaylistDetail.ts
│   ├── usePlaylistTracks.ts
│   ├── useCreatePlaylist.ts
│   ├── usePatchPlaylist.ts
│   ├── useDeletePlaylist.ts
│   ├── useAddTracksToPlaylist.ts
│   ├── useRemoveTrackFromPlaylist.ts
│   ├── useReorderPlaylistTracks.ts
│   ├── useImportSpotifyTracks.ts
│   ├── usePublishPlaylist.ts
│   ├── useUploadCover.ts
│   ├── useClearCover.ts
│   └── __tests__/
│       ├── useCreatePlaylist.test.ts
│       ├── useReorderPlaylistTracks.test.ts
│       ├── useUploadCover.test.ts
│       └── usePublishPlaylist.test.ts
└── lib/
    ├── playlistTypes.ts
    ├── playlistSchemas.ts
    ├── spotifyRefParse.ts
    ├── queryKeys.ts
    └── __tests__/
        └── spotifyRefParse.test.ts
```

Cross-feature additions:

```
frontend/src/features/categories/components/AddToPlaylistSubmenu.tsx
frontend/src/features/categories/components/__tests__/AddToPlaylistSubmenu.test.tsx
```

### Modify

- `frontend/src/routes/router.tsx` — register `/playlists` + `/playlists/:id` under the authenticated `AppShellLayout`.
- `frontend/src/routes/_layout.tsx` — add `Playlists` to `NAV_ITEMS`.
- `frontend/src/components/icons.ts` — add `IconPlaylist` export (or pick `IconPlaylist` from `@tabler/icons-react` directly if not centralised).
- `frontend/src/i18n/en.json` — add the `playlists.*` namespace + extend `appshell` + `categories.row_actions`.
- `frontend/src/features/categories/components/TrackRowActions.tsx` — render the new `AddToPlaylistSubmenu` inside the existing Menu.
- `frontend/src/test/handlers.ts` — extend MSW handlers with the 14 playlist routes for global default coverage.

### Out of scope

Anything not listed in the spec's "Out of scope (YAGNI)" section stays untouched.

---

## Conventions for every task

- **Test runner:** `pnpm -C frontend test` runs the suite (Vitest). For one file: `pnpm -C frontend test -- src/features/playlists/lib/__tests__/spotifyRefParse.test.ts`.
- **Typecheck:** `pnpm -C frontend typecheck` after substantial edits.
- **Lint:** `pnpm -C frontend lint` before commits.
- **Commits:** Conventional Commits, generated via the `caveman:caveman-commit` skill. Multi-line commits use `git commit -m "$(cat <<'EOF' ... EOF)"`. Subject prefix must be `feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert` (PreToolUse hook blocks otherwise).
- **No emojis** in code, comments, or commits.
- **MSW URLs** in tests use `http://localhost/...` (jsdom default origin).
- **All hooks pass `enabled` correctly** so they do not fire during SSR-style mounts.
- **Always** clean up sortable IDs in `useMemo` to keep stable dnd-kit identity (`ids = useMemo(() => tracks.map(t => t.track_id), [tracks])`).
- **Toast helper:** mirror `frontend/src/features/categories/components/TrackRowActions.tsx`'s `fireUndoToast` for any undoable action.

---

## Task 1: Types + query keys + zod schemas

**Files:**
- Create: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Create: `frontend/src/features/playlists/lib/queryKeys.ts`
- Create: `frontend/src/features/playlists/lib/playlistSchemas.ts`

This task establishes the type vocabulary used by every later task. No React, no DOM — pure TypeScript.

- [ ] **Step 1: Create `playlistTypes.ts` with the full interface surface**

```ts
// frontend/src/features/playlists/lib/playlistTypes.ts

export type PlaylistTrackOrigin = 'beatport' | 'spotify';

export interface Playlist {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  cover_s3_key: string | null;
  cover_url: string | null;
  cover_uploaded_at: string | null;
  spotify_playlist_id: string | null;
  last_published_at: string | null;
  needs_republish: boolean;
  track_count: number;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrack {
  track_id: string;
  position: number;
  added_at: string;
  title: string;
  spotify_id: string | null;
  isrc: string | null;
  length_ms: number | null;
  origin: PlaylistTrackOrigin;
}

export interface PaginatedPlaylists {
  items: Playlist[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export interface PaginatedPlaylistTracks {
  items: PlaylistTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export interface AddTracksResult {
  added: string[];
  skipped_duplicates: string[];
  position_after: number;
  correlation_id?: string;
}

export interface ImportSpotifyResult {
  added: { track_id: string; spotify_id: string; title: string }[];
  skipped: { ref: string; reason: 'invalid_ref' | 'not_found' | 'already_in_playlist' }[];
  position_after: number;
  correlation_id?: string;
}

export interface PublishResult {
  spotify_playlist_id: string;
  spotify_url: string;
  skipped_tracks: { track_id: string; title: string; reason: string }[];
  cover_failed: boolean;
  published_at: string;
  correlation_id?: string;
}

export interface CoverUploadUrlResponse {
  upload_url: string;
  s3_key: string;
  expires_in: number;
  correlation_id?: string;
}
```

- [ ] **Step 2: Create `queryKeys.ts`**

```ts
// frontend/src/features/playlists/lib/queryKeys.ts

export const playlistsKey = (search?: string | null) =>
  ['playlists', 'list', search ?? null] as const;

export const playlistDetailKey = (id: string) =>
  ['playlists', 'detail', id] as const;

export const playlistTracksKey = (id: string) =>
  ['playlists', 'tracks', id] as const;
```

- [ ] **Step 3: Write failing test for zod schemas**

```ts
// frontend/src/features/playlists/lib/__tests__/playlistSchemas.test.ts
import { describe, it, expect } from 'vitest';
import {
  playlistNameSchema,
  playlistDescriptionSchema,
  createPlaylistSchema,
} from '../playlistSchemas';

describe('playlistNameSchema', () => {
  it('accepts a 1-char name', () => {
    expect(playlistNameSchema.safeParse('a').success).toBe(true);
  });
  it('rejects empty string', () => {
    expect(playlistNameSchema.safeParse('').success).toBe(false);
  });
  it('rejects > 100 chars', () => {
    expect(playlistNameSchema.safeParse('x'.repeat(101)).success).toBe(false);
  });
  it('accepts exactly 100 chars', () => {
    expect(playlistNameSchema.safeParse('x'.repeat(100)).success).toBe(true);
  });
  it('rejects control characters', () => {
    expect(playlistNameSchema.safeParse('foo\x00bar').success).toBe(false);
  });
  it('trims whitespace', () => {
    const r = playlistNameSchema.safeParse('  hi  ');
    expect(r.success).toBe(true);
    if (r.success) expect(r.data).toBe('hi');
  });
});

describe('playlistDescriptionSchema', () => {
  it('accepts null', () => {
    expect(playlistDescriptionSchema.safeParse(null).success).toBe(true);
  });
  it('accepts empty string and normalises to null', () => {
    const r = playlistDescriptionSchema.safeParse('');
    expect(r.success).toBe(true);
    if (r.success) expect(r.data).toBeNull();
  });
  it('rejects > 300 chars', () => {
    expect(playlistDescriptionSchema.safeParse('x'.repeat(301)).success).toBe(false);
  });
});

describe('createPlaylistSchema', () => {
  it('defaults is_public to false', () => {
    const r = createPlaylistSchema.safeParse({ name: 'My' });
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.is_public).toBe(false);
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

```
pnpm -C frontend test -- src/features/playlists/lib/__tests__/playlistSchemas.test.ts
```

Expected: fail with `Cannot find module '../playlistSchemas'`.

- [ ] **Step 5: Implement `playlistSchemas.ts`**

```ts
// frontend/src/features/playlists/lib/playlistSchemas.ts
import { z } from 'zod';

// Matches ASCII C0 + DEL + C1 control bytes. eslint-disable
// because the regex existence is intentional.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const playlistNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(100, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const playlistDescriptionSchema = z
  .union([z.string().max(300, 'description_too_long'), z.null()])
  .transform((v) => (typeof v === 'string' && v.trim() === '' ? null : v));

export const createPlaylistSchema = z.object({
  name: playlistNameSchema,
  description: playlistDescriptionSchema.optional(),
  is_public: z.boolean().default(false),
});

export const patchPlaylistSchema = z
  .object({
    name: playlistNameSchema.optional(),
    description: playlistDescriptionSchema.optional(),
    is_public: z.boolean().optional(),
  })
  .refine(
    (v) => v.name !== undefined || v.description !== undefined || v.is_public !== undefined,
    { message: 'at_least_one_field' },
  );

export type CreatePlaylistInput = z.infer<typeof createPlaylistSchema>;
export type PatchPlaylistInput = z.infer<typeof patchPlaylistSchema>;
```

- [ ] **Step 6: Re-run the test, expect pass**

```
pnpm -C frontend test -- src/features/playlists/lib/__tests__/playlistSchemas.test.ts
```

Expected: PASS, 8/8.

- [ ] **Step 7: Commit**

```
git add frontend/src/features/playlists/lib/
git commit -m "feat(playlists): scaffold types, query keys, zod schemas"
```

---

## Task 2: `parseSpotifyRef` helper

Mirror of the backend `parse_spotify_ref` from `src/collector/curation/playlists_service.py:62`. Pure function.

**Files:**
- Create: `frontend/src/features/playlists/lib/spotifyRefParse.ts`
- Create: `frontend/src/features/playlists/lib/__tests__/spotifyRefParse.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/playlists/lib/__tests__/spotifyRefParse.test.ts
import { describe, it, expect } from 'vitest';
import { parseSpotifyRef, InvalidSpotifyRefError } from '../spotifyRefParse';

describe('parseSpotifyRef', () => {
  it('parses spotify:track URI', () => {
    expect(parseSpotifyRef('spotify:track:5PB5CTjuKcD2GUlIMtU1gr')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('parses open.spotify.com URL', () => {
    expect(parseSpotifyRef('https://open.spotify.com/track/5PB5CTjuKcD2GUlIMtU1gr')).toBe(
      '5PB5CTjuKcD2GUlIMtU1gr',
    );
  });
  it('parses URL with query string', () => {
    expect(
      parseSpotifyRef('https://open.spotify.com/track/5PB5CTjuKcD2GUlIMtU1gr?si=foo'),
    ).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('parses bare 22-char base62 id', () => {
    expect(parseSpotifyRef('5PB5CTjuKcD2GUlIMtU1gr')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('trims whitespace', () => {
    expect(parseSpotifyRef('  5PB5CTjuKcD2GUlIMtU1gr  ')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('rejects empty string', () => {
    expect(() => parseSpotifyRef('')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects playlist URL', () => {
    expect(() =>
      parseSpotifyRef('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'),
    ).toThrow(InvalidSpotifyRefError);
  });
  it('rejects too-short id', () => {
    expect(() => parseSpotifyRef('abc')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects non-base62 id', () => {
    expect(() => parseSpotifyRef('5PB5CTjuKcD2GUlIMtU1g!')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects album URI', () => {
    expect(() => parseSpotifyRef('spotify:album:5PB5CTjuKcD2GUlIMtU1gr')).toThrow(
      InvalidSpotifyRefError,
    );
  });
});
```

- [ ] **Step 2: Run failing test**

```
pnpm -C frontend test -- src/features/playlists/lib/__tests__/spotifyRefParse.test.ts
```

Expected: fail with "Cannot find module".

- [ ] **Step 3: Implement the parser**

```ts
// frontend/src/features/playlists/lib/spotifyRefParse.ts

export class InvalidSpotifyRefError extends Error {
  constructor(message = 'invalid_spotify_ref') {
    super(message);
    this.name = 'InvalidSpotifyRefError';
  }
}

const BASE62 = /^[0-9A-Za-z]{22}$/;
const URI_RE = /^spotify:track:([0-9A-Za-z]{22})$/;
const URL_RE = /^https?:\/\/open\.spotify\.com\/track\/([0-9A-Za-z]{22})(?:\?.*)?$/;

export function parseSpotifyRef(input: string): string {
  const ref = (input ?? '').trim();
  if (!ref) throw new InvalidSpotifyRefError();

  const uriMatch = URI_RE.exec(ref);
  if (uriMatch) return uriMatch[1];

  const urlMatch = URL_RE.exec(ref);
  if (urlMatch) return urlMatch[1];

  if (BASE62.test(ref)) return ref;

  throw new InvalidSpotifyRefError();
}
```

- [ ] **Step 4: Re-run, expect pass**

```
pnpm -C frontend test -- src/features/playlists/lib/__tests__/spotifyRefParse.test.ts
```

Expected: PASS, 10/10.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/playlists/lib/spotifyRefParse.ts frontend/src/features/playlists/lib/__tests__/spotifyRefParse.test.ts
git commit -m "feat(playlists): add spotifyRefParse client helper"
```

---

## Task 3: MSW handlers for the 14 routes

A single helper that registers default MSW handlers — used by every test. Keeps test files terse.

**Files:**
- Modify: `frontend/src/test/handlers.ts` — append minimal handlers (return empty/default shapes) so unhandled requests do not surface as errors when an unrelated test loads a query.

Note: per-test scenarios still call `server.use(...)` to override. This task only adds happy-default behaviour to prevent `onUnhandledRequest: 'error'` failures.

- [ ] **Step 1: Read current `handlers.ts`**

```
cat frontend/src/test/handlers.ts
```

Note the file uses `http.get('http://localhost/...')`.

- [ ] **Step 2: Append playlist defaults**

```ts
// frontend/src/test/handlers.ts — APPEND after existing handlers array
// Default-empty playlists handlers to avoid "unhandled request" errors when
// components on tested pages fire background queries. Tests that exercise
// real responses should call `server.use(...)` to override.
import { http, HttpResponse } from 'msw';

const PLAYLIST_DEFAULTS = [
  http.get('http://localhost/playlists', () =>
    HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
  ),
  http.get('http://localhost/playlists/:id', ({ params }) =>
    HttpResponse.json({ error_code: 'playlist_not_found', message: 'not found' }, { status: 404 }),
  ),
  http.get('http://localhost/playlists/:id/tracks', () =>
    HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
  ),
];

// Spread into the existing exported `handlers` array. Edit the existing
// `export const handlers = [...]` declaration to include `...PLAYLIST_DEFAULTS`.
```

Concretely, change `frontend/src/test/handlers.ts` from `export const handlers = [ ... ]` to `export const handlers = [ ..., ...PLAYLIST_DEFAULTS ]`.

- [ ] **Step 3: Run the full suite — expect no regressions**

```
pnpm -C frontend test -- --run
```

Expected: every previously passing test still passes (no compile errors, no unhandled-request errors).

- [ ] **Step 4: Commit**

```
git add frontend/src/test/handlers.ts
git commit -m "test(playlists): add default MSW handlers"
```

---

## Task 4: List query hook (`usePlaylists`)

**Files:**
- Create: `frontend/src/features/playlists/hooks/usePlaylists.ts`

- [ ] **Step 1: Create the hook**

```ts
// frontend/src/features/playlists/hooks/usePlaylists.ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylists } from '../lib/playlistTypes';
import { playlistsKey } from '../lib/queryKeys';

export interface UsePlaylistsOpts {
  search?: string;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function usePlaylists(
  opts: UsePlaylistsOpts = {},
): UseQueryResult<PaginatedPlaylists> {
  const { search, limit = 20, offset = 0, enabled = true } = opts;
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  if (search && search.trim()) params.set('search', search.trim());
  return useQuery({
    queryKey: playlistsKey(search?.trim() || null),
    queryFn: () => api<PaginatedPlaylists>(`/playlists?${params.toString()}`),
    enabled,
  });
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/hooks/usePlaylists.ts
git commit -m "feat(playlists): add usePlaylists query hook"
```

---

## Task 5: Detail + tracks query hooks

**Files:**
- Create: `frontend/src/features/playlists/hooks/usePlaylistDetail.ts`
- Create: `frontend/src/features/playlists/hooks/usePlaylistTracks.ts`

- [ ] **Step 1: Implement `usePlaylistDetail`**

```ts
// frontend/src/features/playlists/hooks/usePlaylistDetail.ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export function usePlaylistDetail(
  id: string | undefined,
): UseQueryResult<Playlist> {
  return useQuery({
    queryKey: playlistDetailKey(id ?? ''),
    queryFn: () => api<Playlist>(`/playlists/${id}`),
    enabled: !!id,
  });
}
```

- [ ] **Step 2: Implement `usePlaylistTracks`**

```ts
// frontend/src/features/playlists/hooks/usePlaylistTracks.ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylistTracks } from '../lib/playlistTypes';
import { playlistTracksKey } from '../lib/queryKeys';

export function usePlaylistTracks(
  id: string | undefined,
  limit = 200,
): UseQueryResult<PaginatedPlaylistTracks> {
  return useQuery({
    queryKey: playlistTracksKey(id ?? ''),
    queryFn: () =>
      api<PaginatedPlaylistTracks>(`/playlists/${id}/tracks?limit=${limit}&offset=0`),
    enabled: !!id,
  });
}
```

Note: spec caps total playlist size at 1000. Default `limit=200` covers most playlists in one round-trip; raise to 1000 for the detail page if needed in Task 14. Pagination across pages is not required because reorder demands the full list anyway — load it once.

- [ ] **Step 3: Typecheck**

```
pnpm -C frontend typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```
git add frontend/src/features/playlists/hooks/usePlaylistDetail.ts frontend/src/features/playlists/hooks/usePlaylistTracks.ts
git commit -m "feat(playlists): add detail + tracks query hooks"
```

---

## Task 6: Create + delete mutation hooks

**Files:**
- Create: `frontend/src/features/playlists/hooks/useCreatePlaylist.ts`
- Create: `frontend/src/features/playlists/hooks/useDeletePlaylist.ts`
- Create: `frontend/src/features/playlists/hooks/__tests__/useCreatePlaylist.test.ts`

- [ ] **Step 1: Write failing test for `useCreatePlaylist`**

```ts
// frontend/src/features/playlists/hooks/__tests__/useCreatePlaylist.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useCreatePlaylist } from '../useCreatePlaylist';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useCreatePlaylist', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists', async ({ request }) => {
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: 'p1',
            user_id: 'u1',
            name: body.name,
            description: null,
            is_public: false,
            cover_s3_key: null,
            cover_url: null,
            cover_uploaded_at: null,
            spotify_playlist_id: null,
            last_published_at: null,
            needs_republish: false,
            track_count: 0,
            created_at: '2026-05-12T00:00:00Z',
            updated_at: '2026-05-12T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );
  });

  it('invalidates the playlists list after success', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useCreatePlaylist(), { wrapper: makeWrapper(qc) });
    await result.current.mutateAsync({ name: 'Hello', is_public: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['playlists', 'list'] as unknown });
  });
});
```

Note: `vi.spyOn` requires `import { vi } from 'vitest';` — add it.

- [ ] **Step 2: Run failing test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useCreatePlaylist.test.ts
```

Expected: fail (`Cannot find module '../useCreatePlaylist'`).

- [ ] **Step 3: Implement `useCreatePlaylist`**

```ts
// frontend/src/features/playlists/hooks/useCreatePlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import type { CreatePlaylistInput } from '../lib/playlistSchemas';

export function useCreatePlaylist(): UseMutationResult<Playlist, Error, CreatePlaylistInput> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, CreatePlaylistInput>({
    mutationFn: (input) =>
      api<Playlist>('/playlists', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

Note: `invalidateQueries` with `['playlists', 'list']` matches every `playlistsKey(search?)` because TanStack uses prefix matching.

- [ ] **Step 4: Implement `useDeletePlaylist`**

```ts
// frontend/src/features/playlists/hooks/useDeletePlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistDetailKey } from '../lib/queryKeys';

export function useDeletePlaylist(): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      await api<void>(`/playlists/${id}`, { method: 'DELETE' });
    },
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: playlistDetailKey(id) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 5: Run the test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useCreatePlaylist.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```
git add frontend/src/features/playlists/hooks/useCreatePlaylist.ts frontend/src/features/playlists/hooks/useDeletePlaylist.ts frontend/src/features/playlists/hooks/__tests__/useCreatePlaylist.test.ts
git commit -m "feat(playlists): add create + delete mutation hooks"
```

---

## Task 7: Patch + add/remove track mutation hooks

**Files:**
- Create: `frontend/src/features/playlists/hooks/usePatchPlaylist.ts`
- Create: `frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts`
- Create: `frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts`

- [ ] **Step 1: Implement `usePatchPlaylist`**

```ts
// frontend/src/features/playlists/hooks/usePatchPlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import type { PatchPlaylistInput } from '../lib/playlistSchemas';
import { playlistDetailKey } from '../lib/queryKeys';

export function usePatchPlaylist(
  id: string,
): UseMutationResult<Playlist, Error, PatchPlaylistInput, { previous?: Playlist }> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, PatchPlaylistInput, { previous?: Playlist }>({
    mutationFn: (input) =>
      api<Playlist>(`/playlists/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: playlistDetailKey(id) });
      const previous = qc.getQueryData<Playlist>(playlistDetailKey(id));
      if (previous) {
        qc.setQueryData<Playlist>(playlistDetailKey(id), {
          ...previous,
          ...('name' in input && input.name !== undefined ? { name: input.name } : {}),
          ...('description' in input ? { description: input.description ?? null } : {}),
          ...('is_public' in input && input.is_public !== undefined
            ? { is_public: input.is_public }
            : {}),
        });
      }
      return { previous };
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.previous) qc.setQueryData(playlistDetailKey(id), ctx.previous);
    },
    onSuccess: (data) => {
      qc.setQueryData(playlistDetailKey(id), data);
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 2: Implement `useAddTracksToPlaylist`**

```ts
// frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AddTracksResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface AddTracksInput {
  playlistId: string;
  trackIds: string[];
}

export function useAddTracksToPlaylist(): UseMutationResult<AddTracksResult, Error, AddTracksInput> {
  const qc = useQueryClient();
  return useMutation<AddTracksResult, Error, AddTracksInput>({
    mutationFn: ({ playlistId, trackIds }) =>
      api<AddTracksResult>(`/playlists/${playlistId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
    },
  });
}
```

- [ ] **Step 3: Implement `useRemoveTrackFromPlaylist`**

```ts
// frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylistTracks } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface RemoveTrackInput {
  playlistId: string;
  trackId: string;
}

interface RollbackCtx {
  previousTracks?: PaginatedPlaylistTracks;
}

export function useRemoveTrackFromPlaylist(): UseMutationResult<
  void,
  Error,
  RemoveTrackInput,
  RollbackCtx
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackInput, RollbackCtx>({
    mutationFn: async ({ playlistId, trackId }) => {
      await api<void>(`/playlists/${playlistId}/tracks/${trackId}`, { method: 'DELETE' });
    },
    onMutate: async ({ playlistId, trackId }) => {
      await qc.cancelQueries({ queryKey: playlistTracksKey(playlistId) });
      const previousTracks = qc.getQueryData<PaginatedPlaylistTracks>(
        playlistTracksKey(playlistId),
      );
      if (previousTracks) {
        qc.setQueryData<PaginatedPlaylistTracks>(playlistTracksKey(playlistId), {
          ...previousTracks,
          items: previousTracks.items.filter((t) => t.track_id !== trackId),
          total: Math.max(0, previousTracks.total - 1),
        });
      }
      return { previousTracks };
    },
    onError: (_err, { playlistId }, ctx) => {
      if (ctx?.previousTracks) {
        qc.setQueryData(playlistTracksKey(playlistId), ctx.previousTracks);
      }
    },
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
    },
  });
}
```

- [ ] **Step 4: Typecheck**

```
pnpm -C frontend typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/playlists/hooks/usePatchPlaylist.ts frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts
git commit -m "feat(playlists): add patch + track add/remove hooks"
```

---

## Task 8: Reorder hook with debounce

Mirrors `useReorderCategories` from `frontend/src/features/categories/hooks/useReorderCategories.ts`.

**Files:**
- Create: `frontend/src/features/playlists/hooks/useReorderPlaylistTracks.ts`
- Create: `frontend/src/features/playlists/hooks/__tests__/useReorderPlaylistTracks.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/src/features/playlists/hooks/__tests__/useReorderPlaylistTracks.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import i18n from '../../../../i18n';
import { useReorderPlaylistTracks } from '../useReorderPlaylistTracks';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <I18nextProvider i18n={i18n}>
        <MantineProvider>
          <Notifications />
          <QueryClientProvider client={qc}>{children}</QueryClientProvider>
        </MantineProvider>
      </I18nextProvider>
    );
  };
}

describe('useReorderPlaylistTracks', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('debounces and posts the latest order', async () => {
    let postedBody: { track_ids: string[] } | null = null;
    server.use(
      http.post('http://localhost/playlists/p1/tracks/order', async ({ request }) => {
        postedBody = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json({ correlation_id: 'cid' });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useReorderPlaylistTracks('p1'), {
      wrapper: makeWrapper(qc),
    });

    act(() => {
      result.current.queueOrder(['t1', 't2', 't3']);
      result.current.queueOrder(['t3', 't2', 't1']);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(postedBody).toEqual({ track_ids: ['t3', 't2', 't1'] });
  });

  it('invalidates tracks cache on 400 order_mismatch', async () => {
    server.use(
      http.post('http://localhost/playlists/p1/tracks/order', () =>
        HttpResponse.json(
          { error_code: 'order_mismatch', message: 'mismatch' },
          { status: 400 },
        ),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useReorderPlaylistTracks('p1'), {
      wrapper: makeWrapper(qc),
    });
    act(() => result.current.queueOrder(['t1', 't2']));
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(
      invalidateSpy.mock.calls.some(
        ([arg]) => Array.isArray(arg?.queryKey) && arg.queryKey[0] === 'playlists' && arg.queryKey[1] === 'tracks',
      ),
    ).toBe(true);
  });
});
```

- [ ] **Step 2: Run failing test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useReorderPlaylistTracks.test.ts
```

Expected: fail (`Cannot find module '../useReorderPlaylistTracks'`).

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/playlists/hooks/useReorderPlaylistTracks.ts
import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { playlistTracksKey } from '../lib/queryKeys';

const DEBOUNCE_MS = 200;

export interface ReorderHandle {
  queueOrder: (trackIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useReorderPlaylistTracks(playlistId: string): ReorderHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (trackIds) =>
      api(`/playlists/${playlistId}/tracks/order`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onError: (err) => {
      const isMismatch =
        err instanceof ApiError && err.status === 400 && err.code === 'order_mismatch';
      void qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
      try {
        notifications.show({
          message: isMismatch
            ? t('playlists.toast.reorder_race')
            : t('playlists.toast.generic_error'),
          color: isMismatch ? 'yellow' : 'red',
        });
      } catch {
        // notifications may be unmounted in test environments
      }
    },
  });

  const flush = useCallback(async () => {
    const order = latestRef.current;
    latestRef.current = null;
    timerRef.current = null;
    if (!order) return;
    await mutation.mutateAsync(order).catch(() => {
      // onError handler manages user-facing side effects
    });
  }, [mutation]);

  const queueOrder = useCallback(
    (trackIds: string[]) => {
      latestRef.current = trackIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [flush],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { queueOrder, flushNow: flush };
}
```

- [ ] **Step 4: Re-run, expect pass**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useReorderPlaylistTracks.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/playlists/hooks/useReorderPlaylistTracks.ts frontend/src/features/playlists/hooks/__tests__/useReorderPlaylistTracks.test.ts
git commit -m "feat(playlists): add debounced reorder hook"
```

---

## Task 9: Spotify import hook

**Files:**
- Create: `frontend/src/features/playlists/hooks/useImportSpotifyTracks.ts`

- [ ] **Step 1: Implement**

```ts
// frontend/src/features/playlists/hooks/useImportSpotifyTracks.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ImportSpotifyResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface ImportSpotifyInput {
  playlistId: string;
  spotifyRefs: string[];
}

export function useImportSpotifyTracks(): UseMutationResult<
  ImportSpotifyResult,
  Error,
  ImportSpotifyInput
> {
  const qc = useQueryClient();
  return useMutation<ImportSpotifyResult, Error, ImportSpotifyInput>({
    mutationFn: ({ playlistId, spotifyRefs }) =>
      api<ImportSpotifyResult>(`/playlists/${playlistId}/tracks/import-spotify`, {
        method: 'POST',
        body: JSON.stringify({ spotify_refs: spotifyRefs }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
    },
  });
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/hooks/useImportSpotifyTracks.ts
git commit -m "feat(playlists): add spotify import hook"
```

---

## Task 10: Cover upload + clear hooks

The cover replace hook orchestrates the three-step backend flow: presign → S3 PUT → confirm.

**Files:**
- Create: `frontend/src/features/playlists/hooks/useUploadCover.ts`
- Create: `frontend/src/features/playlists/hooks/useClearCover.ts`
- Create: `frontend/src/features/playlists/hooks/__tests__/useUploadCover.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/src/features/playlists/hooks/__tests__/useUploadCover.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useUploadCover } from '../useUploadCover';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useUploadCover', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/p1/cover/upload-url', () =>
        HttpResponse.json({
          upload_url: 'https://s3.example/PUT',
          s3_key: 'covers/u1/p1/abc.jpg',
          expires_in: 300,
        }),
      ),
      http.put('https://s3.example/PUT', () => new HttpResponse(null, { status: 200 })),
      http.post('http://localhost/playlists/p1/cover/confirm', async ({ request }) => {
        const body = (await request.json()) as { s3_key: string };
        expect(body.s3_key).toBe('covers/u1/p1/abc.jpg');
        return HttpResponse.json({
          id: 'p1',
          user_id: 'u1',
          name: 'P1',
          description: null,
          is_public: false,
          cover_s3_key: 'covers/u1/p1/abc.jpg',
          cover_url: 'https://s3.example/GET',
          cover_uploaded_at: '2026-05-12T00:00:00Z',
          spotify_playlist_id: null,
          last_published_at: null,
          needs_republish: false,
          track_count: 0,
          created_at: '2026-05-12T00:00:00Z',
          updated_at: '2026-05-12T00:00:00Z',
        });
      }),
    );
  });

  it('runs presign → PUT → confirm and returns the updated playlist', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const file = new File(['xxx'], 'cover.jpg', { type: 'image/jpeg' });
    const out = await result.current.mutateAsync({ playlistId: 'p1', file });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(out.cover_s3_key).toBe('covers/u1/p1/abc.jpg');
  });

  it('rejects files larger than 256KB on the client', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const huge = new File([new Uint8Array(300_000)], 'big.jpg', { type: 'image/jpeg' });
    await expect(
      result.current.mutateAsync({ playlistId: 'p1', file: huge }),
    ).rejects.toThrow(/too large/i);
  });

  it('rejects non-jpeg/png types on the client', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const gif = new File(['x'], 'a.gif', { type: 'image/gif' });
    await expect(
      result.current.mutateAsync({ playlistId: 'p1', file: gif }),
    ).rejects.toThrow(/unsupported/i);
  });
});
```

- [ ] **Step 2: Run failing test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useUploadCover.test.ts
```

Expected: fail (`Cannot find module '../useUploadCover'`).

- [ ] **Step 3: Implement `useUploadCover`**

```ts
// frontend/src/features/playlists/hooks/useUploadCover.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CoverUploadUrlResponse, Playlist } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export const MAX_COVER_BYTES = 256 * 1024;
const ACCEPTED_TYPES = new Set(['image/jpeg', 'image/png']);

export interface UploadCoverInput {
  playlistId: string;
  file: File;
}

export function useUploadCover(): UseMutationResult<Playlist, Error, UploadCoverInput> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, UploadCoverInput>({
    mutationFn: async ({ playlistId, file }) => {
      if (!ACCEPTED_TYPES.has(file.type)) {
        throw new Error('unsupported_content_type');
      }
      if (file.size > MAX_COVER_BYTES) {
        throw new Error('cover_too_large');
      }
      const presign = await api<CoverUploadUrlResponse>(
        `/playlists/${playlistId}/cover/upload-url`,
        {
          method: 'POST',
          body: JSON.stringify({ content_type: file.type as 'image/jpeg' | 'image/png' }),
        },
      );
      // Presigned PUT — do not use the `api` helper because it injects
      // Authorization and credentials we must NOT send to S3.
      const putRes = await fetch(presign.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': file.type },
        body: file,
      });
      if (!putRes.ok) {
        throw new Error(`cover_put_failed_${putRes.status}`);
      }
      const playlist = await api<Playlist>(`/playlists/${playlistId}/cover/confirm`, {
        method: 'POST',
        body: JSON.stringify({ s3_key: presign.s3_key }),
      });
      return playlist;
    },
    onSuccess: (playlist) => {
      qc.setQueryData(playlistDetailKey(playlist.id), playlist);
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 4: Implement `useClearCover`**

```ts
// frontend/src/features/playlists/hooks/useClearCover.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistDetailKey } from '../lib/queryKeys';

export function useClearCover(): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (playlistId) => {
      await api<void>(`/playlists/${playlistId}/cover`, { method: 'DELETE' });
    },
    onSuccess: (_data, playlistId) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 5: Re-run upload test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/useUploadCover.test.ts
```

Expected: PASS, 3/3.

- [ ] **Step 6: Commit**

```
git add frontend/src/features/playlists/hooks/useUploadCover.ts frontend/src/features/playlists/hooks/useClearCover.ts frontend/src/features/playlists/hooks/__tests__/useUploadCover.test.ts
git commit -m "feat(playlists): add cover upload + clear hooks"
```

---

## Task 11: Publish hook

**Files:**
- Create: `frontend/src/features/playlists/hooks/usePublishPlaylist.ts`
- Create: `frontend/src/features/playlists/hooks/__tests__/usePublishPlaylist.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/src/features/playlists/hooks/__tests__/usePublishPlaylist.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { usePublishPlaylist } from '../usePublishPlaylist';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('usePublishPlaylist', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/p1/publish', async ({ request }) => {
        const body = (await request.json()) as { confirm_overwrite: boolean };
        return HttpResponse.json({
          spotify_playlist_id: 'sp1',
          spotify_url: 'https://open.spotify.com/playlist/sp1',
          skipped_tracks: [],
          cover_failed: false,
          published_at: '2026-05-12T00:00:00Z',
          confirm_overwrite_used: body.confirm_overwrite,
        });
      }),
    );
  });

  it('passes confirm_overwrite=false by default', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => usePublishPlaylist(), { wrapper: makeWrapper(qc) });
    const out = await result.current.mutateAsync({
      playlistId: 'p1',
      confirmOverwrite: false,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(out.spotify_playlist_id).toBe('sp1');
  });
});
```

- [ ] **Step 2: Run failing test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/usePublishPlaylist.test.ts
```

Expected: fail.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/playlists/hooks/usePublishPlaylist.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PublishResult } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export interface PublishInput {
  playlistId: string;
  confirmOverwrite: boolean;
}

export function usePublishPlaylist(): UseMutationResult<PublishResult, Error, PublishInput> {
  const qc = useQueryClient();
  return useMutation<PublishResult, Error, PublishInput>({
    mutationFn: ({ playlistId, confirmOverwrite }) =>
      api<PublishResult>(`/playlists/${playlistId}/publish`, {
        method: 'POST',
        body: JSON.stringify({ confirm_overwrite: confirmOverwrite }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 4: Re-run test**

```
pnpm -C frontend test -- src/features/playlists/hooks/__tests__/usePublishPlaylist.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/playlists/hooks/usePublishPlaylist.ts frontend/src/features/playlists/hooks/__tests__/usePublishPlaylist.test.ts
git commit -m "feat(playlists): add publish hook"
```

---

## Task 12: i18n keys + nav item + router wiring

**Files:**
- Modify: `frontend/src/i18n/en.json` — add `playlists.*` namespace, `appshell.playlists`, and `categories.row_actions.add_to_playlist*` keys.
- Modify: `frontend/src/routes/_layout.tsx` — append `Playlists` to `NAV_ITEMS`.
- Modify: `frontend/src/routes/router.tsx` — register the two routes.
- Create: `frontend/src/features/playlists/index.ts` — `export * from './lib/playlistTypes';` plus route component re-exports added later.

- [ ] **Step 1: Add i18n keys to `frontend/src/i18n/en.json`**

Add to the existing JSON (preserve trailing commas, etc.):

```json
"appshell": {
  "admin": "Admin",
  "home": "Home",
  "categories": "Categories",
  "triage": "Triage",
  "curate": "Curate",
  "profile": "Profile",
  "wordmark": "CLOUDER",
  "playlists": "Playlists"
}
```

Add a new top-level `playlists` object next to `categories`:

```json
"playlists": {
  "page_title": "Playlists",
  "create_cta": "Create playlist",
  "search_placeholder": "Search playlists",
  "table": {
    "col_cover": "",
    "col_name": "Name",
    "col_tracks": "Tracks",
    "col_public": "Public",
    "col_spotify": "Spotify",
    "col_updated": "Updated",
    "col_actions": ""
  },
  "empty": {
    "title": "No playlists yet",
    "body": "Create your first playlist to gather tracks across categories."
  },
  "form": {
    "create_title": "Create playlist",
    "rename_title": "Rename playlist",
    "edit_description_title": "Edit description",
    "name_label": "Name",
    "description_label": "Description",
    "is_public_label": "Public",
    "is_public_description": "Other CLOUDER users see this is set; the Spotify playlist visibility is controlled separately when publishing.",
    "submit_create": "Create",
    "submit_save": "Save",
    "cancel": "Cancel"
  },
  "detail": {
    "back_to_list": "Back to playlists",
    "stats": "{{count}} tracks · Updated {{when}}",
    "delete_cta": "Delete playlist",
    "clear_cover_cta": "Remove cover",
    "add_tracks_cta": "Add tracks",
    "import_spotify_cta": "Import from Spotify",
    "tracks_search_placeholder": "Search loaded tracks",
    "empty_tracks_title": "No tracks yet",
    "empty_tracks_body": "Add tracks from a category or import from Spotify."
  },
  "cover": {
    "replace": "Replace cover",
    "remove": "Remove cover",
    "help_text": "JPEG or PNG, up to 256 KB",
    "uploading": "Uploading…",
    "placeholder_alt": "No cover yet"
  },
  "publish": {
    "first": "Publish to Spotify",
    "again": "Re-publish to Spotify",
    "confirm_title": "Re-publish to Spotify?",
    "confirm_body": "This will overwrite the existing Spotify playlist \"{{name}}\". {{count}} CLOUDER tracks will fully replace its current contents, along with the cover and description.",
    "confirm_cta": "Re-publish",
    "cancel": "Cancel",
    "result_skipped_title": "{{count}} tracks were skipped",
    "result_skipped_body": "The following tracks could not be published to Spotify:",
    "cover_failed": "Tracks updated. Spotify rejected the cover — try Replace and re-publish.",
    "open_in_spotify": "Open in Spotify"
  },
  "drift_badge": {
    "label": "Needs republish",
    "tooltip": "Tracks or cover changed since the last Spotify publish. Re-publish to push the latest version."
  },
  "origin": {
    "spotify": "Spotify"
  },
  "import": {
    "title": "Import from Spotify",
    "textarea_label": "Track URLs, URIs, or IDs",
    "textarea_placeholder": "One per line. Supports https://open.spotify.com/track/...\\nspotify:track:...\\nor bare 22-character ID.",
    "submit": "Import",
    "added": "Added ({{count}})",
    "skipped": "Skipped ({{count}})",
    "reason_invalid_ref": "invalid format",
    "reason_not_found": "not found",
    "reason_already_in_playlist": "already in playlist",
    "max_exceeded": "Maximum 50 refs per import."
  },
  "add_tracks": {
    "title": "Add tracks",
    "style_label": "Style",
    "category_label": "Category",
    "search_placeholder": "Search tracks",
    "selected_count": "{{count}} selected",
    "submit": "Add {{count}} tracks",
    "empty_category": "No tracks in this category."
  },
  "toast": {
    "created": "Playlist created",
    "renamed": "Playlist renamed",
    "deleted": "Playlist deleted",
    "description_saved": "Description saved",
    "visibility_saved": "Visibility updated",
    "track_added": "Added to {{name}}",
    "tracks_added": "Added {{count}} tracks",
    "track_removed": "Track removed",
    "undo_action": "Undo",
    "undone": "Undone",
    "undo_failed": "Undo failed",
    "reorder_race": "Tracks changed, list refreshed.",
    "published_first": "Playlist published to Spotify",
    "published_again": "Playlist re-published to Spotify",
    "cover_saved": "Cover updated",
    "cover_removed": "Cover removed",
    "cover_too_large": "Cover too large (max 256 KB).",
    "cover_unsupported": "Unsupported image format (JPEG or PNG only).",
    "cover_failed": "Cover upload failed.",
    "import_done": "{{added}} imported · {{skipped}} skipped",
    "generic_error": "Something went wrong."
  },
  "errors": {
    "name_required": "Name is required.",
    "name_too_long": "Name must be 100 characters or fewer.",
    "name_control_chars": "Name cannot contain control characters.",
    "description_too_long": "Description must be 300 characters or fewer.",
    "name_conflict": "A playlist with that name already exists.",
    "limit_reached": "Playlist limit reached (200 max).",
    "spotify_not_authorized": "Spotify isn't linked. Re-link from Profile.",
    "spotify_upstream_error": "Spotify is unreachable, retry in a moment.",
    "tracks_not_accessible": "Some tracks are no longer accessible.",
    "confirm_overwrite_required": "Someone else already published this playlist. Confirm to overwrite."
  }
}
```

Add to existing `categories.row_actions` (find via grep — currently has `trigger_aria`, `move_label`, `move_empty`, `loading`, `current_marker`, `remove_label`):

```json
"add_to_playlist_label": "Add to playlist",
"add_to_playlist_empty": "No playlists yet",
"manage_playlists": "Manage playlists…"
```

- [ ] **Step 2: Modify `frontend/src/routes/_layout.tsx` NAV_ITEMS**

Find `const NAV_ITEMS: NavItem[] = [...]` (around line 30). Insert `Playlists` between `Curate` and `Profile`:

```ts
import {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconPlaylist,
  IconUser,
  IconShield,
} from '../components/icons';
```

```ts
const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'appshell.home', Icon: IconHome },
  { path: '/categories', labelKey: 'appshell.categories', Icon: IconCategory },
  { path: '/triage', labelKey: 'appshell.triage', Icon: IconLayoutColumns },
  { path: '/curate', labelKey: 'appshell.curate', Icon: IconAdjustments },
  { path: '/playlists', labelKey: 'appshell.playlists', Icon: IconPlaylist },
  { path: '/profile', labelKey: 'appshell.profile', Icon: IconUser },
];
```

- [ ] **Step 3: Add the icon export**

Open `frontend/src/components/icons.ts` and add `export { IconPlaylist } from '@tabler/icons-react';` next to the other re-exports. If the file does not yet export icons via this barrel, import `IconPlaylist` directly in `_layout.tsx` from `@tabler/icons-react` instead.

Run `grep -n IconHome frontend/src/components/icons.ts` first. If the file lists icons, follow that pattern; otherwise revert step 3 and adjust the import in step 2 to come straight from `@tabler/icons-react`.

- [ ] **Step 4: Register routes in `frontend/src/routes/router.tsx`**

Add this block inside the authenticated children array, immediately before `{ path: 'profile', element: <ProfilePage /> }`:

```tsx
import { PlaylistsListPage } from '../features/playlists/routes/PlaylistsListPage';
import { PlaylistDetailPage } from '../features/playlists/routes/PlaylistDetailPage';

// ...
{
  path: 'playlists',
  children: [
    { index: true, element: <PlaylistsListPage /> },
    { path: ':id', element: <PlaylistDetailPage /> },
  ],
},
```

The two route components do not exist yet. To keep the build green, create thin placeholders for now:

```tsx
// frontend/src/features/playlists/routes/PlaylistsListPage.tsx
export function PlaylistsListPage() {
  return <div data-testid="playlists-list-placeholder">Playlists</div>;
}
```

```tsx
// frontend/src/features/playlists/routes/PlaylistDetailPage.tsx
export function PlaylistDetailPage() {
  return <div data-testid="playlists-detail-placeholder">Playlist</div>;
}
```

- [ ] **Step 5: Create the feature index barrel**

```ts
// frontend/src/features/playlists/index.ts
export type * from './lib/playlistTypes';
export { playlistsKey, playlistDetailKey, playlistTracksKey } from './lib/queryKeys';
```

- [ ] **Step 6: Build + typecheck**

```
pnpm -C frontend typecheck
pnpm -C frontend test -- --run
```

Expected: typecheck clean, every previously passing test still passes.

- [ ] **Step 7: Commit**

```
git add frontend/src/i18n/en.json frontend/src/routes/_layout.tsx frontend/src/routes/router.tsx frontend/src/features/playlists/index.ts frontend/src/features/playlists/routes/PlaylistsListPage.tsx frontend/src/features/playlists/routes/PlaylistDetailPage.tsx frontend/src/components/icons.ts
git commit -m "feat(playlists): wire routes, nav, and i18n keys"
```

---

## Task 13: PlaylistFormDialog

**Files:**
- Create: `frontend/src/features/playlists/components/PlaylistFormDialog.tsx`

Modeled on `frontend/src/features/categories/components/CategoryFormDialog.tsx`. Supports three modes.

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/playlists/components/PlaylistFormDialog.tsx
import { useEffect } from 'react';
import {
  Button,
  Drawer,
  Group,
  Modal,
  Stack,
  Switch,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import {
  createPlaylistSchema,
  type CreatePlaylistInput,
  playlistNameSchema,
  playlistDescriptionSchema,
} from '../lib/playlistSchemas';
import { z } from 'zod';

export type PlaylistFormMode = 'create' | 'rename' | 'edit-description';

export interface PlaylistFormDialogProps {
  mode: PlaylistFormMode;
  opened: boolean;
  initial: { name: string; description: string | null; is_public: boolean };
  submitting: boolean;
  onClose: () => void;
  onSubmit: (input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) => void;
  serverNameError?: string;
}

const renameSchema = z.object({ name: playlistNameSchema });
const editDescriptionSchema = z.object({ description: playlistDescriptionSchema });

type FormValues = {
  name: string;
  description: string;
  is_public: boolean;
};

export function PlaylistFormDialog({
  mode,
  opened,
  initial,
  submitting,
  onClose,
  onSubmit,
  serverNameError,
}: PlaylistFormDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  const resolver =
    mode === 'create'
      ? zodResolver(createPlaylistSchema)
      : mode === 'rename'
        ? zodResolver(renameSchema)
        : zodResolver(editDescriptionSchema);

  const form = useForm<FormValues>({
    initialValues: {
      name: initial.name,
      description: initial.description ?? '',
      is_public: initial.is_public,
    },
    validate: resolver,
  });

  useEffect(() => {
    if (opened) {
      form.setValues({
        name: initial.name,
        description: initial.description ?? '',
        is_public: initial.is_public,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, initial.name, initial.description, initial.is_public]);

  const title =
    mode === 'create'
      ? t('playlists.form.create_title')
      : mode === 'rename'
        ? t('playlists.form.rename_title')
        : t('playlists.form.edit_description_title');

  const submitLabel =
    mode === 'create' ? t('playlists.form.submit_create') : t('playlists.form.submit_save');

  const errorMap: Record<string, string> = {
    name_required: t('playlists.errors.name_required'),
    name_too_long: t('playlists.errors.name_too_long'),
    name_control_chars: t('playlists.errors.name_control_chars'),
    description_too_long: t('playlists.errors.description_too_long'),
  };

  const nameError = (() => {
    if (serverNameError) return serverNameError;
    const e = form.errors.name;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  const descriptionError = (() => {
    const e = form.errors.description;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  function handleSubmit(values: FormValues) {
    const out: { name?: string; description?: string | null; is_public?: boolean } = {};
    if (mode === 'create' || mode === 'rename') out.name = values.name.trim();
    if (mode === 'create' || mode === 'edit-description') {
      out.description = values.description.trim() === '' ? null : values.description.trim();
    }
    if (mode === 'create') out.is_public = values.is_public;
    onSubmit(out);
  }

  const body = (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="md">
        {(mode === 'create' || mode === 'rename') && (
          <TextInput
            label={t('playlists.form.name_label')}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            maxLength={100}
            {...form.getInputProps('name')}
            error={nameError}
          />
        )}
        {(mode === 'create' || mode === 'edit-description') && (
          <Textarea
            label={t('playlists.form.description_label')}
            maxLength={300}
            autosize
            minRows={2}
            maxRows={6}
            {...form.getInputProps('description')}
            error={descriptionError}
          />
        )}
        {mode === 'create' && (
          <Switch
            label={t('playlists.form.is_public_label')}
            description={t('playlists.form.is_public_description')}
            {...form.getInputProps('is_public', { type: 'checkbox' })}
          />
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            {t('playlists.form.cancel')}
          </Button>
          <Button type="submit" loading={submitting}>
            {submitLabel}
          </Button>
        </Group>
      </Stack>
    </form>
  );

  if (isMobile) {
    return (
      <Drawer opened={opened} onClose={onClose} position="bottom" size="auto" title={title}>
        {body}
      </Drawer>
    );
  }
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered transitionProps={{ duration: 0 }}>
      {body}
    </Modal>
  );
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/components/PlaylistFormDialog.tsx
git commit -m "feat(playlists): add PlaylistFormDialog"
```

---

## Task 14: List page (with create + delete flow)

**Files:**
- Modify: `frontend/src/features/playlists/routes/PlaylistsListPage.tsx` (replace placeholder with real implementation)
- Create: `frontend/src/features/playlists/components/PlaylistRow.tsx`
- Create: `frontend/src/features/playlists/components/PlaylistsTable.tsx`
- Create: `frontend/src/features/playlists/components/DriftBadge.tsx`
- Create: `frontend/src/features/playlists/routes/__tests__/PlaylistsListPage.test.tsx`

- [ ] **Step 1: Implement `DriftBadge.tsx`**

```tsx
// frontend/src/features/playlists/components/DriftBadge.tsx
import { Badge, Tooltip } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export function DriftBadge() {
  const { t } = useTranslation();
  return (
    <Tooltip label={t('playlists.drift_badge.tooltip')} withinPortal>
      <Badge color="yellow" leftSection={<IconAlertTriangle size={12} />} size="sm">
        {t('playlists.drift_badge.label')}
      </Badge>
    </Tooltip>
  );
}
```

- [ ] **Step 2: Implement `PlaylistRow.tsx`**

```tsx
// frontend/src/features/playlists/components/PlaylistRow.tsx
import {
  ActionIcon,
  Anchor,
  Avatar,
  Group,
  Menu,
  Table,
  Text,
} from '@mantine/core';
import {
  IconBrandSpotify,
  IconDotsVertical,
  IconLock,
  IconLockOpen,
  IconPhoto,
} from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { Playlist } from '../lib/playlistTypes';
import { DriftBadge } from './DriftBadge';

export interface PlaylistRowProps {
  playlist: Playlist;
  onRename: (p: Playlist) => void;
  onEditDescription: (p: Playlist) => void;
  onDelete: (p: Playlist) => void;
}

export function PlaylistRow({
  playlist,
  onRename,
  onEditDescription,
  onDelete,
}: PlaylistRowProps) {
  const { t } = useTranslation();
  return (
    <Table.Tr>
      <Table.Td>
        <Avatar
          src={playlist.cover_url}
          alt=""
          size={40}
          radius="sm"
          color="gray"
        >
          <IconPhoto size={16} />
        </Avatar>
      </Table.Td>
      <Table.Td>
        <Anchor
          component={Link}
          to={`/playlists/${playlist.id}`}
          c="var(--color-fg)"
          td="none"
          fw={500}
        >
          {playlist.name}
        </Anchor>
      </Table.Td>
      <Table.Td>{playlist.track_count}</Table.Td>
      <Table.Td>
        {playlist.is_public ? <IconLockOpen size={16} /> : <IconLock size={16} />}
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          {playlist.spotify_playlist_id ? <IconBrandSpotify size={16} /> : null}
          {playlist.needs_republish ? <DriftBadge /> : null}
        </Group>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {playlist.updated_at.slice(0, 10)}
        </Text>
      </Table.Td>
      <Table.Td>
        <Menu withinPortal={false} transitionProps={{ duration: 0 }}>
          <Menu.Target>
            <ActionIcon variant="subtle" aria-label="Row actions">
              <IconDotsVertical size={18} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => onRename(playlist)}>
              {t('playlists.form.rename_title')}
            </Menu.Item>
            <Menu.Item onClick={() => onEditDescription(playlist)}>
              {t('playlists.form.edit_description_title')}
            </Menu.Item>
            <Menu.Item color="red" onClick={() => onDelete(playlist)}>
              {t('playlists.detail.delete_cta')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Table.Td>
    </Table.Tr>
  );
}
```

- [ ] **Step 3: Implement `PlaylistsTable.tsx`**

```tsx
// frontend/src/features/playlists/components/PlaylistsTable.tsx
import { Table } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { Playlist } from '../lib/playlistTypes';
import { PlaylistRow } from './PlaylistRow';

export interface PlaylistsTableProps {
  playlists: Playlist[];
  onRename: (p: Playlist) => void;
  onEditDescription: (p: Playlist) => void;
  onDelete: (p: Playlist) => void;
}

export function PlaylistsTable({
  playlists,
  onRename,
  onEditDescription,
  onDelete,
}: PlaylistsTableProps) {
  const { t } = useTranslation();
  return (
    <Table striped withTableBorder>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('playlists.table.col_cover')}</Table.Th>
          <Table.Th>{t('playlists.table.col_name')}</Table.Th>
          <Table.Th>{t('playlists.table.col_tracks')}</Table.Th>
          <Table.Th>{t('playlists.table.col_public')}</Table.Th>
          <Table.Th>{t('playlists.table.col_spotify')}</Table.Th>
          <Table.Th>{t('playlists.table.col_updated')}</Table.Th>
          <Table.Th>{t('playlists.table.col_actions')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {playlists.map((p) => (
          <PlaylistRow
            key={p.id}
            playlist={p}
            onRename={onRename}
            onEditDescription={onEditDescription}
            onDelete={onDelete}
          />
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 4: Implement `PlaylistsListPage.tsx`**

Replace the placeholder created in Task 12:

```tsx
// frontend/src/features/playlists/routes/PlaylistsListPage.tsx
import { useState } from 'react';
import { Button, Group, Stack, TextInput, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useDebouncedValue } from '@mantine/hooks';
import { IconPlus, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { usePlaylists } from '../hooks/usePlaylists';
import { useCreatePlaylist } from '../hooks/useCreatePlaylist';
import { usePatchPlaylist } from '../hooks/usePatchPlaylist';
import { useDeletePlaylist } from '../hooks/useDeletePlaylist';
import { PlaylistsTable } from '../components/PlaylistsTable';
import { PlaylistFormDialog } from '../components/PlaylistFormDialog';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import type { Playlist } from '../lib/playlistTypes';

export function PlaylistsListPage() {
  const { t } = useTranslation();
  const [rawSearch, setRawSearch] = useState('');
  const [search] = useDebouncedValue(rawSearch.trim(), 300);
  const { data, isLoading, isError } = usePlaylists({ search });
  const create = useCreatePlaylist();
  const deleteMut = useDeletePlaylist();

  const [createOpen, setCreateOpen] = useState(false);
  const [createServerError, setCreateServerError] = useState<string | undefined>();
  const [renameTarget, setRenameTarget] = useState<Playlist | null>(null);
  const [descTarget, setDescTarget] = useState<Playlist | null>(null);
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  const renameMut = usePatchPlaylist(renameTarget?.id ?? '');
  const descMut = usePatchPlaylist(descTarget?.id ?? '');

  async function handleCreate(input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) {
    setCreateServerError(undefined);
    try {
      await create.mutateAsync({
        name: input.name!,
        description: input.description ?? null,
        is_public: input.is_public ?? false,
      });
      notifications.show({ message: t('playlists.toast.created'), color: 'green' });
      setCreateOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCreateServerError(t('playlists.errors.name_conflict'));
      } else if (err instanceof ApiError && err.status === 429) {
        notifications.show({ message: t('playlists.errors.limit_reached'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleRename(input: { name?: string }) {
    if (!renameTarget) return;
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync({ name: input.name });
      notifications.show({ message: t('playlists.toast.renamed'), color: 'green' });
      setRenameTarget(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('playlists.errors.name_conflict'));
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleEditDescription(input: { description?: string | null }) {
    if (!descTarget) return;
    try {
      await descMut.mutateAsync({ description: input.description ?? null });
      notifications.show({ message: t('playlists.toast.description_saved'), color: 'green' });
      setDescTarget(null);
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  function openDelete(p: Playlist) {
    modals.openConfirmModal({
      title: t('playlists.detail.delete_cta'),
      children: p.name,
      labels: { confirm: t('playlists.detail.delete_cta'), cancel: t('playlists.form.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(p.id);
          notifications.show({ message: t('playlists.toast.deleted'), color: 'green' });
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  const items = data?.items ?? [];

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={1}>{t('playlists.page_title')}</Title>
        <Group gap="sm">
          <TextInput
            placeholder={t('playlists.search_placeholder')}
            leftSection={<IconSearch size={16} />}
            value={rawSearch}
            onChange={(e) => setRawSearch(e.currentTarget.value)}
          />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreateOpen(true)}>
            {t('playlists.create_cta')}
          </Button>
        </Group>
      </Group>

      {items.length === 0 ? (
        <EmptyState
          title={t('playlists.empty.title')}
          body={t('playlists.empty.body')}
        />
      ) : (
        <PlaylistsTable
          playlists={items}
          onRename={(p) => setRenameTarget(p)}
          onEditDescription={(p) => setDescTarget(p)}
          onDelete={openDelete}
        />
      )}

      <PlaylistFormDialog
        mode="create"
        opened={createOpen}
        initial={{ name: '', description: null, is_public: false }}
        submitting={create.isPending}
        onClose={() => {
          setCreateOpen(false);
          setCreateServerError(undefined);
        }}
        onSubmit={handleCreate}
        serverNameError={createServerError}
      />
      <PlaylistFormDialog
        mode="rename"
        opened={!!renameTarget}
        initial={
          renameTarget
            ? { name: renameTarget.name, description: renameTarget.description, is_public: renameTarget.is_public }
            : { name: '', description: null, is_public: false }
        }
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameTarget(null);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverNameError={renameServerError}
      />
      <PlaylistFormDialog
        mode="edit-description"
        opened={!!descTarget}
        initial={
          descTarget
            ? { name: descTarget.name, description: descTarget.description, is_public: descTarget.is_public }
            : { name: '', description: null, is_public: false }
        }
        submitting={descMut.isPending}
        onClose={() => setDescTarget(null)}
        onSubmit={handleEditDescription}
      />
    </Stack>
  );
}
```

- [ ] **Step 5: Write the route test**

```tsx
// frontend/src/features/playlists/routes/__tests__/PlaylistsListPage.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { PlaylistsListPage } from '../PlaylistsListPage';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/playlists']}>{children}</MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

const seed = [
  {
    id: 'p1',
    user_id: 'u1',
    name: 'Saturday techno',
    description: null,
    is_public: false,
    cover_s3_key: null,
    cover_url: null,
    cover_uploaded_at: null,
    spotify_playlist_id: null,
    last_published_at: null,
    needs_republish: false,
    track_count: 12,
    created_at: '2026-05-12T00:00:00Z',
    updated_at: '2026-05-12T00:00:00Z',
  },
];

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/playlists', () =>
      HttpResponse.json({ items: seed, total: 1, limit: 20, offset: 0 }),
    ),
  );
});

describe('PlaylistsListPage', () => {
  it('renders playlist rows', async () => {
    render(
      <Wrapper>
        <PlaylistsListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Saturday techno')).toBeInTheDocument());
  });

  it('creates a new playlist via the dialog', async () => {
    const user = userEvent.setup();
    let posted: { name: string } | null = null;
    server.use(
      http.post('http://localhost/playlists', async ({ request }) => {
        posted = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: 'p2',
            user_id: 'u1',
            name: posted.name,
            description: null,
            is_public: false,
            cover_s3_key: null,
            cover_url: null,
            cover_uploaded_at: null,
            spotify_playlist_id: null,
            last_published_at: null,
            needs_republish: false,
            track_count: 0,
            created_at: '2026-05-12T00:00:00Z',
            updated_at: '2026-05-12T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );

    render(
      <Wrapper>
        <PlaylistsListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Saturday techno')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Create playlist/i }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Name'), 'Sunday house');
    await user.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(posted?.name).toBe('Sunday house'));
  });
});
```

- [ ] **Step 6: Run the tests**

```
pnpm -C frontend test -- src/features/playlists/routes/__tests__/PlaylistsListPage.test.tsx
```

Expected: PASS, 2/2.

- [ ] **Step 7: Commit**

```
git add frontend/src/features/playlists/routes/PlaylistsListPage.tsx frontend/src/features/playlists/components/PlaylistRow.tsx frontend/src/features/playlists/components/PlaylistsTable.tsx frontend/src/features/playlists/components/DriftBadge.tsx frontend/src/features/playlists/routes/__tests__/PlaylistsListPage.test.tsx
git commit -m "feat(playlists): add list page with create/delete flow"
```

---

## Task 15: CoverPicker component + hookup

Cover replace uses `FileButton` from `@mantine/core` (no `@mantine/dropzone` dependency per spec).

**Files:**
- Create: `frontend/src/features/playlists/components/CoverPicker.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/playlists/components/CoverPicker.tsx
import { useRef } from 'react';
import { Avatar, Button, FileButton, Group, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { modals } from '@mantine/modals';
import { IconPhoto, IconUpload, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useUploadCover, MAX_COVER_BYTES } from '../hooks/useUploadCover';
import { useClearCover } from '../hooks/useClearCover';

export interface CoverPickerProps {
  playlistId: string;
  coverUrl: string | null;
}

export function CoverPicker({ playlistId, coverUrl }: CoverPickerProps) {
  const { t } = useTranslation();
  const upload = useUploadCover();
  const clear = useClearCover();
  const resetRef = useRef<() => void>(null);

  async function handleFile(file: File | null) {
    if (!file) return;
    try {
      await upload.mutateAsync({ playlistId, file });
      notifications.show({ message: t('playlists.toast.cover_saved'), color: 'green' });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg === 'cover_too_large' || msg.includes('cover_too_large')) {
        notifications.show({ message: t('playlists.toast.cover_too_large'), color: 'red' });
      } else if (msg === 'unsupported_content_type') {
        notifications.show({ message: t('playlists.toast.cover_unsupported'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.cover_failed'), color: 'red' });
      }
    } finally {
      resetRef.current?.();
    }
  }

  function handleRemove() {
    modals.openConfirmModal({
      title: t('playlists.cover.remove'),
      labels: {
        confirm: t('playlists.cover.remove'),
        cancel: t('playlists.form.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await clear.mutateAsync(playlistId);
          notifications.show({ message: t('playlists.toast.cover_removed'), color: 'green' });
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  return (
    <Stack gap="xs" align="center">
      <Avatar
        src={coverUrl}
        alt={t('playlists.cover.placeholder_alt')}
        size={160}
        radius="md"
        color="gray"
      >
        <IconPhoto size={48} />
      </Avatar>
      <Group gap="xs" wrap="nowrap">
        <FileButton
          accept="image/jpeg,image/png"
          onChange={handleFile}
          resetRef={resetRef}
        >
          {(props) => (
            <Button
              {...props}
              leftSection={<IconUpload size={14} />}
              variant="default"
              size="xs"
              loading={upload.isPending}
            >
              {t('playlists.cover.replace')}
            </Button>
          )}
        </FileButton>
        {coverUrl ? (
          <Button
            leftSection={<IconTrash size={14} />}
            variant="default"
            color="red"
            size="xs"
            onClick={handleRemove}
            loading={clear.isPending}
          >
            {t('playlists.cover.remove')}
          </Button>
        ) : null}
      </Group>
      <Text size="xs" c="dimmed">
        {t('playlists.cover.help_text')} ({Math.floor(MAX_COVER_BYTES / 1024)} KB)
      </Text>
    </Stack>
  );
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/components/CoverPicker.tsx
git commit -m "feat(playlists): add CoverPicker"
```

---

## Task 16: PlaylistMetaPanel (header with inline-edit + cover slot)

**Files:**
- Create: `frontend/src/features/playlists/components/PlaylistMetaPanel.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/playlists/components/PlaylistMetaPanel.tsx
import { useState } from 'react';
import {
  ActionIcon,
  Group,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { IconCheck, IconPencil, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { Playlist } from '../lib/playlistTypes';
import { playlistNameSchema, playlistDescriptionSchema } from '../lib/playlistSchemas';
import { CoverPicker } from './CoverPicker';

export interface PlaylistMetaPanelProps {
  playlist: Playlist;
  onPatch: (input: { name?: string; description?: string | null; is_public?: boolean }) => Promise<void>;
  publishSlot?: React.ReactNode;
}

export function PlaylistMetaPanel({
  playlist,
  onPatch,
  publishSlot,
}: PlaylistMetaPanelProps) {
  const { t } = useTranslation();
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(playlist.name);
  const [nameError, setNameError] = useState<string | undefined>();
  const [editingDescription, setEditingDescription] = useState(false);
  const [descDraft, setDescDraft] = useState(playlist.description ?? '');
  const [descError, setDescError] = useState<string | undefined>();

  async function commitName() {
    const parsed = playlistNameSchema.safeParse(nameDraft);
    if (!parsed.success) {
      setNameError(t('playlists.errors.name_too_long'));
      return;
    }
    setNameError(undefined);
    setEditingName(false);
    try {
      await onPatch({ name: parsed.data });
    } catch {
      setNameDraft(playlist.name);
    }
  }
  function cancelName() {
    setNameDraft(playlist.name);
    setNameError(undefined);
    setEditingName(false);
  }

  async function commitDescription() {
    const value = descDraft.trim() === '' ? null : descDraft.trim();
    const parsed = playlistDescriptionSchema.safeParse(value);
    if (!parsed.success) {
      setDescError(t('playlists.errors.description_too_long'));
      return;
    }
    setDescError(undefined);
    setEditingDescription(false);
    try {
      await onPatch({ description: parsed.data });
    } catch {
      setDescDraft(playlist.description ?? '');
    }
  }
  function cancelDescription() {
    setDescDraft(playlist.description ?? '');
    setDescError(undefined);
    setEditingDescription(false);
  }

  async function togglePublic(checked: boolean) {
    try {
      await onPatch({ is_public: checked });
    } catch {
      // Mantine Switch is uncontrolled visually here; failure rolls back
      // via the parent's onPatch (which uses optimistic update). Nothing
      // to do explicitly.
    }
  }

  return (
    <Group align="flex-start" gap="lg" wrap="nowrap">
      <CoverPicker playlistId={playlist.id} coverUrl={playlist.cover_url} />
      <Stack gap="sm" flex={1}>
        {editingName ? (
          <Group gap="xs" wrap="nowrap">
            <TextInput
              value={nameDraft}
              onChange={(e) => setNameDraft(e.currentTarget.value)}
              maxLength={100}
              error={nameError}
              autoFocus
              flex={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void commitName();
                if (e.key === 'Escape') cancelName();
              }}
            />
            <ActionIcon variant="subtle" onClick={() => void commitName()} aria-label="Save name">
              <IconCheck size={18} />
            </ActionIcon>
            <ActionIcon variant="subtle" onClick={cancelName} aria-label="Cancel">
              <IconX size={18} />
            </ActionIcon>
          </Group>
        ) : (
          <Group gap="xs" wrap="nowrap">
            <Title order={1}>{playlist.name}</Title>
            <Tooltip label={t('playlists.form.rename_title')} withinPortal>
              <ActionIcon
                variant="subtle"
                onClick={() => setEditingName(true)}
                aria-label={t('playlists.form.rename_title')}
              >
                <IconPencil size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}

        {editingDescription ? (
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Textarea
              value={descDraft}
              onChange={(e) => setDescDraft(e.currentTarget.value)}
              maxLength={300}
              autosize
              minRows={2}
              maxRows={6}
              error={descError}
              autoFocus
              flex={1}
            />
            <ActionIcon variant="subtle" onClick={() => void commitDescription()} aria-label="Save description">
              <IconCheck size={18} />
            </ActionIcon>
            <ActionIcon variant="subtle" onClick={cancelDescription} aria-label="Cancel">
              <IconX size={18} />
            </ActionIcon>
          </Group>
        ) : (
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Text c="dimmed" style={{ minHeight: 24 }} flex={1}>
              {playlist.description ?? '—'}
            </Text>
            <Tooltip label={t('playlists.form.edit_description_title')} withinPortal>
              <ActionIcon
                variant="subtle"
                onClick={() => setEditingDescription(true)}
                aria-label={t('playlists.form.edit_description_title')}
              >
                <IconPencil size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}

        <Switch
          label={t('playlists.form.is_public_label')}
          checked={playlist.is_public}
          onChange={(e) => void togglePublic(e.currentTarget.checked)}
        />

        <Text c="dimmed" size="sm">
          {t('playlists.detail.stats', {
            count: playlist.track_count,
            when: playlist.updated_at.slice(0, 10),
          })}
        </Text>

        {publishSlot ? <div>{publishSlot}</div> : null}
      </Stack>
    </Group>
  );
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/components/PlaylistMetaPanel.tsx
git commit -m "feat(playlists): add PlaylistMetaPanel"
```

---

## Task 17: OriginBadge + PlaylistTrackRow + PlaylistTracksList

The track row is sortable (dnd-kit) and renders the origin badge only when the track came from Spotify (per Q4 brainstorm answer).

**Files:**
- Create: `frontend/src/features/playlists/components/OriginBadge.tsx`
- Create: `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`
- Create: `frontend/src/features/playlists/components/PlaylistTrackRowActions.tsx`
- Create: `frontend/src/features/playlists/components/PlaylistTracksList.tsx`

- [ ] **Step 1: Implement `OriginBadge`**

```tsx
// frontend/src/features/playlists/components/OriginBadge.tsx
import { Badge } from '@mantine/core';
import { IconBrandSpotify } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrackOrigin } from '../lib/playlistTypes';

export function OriginBadge({ origin }: { origin: PlaylistTrackOrigin }) {
  const { t } = useTranslation();
  if (origin !== 'spotify') return null;
  return (
    <Badge color="green" leftSection={<IconBrandSpotify size={12} />} size="sm" variant="light">
      {t('playlists.origin.spotify')}
    </Badge>
  );
}
```

- [ ] **Step 2: Implement `PlaylistTrackRowActions`**

```tsx
// frontend/src/features/playlists/components/PlaylistTrackRowActions.tsx
import { ActionIcon, Menu } from '@mantine/core';
import { IconDotsVertical } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export interface PlaylistTrackRowActionsProps {
  onRemove: () => void;
}

export function PlaylistTrackRowActions({ onRemove }: PlaylistTrackRowActionsProps) {
  const { t } = useTranslation();
  return (
    <Menu withinPortal={false} transitionProps={{ duration: 0 }}>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label="Track actions">
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item color="red" onClick={onRemove}>
          {t('categories.row_actions.remove_label')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
```

- [ ] **Step 3: Implement `PlaylistTrackRow`**

```tsx
// frontend/src/features/playlists/components/PlaylistTrackRow.tsx
import { ActionIcon, Group, Text } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { IconExternalLink, IconGripVertical } from '@tabler/icons-react';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { OriginBadge } from './OriginBadge';
import { PlaylistTrackRowActions } from './PlaylistTrackRowActions';

export interface PlaylistTrackRowProps {
  track: PlaylistTrack;
  position: number;
  onRemove: (track: PlaylistTrack) => void;
}

function formatDuration(ms: number | null): string {
  if (!ms || ms <= 0) return '';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function PlaylistTrackRow({ track, position, onRemove }: PlaylistTrackRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: track.track_id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    borderRadius: 'var(--mantine-radius-md)',
  };

  return (
    <Group
      ref={setNodeRef}
      style={style}
      gap="sm"
      wrap="nowrap"
      p="sm"
      bg="var(--color-bg-elevated)"
      bd="1px solid var(--color-border)"
    >
      <ActionIcon
        variant="subtle"
        aria-label="Drag handle"
        {...attributes}
        {...listeners}
        aria-roledescription="sortable"
        style={{ cursor: 'grab', touchAction: 'none' }}
      >
        <IconGripVertical size={18} />
      </ActionIcon>
      <Text fw={500} size="sm" style={{ minWidth: 32 }}>
        {position}.
      </Text>
      <Text flex={1} truncate>
        {track.title}
      </Text>
      <Text c="dimmed" size="sm">
        {formatDuration(track.length_ms)}
      </Text>
      <OriginBadge origin={track.origin} />
      {track.spotify_id ? (
        <ActionIcon
          component="a"
          href={`https://open.spotify.com/track/${track.spotify_id}`}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          aria-label="Open in Spotify"
        >
          <IconExternalLink size={16} />
        </ActionIcon>
      ) : null}
      <PlaylistTrackRowActions onRemove={() => onRemove(track)} />
    </Group>
  );
}
```

- [ ] **Step 4: Implement `PlaylistTracksList`**

```tsx
// frontend/src/features/playlists/components/PlaylistTracksList.tsx
import { useMemo } from 'react';
import { Stack } from '@mantine/core';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { PlaylistTrackRow } from './PlaylistTrackRow';

export interface PlaylistTracksListProps {
  tracks: PlaylistTrack[];
  onReorder: (orderedIds: string[]) => void;
  onRemove: (track: PlaylistTrack) => void;
}

export function PlaylistTracksList({ tracks, onReorder, onRemove }: PlaylistTracksListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => tracks.map((t) => t.track_id), [tracks]);

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    onReorder(arrayMove(ids, oldIndex, newIndex));
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <Stack gap="xs">
          {tracks.map((t, i) => (
            <PlaylistTrackRow
              key={t.track_id}
              track={t}
              position={i + 1}
              onRemove={onRemove}
            />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
}
```

- [ ] **Step 5: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 6: Commit**

```
git add frontend/src/features/playlists/components/OriginBadge.tsx frontend/src/features/playlists/components/PlaylistTrackRowActions.tsx frontend/src/features/playlists/components/PlaylistTrackRow.tsx frontend/src/features/playlists/components/PlaylistTracksList.tsx
git commit -m "feat(playlists): add sortable track list components"
```

---

## Task 18: AddTracksModal

**Files:**
- Create: `frontend/src/features/playlists/components/AddTracksModal.tsx`

Reuses existing categories hooks (`useStyles`, `useCategoriesByStyle`, `useCategoryTracks`).

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/playlists/components/AddTracksModal.tsx
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../../../hooks/useStyles';
import { useCategoriesByStyle } from '../../categories/hooks/useCategoriesByStyle';
import { useCategoryTracks } from '../../categories/hooks/useCategoryTracks';
import { useAddTracksToPlaylist } from '../hooks/useAddTracksToPlaylist';
import { notifications } from '@mantine/notifications';

export interface AddTracksModalProps {
  opened: boolean;
  onClose: () => void;
  playlistId: string;
  onAdded: () => void;
}

export function AddTracksModal({ opened, onClose, playlistId, onAdded }: AddTracksModalProps) {
  const { t } = useTranslation();
  const stylesQ = useStyles();
  const [styleId, setStyleId] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const categoriesQ = useCategoriesByStyle(styleId ?? '');
  const tracksQ = useCategoryTracks(categoryId ?? '', '', 'added_at', 'desc', [], 'any');
  const addMut = useAddTracksToPlaylist();

  useEffect(() => {
    if (!opened) {
      setStyleId(null);
      setCategoryId(null);
      setSearch('');
      setSelected(new Set());
    }
  }, [opened]);

  const trackItems = (tracksQ.data?.pages ?? []).flatMap((p) => p.items);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return trackItems;
    return trackItems.filter((tr) => tr.title.toLowerCase().includes(q));
  }, [trackItems, search]);

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function handleSubmit() {
    if (selected.size === 0) return;
    try {
      const res = await addMut.mutateAsync({
        playlistId,
        trackIds: Array.from(selected),
      });
      notifications.show({
        message: t('playlists.toast.tracks_added', { count: res.added.length }),
        color: 'green',
      });
      onAdded();
      onClose();
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={t('playlists.add_tracks.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Group gap="sm" grow>
          <Select
            label={t('playlists.add_tracks.style_label')}
            data={(stylesQ.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))}
            value={styleId}
            onChange={(v) => {
              setStyleId(v);
              setCategoryId(null);
            }}
          />
          <Select
            label={t('playlists.add_tracks.category_label')}
            data={(categoriesQ.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))}
            value={categoryId}
            onChange={setCategoryId}
            disabled={!styleId}
          />
        </Group>
        <TextInput
          placeholder={t('playlists.add_tracks.search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          disabled={!categoryId}
        />
        <ScrollArea h={320}>
          <Stack gap={4}>
            {!categoryId ? null : filtered.length === 0 ? (
              <Text c="dimmed">{t('playlists.add_tracks.empty_category')}</Text>
            ) : (
              filtered.map((tr) => (
                <Checkbox
                  key={tr.id}
                  label={tr.title}
                  checked={selected.has(tr.id)}
                  onChange={() => toggle(tr.id)}
                />
              ))
            )}
          </Stack>
        </ScrollArea>
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {t('playlists.add_tracks.selected_count', { count: selected.size })}
          </Text>
          <Group gap="sm">
            <Button variant="default" onClick={onClose} disabled={addMut.isPending}>
              {t('playlists.form.cancel')}
            </Button>
            <Button
              onClick={() => void handleSubmit()}
              loading={addMut.isPending}
              disabled={selected.size === 0}
            >
              {t('playlists.add_tracks.submit', { count: selected.size })}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
```

Note: if `useCategoryTracks` signature drifts, run `cat frontend/src/features/categories/hooks/useCategoryTracks.ts` and adjust the arg list — but do not redesign the hook.

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/components/AddTracksModal.tsx
git commit -m "feat(playlists): add AddTracksModal for cross-category picker"
```

---

## Task 19: ImportSpotifyModal

**Files:**
- Create: `frontend/src/features/playlists/components/ImportSpotifyModal.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/playlists/components/ImportSpotifyModal.tsx
import { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  List,
  Modal,
  Stack,
  Textarea,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { parseSpotifyRef, InvalidSpotifyRefError } from '../lib/spotifyRefParse';
import { useImportSpotifyTracks } from '../hooks/useImportSpotifyTracks';
import { ApiError } from '../../../api/error';
import type { ImportSpotifyResult } from '../lib/playlistTypes';

const MAX_REFS = 50;

export interface ImportSpotifyModalProps {
  opened: boolean;
  onClose: () => void;
  playlistId: string;
}

interface RefValidation {
  raw: string;
  valid: boolean;
}

function validateRefs(text: string): RefValidation[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((raw) => {
      try {
        parseSpotifyRef(raw);
        return { raw, valid: true };
      } catch (e) {
        if (e instanceof InvalidSpotifyRefError) return { raw, valid: false };
        return { raw, valid: false };
      }
    });
}

export function ImportSpotifyModal({ opened, onClose, playlistId }: ImportSpotifyModalProps) {
  const { t } = useTranslation();
  const importMut = useImportSpotifyTracks();
  const [text, setText] = useState('');
  const [result, setResult] = useState<ImportSpotifyResult | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const lines = useMemo(() => validateRefs(text), [text]);
  const validCount = lines.filter((l) => l.valid).length;
  const tooMany = lines.length > MAX_REFS;
  const canSubmit = validCount > 0 && !tooMany;

  async function handleSubmit() {
    setServerError(null);
    const refs = lines.filter((l) => l.valid).map((l) => l.raw);
    try {
      const r = await importMut.mutateAsync({ playlistId, spotifyRefs: refs });
      setResult(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setServerError(t('playlists.errors.spotify_not_authorized'));
      } else if (err instanceof ApiError && err.status === 502) {
        setServerError(t('playlists.errors.spotify_upstream_error'));
      } else {
        setServerError(t('playlists.toast.generic_error'));
      }
    }
  }

  function handleClose() {
    setText('');
    setResult(null);
    setServerError(null);
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      size="lg"
      title={t('playlists.import.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        {serverError ? (
          <Alert color="red" icon={<IconAlertTriangle size={16} />}>
            {serverError}
          </Alert>
        ) : null}
        <Textarea
          label={t('playlists.import.textarea_label')}
          placeholder={t('playlists.import.textarea_placeholder')}
          autosize
          minRows={5}
          maxRows={12}
          value={text}
          onChange={(e) => setText(e.currentTarget.value)}
        />
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {lines.length === 0
              ? ''
              : tooMany
                ? t('playlists.import.max_exceeded')
                : `${validCount}/${lines.length} valid`}
          </Text>
          <Button
            onClick={() => void handleSubmit()}
            loading={importMut.isPending}
            disabled={!canSubmit}
          >
            {t('playlists.import.submit')}
          </Button>
        </Group>

        {result ? (
          <Stack gap="xs">
            <Title order={5}>{t('playlists.import.added', { count: result.added.length })}</Title>
            <List size="sm">
              {result.added.map((a) => (
                <List.Item key={a.track_id}>{a.title}</List.Item>
              ))}
            </List>
            {result.skipped.length > 0 ? (
              <>
                <Title order={5}>{t('playlists.import.skipped', { count: result.skipped.length })}</Title>
                <List size="sm">
                  {result.skipped.map((s, i) => (
                    <List.Item key={`${s.ref}-${i}`}>
                      <Text size="sm" inherit>
                        {s.ref} — {t(`playlists.import.reason_${s.reason}`)}
                      </Text>
                    </List.Item>
                  ))}
                </List>
              </>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/components/ImportSpotifyModal.tsx
git commit -m "feat(playlists): add ImportSpotifyModal"
```

---

## Task 20: PublishButton + PublishConfirmModal + PublishResultModal

**Files:**
- Create: `frontend/src/features/playlists/components/PublishConfirmModal.tsx`
- Create: `frontend/src/features/playlists/components/PublishResultModal.tsx`
- Create: `frontend/src/features/playlists/components/PublishButton.tsx`

- [ ] **Step 1: Implement `PublishConfirmModal`**

```tsx
// frontend/src/features/playlists/components/PublishConfirmModal.tsx
import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface PublishConfirmModalProps {
  opened: boolean;
  onClose: () => void;
  onConfirm: () => void;
  playlistName: string;
  trackCount: number;
  loading: boolean;
}

export function PublishConfirmModal({
  opened,
  onClose,
  onConfirm,
  playlistName,
  trackCount,
  loading,
}: PublishConfirmModalProps) {
  const { t } = useTranslation();
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.confirm_title')}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>
          {t('playlists.publish.confirm_body', { name: playlistName, count: trackCount })}
        </Text>
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={loading}>
            {t('playlists.publish.cancel')}
          </Button>
          <Button color="red" onClick={onConfirm} loading={loading}>
            {t('playlists.publish.confirm_cta')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 2: Implement `PublishResultModal`**

```tsx
// frontend/src/features/playlists/components/PublishResultModal.tsx
import { Anchor, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PublishResult } from '../lib/playlistTypes';

export interface PublishResultModalProps {
  opened: boolean;
  onClose: () => void;
  result: PublishResult | null;
}

export function PublishResultModal({ opened, onClose, result }: PublishResultModalProps) {
  const { t } = useTranslation();
  if (!result) return null;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.result_skipped_title', { count: result.skipped_tracks.length })}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>{t('playlists.publish.result_skipped_body')}</Text>
        <List size="sm">
          {result.skipped_tracks.map((s) => (
            <List.Item key={s.track_id}>
              {s.title} — {s.reason}
            </List.Item>
          ))}
        </List>
        <Group justify="space-between">
          <Anchor href={result.spotify_url} target="_blank" rel="noopener noreferrer">
            {t('playlists.publish.open_in_spotify')}
          </Anchor>
          <Button onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 3: Implement `PublishButton`**

```tsx
// frontend/src/features/playlists/components/PublishButton.tsx
import { useState } from 'react';
import { Anchor, Button, Group } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconBrandSpotify } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import type { Playlist, PublishResult } from '../lib/playlistTypes';
import { usePublishPlaylist } from '../hooks/usePublishPlaylist';
import { PublishConfirmModal } from './PublishConfirmModal';
import { PublishResultModal } from './PublishResultModal';
import { DriftBadge } from './DriftBadge';

export interface PublishButtonProps {
  playlist: Playlist;
}

export function PublishButton({ playlist }: PublishButtonProps) {
  const { t } = useTranslation();
  const publishMut = usePublishPlaylist();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resultModal, setResultModal] = useState<PublishResult | null>(null);

  const alreadyPublished = !!playlist.spotify_playlist_id;

  function handleClick() {
    if (alreadyPublished) {
      setConfirmOpen(true);
    } else {
      void doPublish(false);
    }
  }

  async function doPublish(confirmOverwrite: boolean) {
    try {
      const r = await publishMut.mutateAsync({
        playlistId: playlist.id,
        confirmOverwrite,
      });
      setConfirmOpen(false);
      notifications.show({
        color: 'green',
        message: (
          <Group gap="sm">
            <span>
              {alreadyPublished
                ? t('playlists.toast.published_again')
                : t('playlists.toast.published_first')}
            </span>
            <Anchor href={r.spotify_url} target="_blank" rel="noopener noreferrer">
              {t('playlists.publish.open_in_spotify')}
            </Anchor>
          </Group>
        ),
      });
      if (r.cover_failed) {
        notifications.show({ message: t('playlists.publish.cover_failed'), color: 'yellow' });
      }
      if (r.skipped_tracks.length > 0) {
        setResultModal(r);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && err.code === 'confirm_overwrite_required') {
        notifications.show({
          message: t('playlists.errors.confirm_overwrite_required'),
          color: 'yellow',
        });
        setConfirmOpen(true);
      } else if (err instanceof ApiError && err.status === 412) {
        notifications.show({
          message: t('playlists.errors.spotify_not_authorized'),
          color: 'red',
        });
      } else if (err instanceof ApiError && err.status === 502) {
        notifications.show({
          message: t('playlists.errors.spotify_upstream_error'),
          color: 'red',
        });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <>
      <Group gap="sm" align="center">
        <Button
          leftSection={<IconBrandSpotify size={16} />}
          color="green"
          loading={publishMut.isPending}
          onClick={handleClick}
        >
          {alreadyPublished ? t('playlists.publish.again') : t('playlists.publish.first')}
        </Button>
        {playlist.needs_republish ? <DriftBadge /> : null}
      </Group>
      <PublishConfirmModal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void doPublish(true)}
        playlistName={playlist.name}
        trackCount={playlist.track_count}
        loading={publishMut.isPending}
      />
      <PublishResultModal
        opened={resultModal !== null}
        onClose={() => setResultModal(null)}
        result={resultModal}
      />
    </>
  );
}
```

- [ ] **Step 4: Typecheck**

```
pnpm -C frontend typecheck
```

- [ ] **Step 5: Commit**

```
git add frontend/src/features/playlists/components/PublishConfirmModal.tsx frontend/src/features/playlists/components/PublishResultModal.tsx frontend/src/features/playlists/components/PublishButton.tsx
git commit -m "feat(playlists): add publish button + confirm/result modals"
```

---

## Task 21: Detail page assembly

**Files:**
- Modify: `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` (replace placeholder)
- Create: `frontend/src/features/playlists/routes/__tests__/PlaylistDetailPage.test.tsx`

- [ ] **Step 1: Implement the page**

```tsx
// frontend/src/features/playlists/routes/PlaylistDetailPage.tsx
import { useMemo, useState } from 'react';
import { Anchor, Breadcrumbs, Button, Group, Stack, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconBrandSpotify, IconPlus, IconSearch } from '@tabler/icons-react';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { usePlaylistDetail } from '../hooks/usePlaylistDetail';
import { usePlaylistTracks } from '../hooks/usePlaylistTracks';
import { usePatchPlaylist } from '../hooks/usePatchPlaylist';
import { useDeletePlaylist } from '../hooks/useDeletePlaylist';
import { useRemoveTrackFromPlaylist } from '../hooks/useRemoveTrackFromPlaylist';
import { useReorderPlaylistTracks } from '../hooks/useReorderPlaylistTracks';
import { PlaylistMetaPanel } from '../components/PlaylistMetaPanel';
import { PlaylistTracksList } from '../components/PlaylistTracksList';
import { PublishButton } from '../components/PublishButton';
import { AddTracksModal } from '../components/AddTracksModal';
import { ImportSpotifyModal } from '../components/ImportSpotifyModal';
import { playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedPlaylistTracks, PlaylistTrack } from '../lib/playlistTypes';

export function PlaylistDetailPage() {
  const { id } = useParams<{ id: string }>();
  if (!id) return <Navigate to="/playlists" replace />;
  return <PlaylistDetailPageInner id={id} />;
}

function PlaylistDetailPageInner({ id }: { id: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const detailQ = usePlaylistDetail(id);
  const tracksQ = usePlaylistTracks(id);
  const patchMut = usePatchPlaylist(id);
  const deleteMut = useDeletePlaylist();
  const removeTrackMut = useRemoveTrackFromPlaylist();
  const reorder = useReorderPlaylistTracks(id);

  const [search, setSearch] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const tracks = tracksQ.data?.items ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tracks;
    return tracks.filter((tr) => tr.title.toLowerCase().includes(q));
  }, [tracks, search]);

  async function handlePatch(input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) {
    try {
      await patchMut.mutateAsync(input);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        notifications.show({ message: t('playlists.errors.name_conflict'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
      throw err;
    }
  }

  function handleReorder(orderedIds: string[]) {
    const cur = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(id));
    if (!cur) return;
    const byId = new Map(cur.items.map((t) => [t.track_id, t]));
    qc.setQueryData<PaginatedPlaylistTracks>(playlistTracksKey(id), {
      ...cur,
      items: orderedIds.map((tid, idx) => ({
        ...(byId.get(tid) as PlaylistTrack),
        position: idx,
      })),
    });
    reorder.queueOrder(orderedIds);
  }

  async function handleRemoveTrack(track: PlaylistTrack) {
    try {
      await removeTrackMut.mutateAsync({ playlistId: id, trackId: track.track_id });
      notifications.show({ message: t('playlists.toast.track_removed'), color: 'green' });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  function openDelete() {
    if (!detailQ.data) return;
    const p = detailQ.data;
    modals.openConfirmModal({
      title: t('playlists.detail.delete_cta'),
      children: p.name,
      labels: { confirm: t('playlists.detail.delete_cta'), cancel: t('playlists.form.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(p.id);
          notifications.show({ message: t('playlists.toast.deleted'), color: 'green' });
          navigate('/playlists');
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  if (detailQ.isLoading) return <FullScreenLoader />;
  if (detailQ.isError) {
    if (detailQ.error instanceof ApiError && detailQ.error.status === 404) {
      return (
        <EmptyState
          title={t('errors.not_found')}
          body={
            <Anchor component={Link} to="/playlists">
              {t('playlists.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  if (!detailQ.data) return null;
  const playlist = detailQ.data;

  return (
    <Stack gap="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/playlists">
          {t('playlists.page_title')}
        </Anchor>
        <span>{playlist.name}</span>
      </Breadcrumbs>

      <PlaylistMetaPanel
        playlist={playlist}
        onPatch={handlePatch}
        publishSlot={
          <Group gap="sm" align="center">
            <PublishButton playlist={playlist} />
            <Button color="red" variant="subtle" onClick={openDelete}>
              {t('playlists.detail.delete_cta')}
            </Button>
          </Group>
        }
      />

      <Group gap="sm" wrap="wrap">
        <Button leftSection={<IconPlus size={16} />} onClick={() => setAddOpen(true)}>
          {t('playlists.detail.add_tracks_cta')}
        </Button>
        <Button
          leftSection={<IconBrandSpotify size={16} />}
          variant="default"
          onClick={() => setImportOpen(true)}
        >
          {t('playlists.detail.import_spotify_cta')}
        </Button>
        <TextInput
          placeholder={t('playlists.detail.tracks_search_placeholder')}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
        />
      </Group>

      {tracks.length === 0 ? (
        <EmptyState
          title={t('playlists.detail.empty_tracks_title')}
          body={t('playlists.detail.empty_tracks_body')}
        />
      ) : (
        <PlaylistTracksList
          tracks={filtered}
          onReorder={handleReorder}
          onRemove={handleRemoveTrack}
        />
      )}

      <AddTracksModal
        opened={addOpen}
        onClose={() => setAddOpen(false)}
        playlistId={id}
        onAdded={() => {
          /* invalidations happen inside the hook */
        }}
      />
      <ImportSpotifyModal
        opened={importOpen}
        onClose={() => setImportOpen(false)}
        playlistId={id}
      />
    </Stack>
  );
}
```

- [ ] **Step 2: Write the route test**

```tsx
// frontend/src/features/playlists/routes/__tests__/PlaylistDetailPage.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { PlaylistDetailPage } from '../PlaylistDetailPage';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/playlists/p1']}>
            <Routes>
              <Route path="/playlists/:id" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

const seedPlaylist = {
  id: 'p1',
  user_id: 'u1',
  name: 'Saturday techno',
  description: 'rolling weekly mix',
  is_public: false,
  cover_s3_key: null,
  cover_url: null,
  cover_uploaded_at: null,
  spotify_playlist_id: null,
  last_published_at: null,
  needs_republish: false,
  track_count: 1,
  created_at: '2026-05-12T00:00:00Z',
  updated_at: '2026-05-12T00:00:00Z',
};

const seedTracks = {
  items: [
    {
      track_id: 't1',
      position: 0,
      added_at: '2026-05-12T00:00:00Z',
      title: 'Test Track',
      spotify_id: null,
      isrc: null,
      length_ms: 222_000,
      origin: 'beatport' as const,
    },
  ],
  total: 1,
  limit: 200,
  offset: 0,
};

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/playlists/p1', () => HttpResponse.json(seedPlaylist)),
    http.get('http://localhost/playlists/p1/tracks', () => HttpResponse.json(seedTracks)),
  );
});

describe('PlaylistDetailPage', () => {
  it('renders title, stats, and the single track row', async () => {
    render(
      <Wrapper>
        <PlaylistDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Saturday techno')).toBeInTheDocument());
    expect(await screen.findByText('Test Track')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Publish to Spotify/i })).toBeInTheDocument();
  });

  it('renders Re-publish + drift badge when already published and dirty', async () => {
    server.use(
      http.get('http://localhost/playlists/p1', () =>
        HttpResponse.json({
          ...seedPlaylist,
          spotify_playlist_id: 'sp1',
          last_published_at: '2026-05-12T00:00:00Z',
          needs_republish: true,
        }),
      ),
    );
    render(
      <Wrapper>
        <PlaylistDetailPage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Re-publish to Spotify/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/Needs republish/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the tests**

```
pnpm -C frontend test -- src/features/playlists/routes/__tests__/PlaylistDetailPage.test.tsx
```

Expected: PASS, 2/2.

- [ ] **Step 4: Commit**

```
git add frontend/src/features/playlists/routes/PlaylistDetailPage.tsx frontend/src/features/playlists/routes/__tests__/PlaylistDetailPage.test.tsx
git commit -m "feat(playlists): assemble PlaylistDetailPage"
```

---

## Task 22: Cross-feature `Add to playlist` submenu

**Files:**
- Create: `frontend/src/features/categories/components/AddToPlaylistSubmenu.tsx`
- Create: `frontend/src/features/categories/components/__tests__/AddToPlaylistSubmenu.test.tsx`
- Modify: `frontend/src/features/categories/components/TrackRowActions.tsx`

- [ ] **Step 1: Implement the submenu component**

```tsx
// frontend/src/features/categories/components/AddToPlaylistSubmenu.tsx
import { Anchor, Loader, Menu, Text } from '@mantine/core';
import { Link } from 'react-router';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';

export interface AddToPlaylistSubmenuProps {
  trackId: string;
}

export function AddToPlaylistSubmenu({ trackId }: AddToPlaylistSubmenuProps) {
  const { t } = useTranslation();
  // Always-enabled — Menu controls render eagerly; cost is one /playlists
  // GET per category page mount with stale cache reuse across rows.
  const q = usePlaylists({ limit: 100 });
  const addMut = useAddTracksToPlaylist();

  async function handleAdd(playlistId: string, playlistName: string) {
    try {
      await addMut.mutateAsync({ playlistId, trackIds: [trackId] });
      notifications.show({
        message: t('playlists.toast.track_added', { name: playlistName }),
        color: 'green',
      });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <>
      <Menu.Label>{t('categories.row_actions.add_to_playlist_label')}</Menu.Label>
      {q.isLoading ? (
        <Menu.Item disabled leftSection={<Loader size={12} />}>
          {t('categories.row_actions.loading')}
        </Menu.Item>
      ) : (q.data?.items.length ?? 0) === 0 ? (
        <>
          <Menu.Item disabled>{t('categories.row_actions.add_to_playlist_empty')}</Menu.Item>
          <Menu.Item>
            <Anchor component={Link} to="/playlists" td="none">
              <Text size="sm">{t('categories.row_actions.manage_playlists')}</Text>
            </Anchor>
          </Menu.Item>
        </>
      ) : (
        q.data!.items.map((p) => (
          <Menu.Item key={p.id} onClick={() => void handleAdd(p.id, p.name)}>
            {p.name}
          </Menu.Item>
        ))
      )}
    </>
  );
}
```

- [ ] **Step 2: Inject into `TrackRowActions.tsx`**

Open `frontend/src/features/categories/components/TrackRowActions.tsx`. The file currently has a `Menu.Dropdown` with the "Move to category" label/items, a `Menu.Divider`, and a red "Remove" item. Wrap the existing Move section in its own block and add the submenu BEFORE the divider:

```tsx
import { AddToPlaylistSubmenu } from './AddToPlaylistSubmenu';

// inside <Menu.Dropdown>:
<Menu.Label>
  {/* existing move label logic */}
</Menu.Label>
{/* existing move items */}

<Menu.Divider />
<AddToPlaylistSubmenu trackId={track.id} />

<Menu.Divider />
<Menu.Item color="red" onClick={handleRemove}>
  {t('categories.row_actions.remove_label')}
</Menu.Item>
```

Implementation note: do not eagerly load the submenu's playlists query outside the menu. Mantine renders `Menu.Dropdown` content lazily by default, so the `usePlaylists` query fires only when the menu opens. If you find it fires earlier, gate the inner JSX behind a `useState` controlled-open flag.

- [ ] **Step 3: Write submenu test**

```tsx
// frontend/src/features/categories/components/__tests__/AddToPlaylistSubmenu.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Menu } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { AddToPlaylistSubmenu } from '../AddToPlaylistSubmenu';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

const seedPlaylists = {
  items: [
    {
      id: 'p1',
      user_id: 'u1',
      name: 'Hot New',
      description: null,
      is_public: false,
      cover_s3_key: null,
      cover_url: null,
      cover_uploaded_at: null,
      spotify_playlist_id: null,
      last_published_at: null,
      needs_republish: false,
      track_count: 0,
      created_at: '2026-05-12T00:00:00Z',
      updated_at: '2026-05-12T00:00:00Z',
    },
  ],
  total: 1,
  limit: 100,
  offset: 0,
};

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/playlists', () => HttpResponse.json(seedPlaylists)),
  );
});

describe('AddToPlaylistSubmenu', () => {
  it('lists user playlists inside an open Menu', async () => {
    render(
      <Wrapper>
        <Menu>
          <Menu.Target>
            <button>open</button>
          </Menu.Target>
          <Menu.Dropdown>
            <AddToPlaylistSubmenu trackId="t1" />
          </Menu.Dropdown>
        </Menu>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    const menu = await screen.findByRole('menu');
    await waitFor(() => expect(within(menu).getByText('Hot New')).toBeInTheDocument());
  });

  it('posts to /playlists/p1/tracks when an item is clicked', async () => {
    let posted: { track_ids: string[] } | null = null;
    server.use(
      http.post('http://localhost/playlists/p1/tracks', async ({ request }) => {
        posted = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json(
          { added: ['t1'], skipped_duplicates: [], position_after: 1 },
          { status: 201 },
        );
      }),
    );
    render(
      <Wrapper>
        <Menu>
          <Menu.Target>
            <button>open</button>
          </Menu.Target>
          <Menu.Dropdown>
            <AddToPlaylistSubmenu trackId="t1" />
          </Menu.Dropdown>
        </Menu>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(await within(menu).findByText('Hot New'));
    await waitFor(() => expect(posted).toEqual({ track_ids: ['t1'] }));
  });
});
```

- [ ] **Step 4: Run the test**

```
pnpm -C frontend test -- src/features/categories/components/__tests__/AddToPlaylistSubmenu.test.tsx
```

Expected: PASS, 2/2.

- [ ] **Step 5: Re-run the full suite — ensure existing `TrackRowActions` tests still pass**

```
pnpm -C frontend test -- --run
```

Expected: every previously passing test still passes (the existing `TrackRowActions` test must continue to render and assert on the move/remove flow).

- [ ] **Step 6: Commit**

```
git add frontend/src/features/categories/components/AddToPlaylistSubmenu.tsx frontend/src/features/categories/components/__tests__/AddToPlaylistSubmenu.test.tsx frontend/src/features/categories/components/TrackRowActions.tsx
git commit -m "feat(categories): add 'Add to playlist' submenu"
```

---

## Task 23: Integration smoke test

End-to-end happy path across the feature using MSW.

**Files:**
- Create: `frontend/src/features/playlists/__tests__/integration.playlists.test.tsx`

- [ ] **Step 1: Write the integration test**

```tsx
// frontend/src/features/playlists/__tests__/integration.playlists.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import { PlaylistsListPage } from '../routes/PlaylistsListPage';
import { PlaylistDetailPage } from '../routes/PlaylistDetailPage';
import { testTheme } from '../../../test/theme';

function Wrapper({ children, entries }: { children: React.ReactNode; entries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={entries}>
            <Routes>
              <Route path="/playlists" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
});

describe('Playlists integration smoke', () => {
  it('shows the empty list, opens create dialog, posts a new playlist', async () => {
    const user = userEvent.setup();
    let posted: { name: string } | null = null;
    server.use(
      http.get('http://localhost/playlists', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.post('http://localhost/playlists', async ({ request }) => {
        posted = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: 'p1',
            user_id: 'u1',
            name: posted.name,
            description: null,
            is_public: false,
            cover_s3_key: null,
            cover_url: null,
            cover_uploaded_at: null,
            spotify_playlist_id: null,
            last_published_at: null,
            needs_republish: false,
            track_count: 0,
            created_at: '2026-05-12T00:00:00Z',
            updated_at: '2026-05-12T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );

    render(
      <Wrapper entries={['/playlists']}>
        <PlaylistsListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/No playlists yet/i)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Create playlist/i }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Name'), 'Sunday house');
    await user.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(posted?.name).toBe('Sunday house'));
  });
});
```

- [ ] **Step 2: Run**

```
pnpm -C frontend test -- src/features/playlists/__tests__/integration.playlists.test.tsx
```

Expected: PASS, 1/1.

- [ ] **Step 3: Commit**

```
git add frontend/src/features/playlists/__tests__/integration.playlists.test.tsx
git commit -m "test(playlists): integration smoke"
```

---

## Task 24: Full-suite green + lint pass

- [ ] **Step 1: Lint and fix any remaining issues**

```
pnpm -C frontend lint
```

If lint fails, fix inline (typically unused imports). Re-run until clean.

- [ ] **Step 2: Typecheck**

```
pnpm -C frontend typecheck
```

Expected: no errors.

- [ ] **Step 3: Run the full test suite**

```
pnpm -C frontend test -- --run
```

Expected: every test passes.

- [ ] **Step 4: Manual dev check (browser)**

```
pnpm -C frontend dev
```

Open `http://127.0.0.1:5173/playlists` (after logging in via the existing Spotify flow). Verify:
- List page renders, "Create playlist" works.
- Detail page renders, inline-edit name + description, toggle public switch.
- Cover replace with a small JPEG works end-to-end.
- Add tracks from a category lands them in the playlist.
- Import Spotify with one valid URL adds the track.
- Publish flow surfaces a Spotify URL in the toast (first publish path).

Capture screenshots only if something looks off — otherwise proceed.

- [ ] **Step 5: Final commit (if any cleanup edits happened)**

If steps 1-4 produced any edits:

```
git add -A
git commit -m "chore(playlists): lint + cleanup"
```

Otherwise skip.

---

## Self-Review Notes

- **Spec coverage**: each spec section maps to at least one task —
  - "Routes & Navigation" → Task 12
  - "Feature folder layout" → Tasks 1 + 5 + every implementation task
  - "List page" → Task 14
  - "Detail page" + "Component Designs" → Tasks 13, 15, 16, 17, 18, 19, 20, 21
  - "Cross-feature submenu" → Task 22
  - "Data Flow" / query keys / optimistic updates → Tasks 1, 6, 7, 8
  - "Error Handling Catalog" → covered inline in each component (list/detail pages + import + publish + cover)
  - "Loading / Skeleton States" → `FullScreenLoader` in Tasks 14 + 21
  - "Accessibility" → ariadropdown labels on action icons, drag handle aria, keyboard-driven inline-edit (Enter/Escape)
  - "i18n" → Task 12
  - "Testing Strategy" → Tasks 1, 6, 8, 10, 11, 14, 21, 22, 23
  - "Performance" → `usePlaylistTracks` default `limit=200`, `staleTime` already covered by TanStack defaults (no extra tweaks needed for v1)
  - "Out of scope" honored — no bulk ops, no clone, no server-side track search, no share UI.

- **Placeholder scan**: no `TBD/TODO`, no "implement later", no "similar to Task N". Each task contains complete code blocks.

- **Type consistency**: `Playlist`, `PlaylistTrack`, `PaginatedPlaylists`, `PaginatedPlaylistTracks`, `AddTracksResult`, `ImportSpotifyResult`, `PublishResult`, `CoverUploadUrlResponse` defined in Task 1 and referenced consistently through Tasks 4-23. `playlistsKey` / `playlistDetailKey` / `playlistTracksKey` defined in Task 1 and reused. `useReorderPlaylistTracks` returns `{ queueOrder, flushNow }` consistent with categories pattern; both helper names appear identically in the test and the implementation.

- **One thing the engineer should verify before Task 18**: the exact signature of `useCategoryTracks(categoryId, query, sortKey, sortDir, tagIds, tagMatch)`. The plan uses the live signature observed in `frontend/src/features/categories/components/TracksTab.tsx`; if categories work has refactored it since this plan was written, re-read the hook before wiring `AddTracksModal`.

---

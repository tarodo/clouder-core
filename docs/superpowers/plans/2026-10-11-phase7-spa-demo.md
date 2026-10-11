# Phase 7 — SPA demo on sample data (GitHub Pages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone can try the curation app in a browser — no login, no AWS: `https://tarodo.github.io/clouder-core/demo/` runs the real SPA against an in-memory sample catalog served by MSW, next to the dbt lineage, under one Pages landing page.

**Architecture:** A `demo` Vite mode (`base: /clouder-core/demo/`) starts an MSW service worker before React renders; its handlers serve a deterministic sample catalog from a small in-memory store (`src/demo/`) that keeps real state for the core loop (curate → triage → categories → playlists, tags, styles), static payloads for Home analytics and Admin coverage, 404 for other reads and 403 "Not available in the demo" for other writes. Demo code is reached only through a `MODE === 'demo'` dynamic import, so the production bundle carries none of it. Playback stays off in the demo (the existing "disconnected" player state, with demo wording). One Pages workflow builds the landing page, `/lineage/` (dbt docs, moved from the root) and `/demo/` into a single artifact.

**Tech Stack:** Vite 7, React 19, React Router 7, MSW 2 (`msw/browser`), Vitest 4, GitHub Pages (`actions/deploy-pages`).

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` §0 phase 7 ("Demo-режим SPA на MSW в браузере, общий Pages-артефакт (лендинг, `/lineage`, `/demo`)"), §9 L3 ("Try it with sample data"), §11 P1 "Demo-режим SPA на MSW". Map of the SPA's auth, router, playback and per-page endpoints: gathered 2026-10-11 (see the ledger).

## Global Constraints

- Worktree `<repo>` (`clouder-core-p1`), branch `feat/spa-demo` from `origin/main`.
- Production behaviour and bundle unchanged: every demo branch is `import.meta.env.MODE === 'demo'`; `pnpm build` output contains no `msw` / `mockServiceWorker` string.
- Sample data is invented (names, labels, ids); no production data, no real user, no external image.
- Never answer 401 in the demo (it triggers the refresh loop); `expires_in` = 3600.
- The demo never loads the Spotify SDK or calls `api.spotify.com`.
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **Deep links and F5 on Pages** (`/clouder-core/demo/triage/s-tech/...`) render the app: Pages serves the root `404.html` (a copy of the demo `index.html` with absolute asset URLs) and the router's `basename` matches — checked live in Task 5.
2. **The core loop keeps state across screens**: a track assigned in Curate shows in the destination bucket, finalize promotes STAGING tracks into categories, a track added to a playlist shows there — `db.test.ts` + the live smoke in Task 5.
3. **Unhandled demo calls fail soft**: unknown GET → 404 `not_found` (no retry), unknown write → 403 with a readable message, never 401, never a hang — `handlers.test.ts`.
4. **No demo code in production**: `pnpm build` dist has no `mockServiceWorker`/`msw` — checked in Task 3.
5. **Handlers stay honest to the API**: every demo route exists in `docs/api/openapi.yaml` — `test_demo_routes_exist_in_openapi` (vitest).

---

### Task 1: Sample catalog + in-memory store

**Files:** Create `frontend/src/demo/seed.ts`, `frontend/src/demo/db.ts`, `frontend/src/demo/samples.ts`, `frontend/src/demo/__tests__/db.test.ts`; modify `frontend/src/screenshots/readme.shot.tsx` (import the analytics/coverage/auto-ingest samples from `demo/samples.ts` instead of inline literals — same values).

**Interfaces — Produces:** `buildSeed(): DemoSeed`; `class DemoDb` with the methods used in Task 2 (names below); `class DemoError(status, code, message)`; `samples.ts`: `sampleListening()`, `sampleFunnel()`, `sampleTimePerTrack(days)`, `sampleCoverage(weekYear)`, `sampleAutoIngest()`.

- [ ] **Step 1: Failing tests** `frontend/src/demo/__tests__/db.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { DemoDb, DemoError } from '../db';

const firstOpenBlock = (db: DemoDb) => db.blocksByStyle('s-tech', 'IN_PROGRESS')[0];

describe('DemoDb', () => {
  it('serves three selected styles with an open week each', () => {
    const db = new DemoDb();
    expect(db.styles('mine').map((s) => s.name)).toEqual(['Tech House', 'Melodic House & Techno', 'Afro House']);
    expect(db.styles('all').length).toBeGreaterThan(3);
    for (const s of db.styles('mine')) expect(db.blocksByStyle(s.id, 'IN_PROGRESS')).toHaveLength(1);
  });

  it('moves a track between buckets and keeps the counts', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    const from = block.buckets.find((b) => b.bucket_type === 'NEW')!;
    const to = block.buckets.find((b) => b.bucket_type === 'STAGING')!;
    const [track] = db.bucketTracks(block.id, from.id);
    expect(db.move(block.id, from.id, to.id, [track.track_id])).toBe(1);
    const after = db.block(block.id);
    expect(after.buckets.find((b) => b.id === from.id)!.track_count).toBe(from.track_count - 1);
    expect(after.buckets.find((b) => b.id === to.id)!.track_count).toBe(to.track_count + 1);
    expect(db.bucketTracks(block.id, to.id).map((t) => t.track_id)).toContain(track.track_id);
  });

  it('finalize promotes staging tracks into their categories', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    const staging = block.buckets.find((b) => b.bucket_type === 'STAGING' && b.track_count > 0)!;
    const before = db.category(staging.category_id!).track_count;
    const res = db.finalize(block.id);
    expect(res.block.status).toBe('FINALIZED');
    expect(res.promoted[staging.category_id!]).toBe(staging.track_count);
    expect(db.category(staging.category_id!).track_count).toBe(before + staging.track_count);
    expect(() => db.finalize(block.id)).toThrow(DemoError);
  });

  it('adds category tracks to a playlist once and reorders them', () => {
    const db = new DemoDb();
    const playlist = db.playlists({})[0];
    const cat = db.categoriesByStyle('s-tech')[0];
    const ids = db.categoryTracks(cat.id, {}).slice(0, 2).map((t) => t.id);
    const first = db.addToPlaylist(playlist.id, ids);
    const again = db.addToPlaylist(playlist.id, ids);
    expect(again.added).toEqual([]);
    expect(again.skipped_duplicates.sort()).toEqual(first.added.length ? ids.sort() : again.skipped_duplicates.sort());
    const order = db.playlistTracks(playlist.id).map((t) => t.track_id).reverse();
    db.reorderPlaylist(playlist.id, order);
    expect(db.playlistTracks(playlist.id).map((t) => t.track_id)).toEqual(order);
    expect(db.categoryTracks(cat.id, {}).find((t) => t.id === ids[0])!.used_in_playlist).toBe(true);
  });

  it('tags a track and filters a category by tag', () => {
    const db = new DemoDb();
    const tag = db.tags()[0];
    const cat = db.categoriesByStyle('s-afro')[0];
    const track = db.categoryTracks(cat.id, {})[0];
    db.tagTrack(track.id, tag.id);
    expect(db.categoryTracks(cat.id, { tags: [tag.id] }).map((t) => t.id)).toContain(track.id);
  });

  it('remembers the selected styles', () => {
    const db = new DemoDb();
    db.setMyStyles(['s-afro']);
    expect(db.styles('mine').map((s) => s.id)).toEqual(['s-afro']);
  });

  it('is deterministic', () => {
    expect(new DemoDb().bucketTracks(firstOpenBlock(new DemoDb()).id, 'irrelevant-missing')).toEqual([]);
    const a = new DemoDb(); const b = new DemoDb();
    const blockA = firstOpenBlock(a).id;
    expect(a.block(blockA)).toEqual(b.block(blockA));
  });
});
```

- [ ] **Step 2 (RED):** `pnpm test src/demo` → FAIL (modules missing).
- [ ] **Step 3:** implement.

`seed.ts` — deterministic catalog (mulberry32 PRNG, fixed seed), three selected styles (`s-tech` Tech House, `s-melodic` Melodic House & Techno, `s-afro` Afro House) plus three unselected catalog styles with no data; per style 48 invented tracks (title = two words from a word list, mix from `Original Mix / Extended Mix / Dub / Club Mix`, 1–2 artists from an invented name pool, one of six invented labels, style-typical BPM, 5:30–7:30 length, Camelot key, `isrc` `QZDA626xxxxx`, a 22-char base62 `spotify_id`, non-null so Curate never shows the empty-bucket state); per style: one FINALIZED block "Week 40 · Sep 26 – Oct 2" whose 18 tracks sit in three categories (6 each), and one IN_PROGRESS block "Week 41 · Oct 3 – 9" with the other 30 tracks: NEW 18, OLD 5, NOT 3, UNCLASSIFIED 2, FAV 1, first STAGING 1, DISCARD 0, one STAGING bucket per category. Category names: Tech House — Warm-up, Peak time, Closing; Melodic — Opening, Journey, Afterhours; Afro — Percussive, Vocal, Deep. Playlists: "Saturday warm-up" (active, 6 tracks), "Peak hour ideas" (active, 6), "September set" (completed, 4). Tags: Vocal `#e8590c`, Groovy `#2f9e44`, Dark `#5f3dc4`, Hypnotic `#1971c2`, a few category tracks pre-tagged. All timestamps fixed in October 2026.

`db.ts` — `DemoDb(seed = buildSeed())` holding mutable copies; public methods, each returning the SPA's own types (`TriageBlockSummary`, `TriageBlock`, `TriageBucket`, `BucketTrack`, `Category`, `CategoryTrack`, `Playlist`, `PlaylistTrack`, `Tag`, `FinalizeResponse`):
`styles(scope: 'mine' | 'all')`, `setMyStyles(ids)`, `blocksByStyle(styleId, status?)`, `block(id)`, `bucketTracks(blockId, bucketId, search?)`, `move(blockId, fromId, toId, trackIds) → number`, `finalize(blockId) → FinalizeResponse`, `categoriesByStyle(styleId)`, `category(id)`, `categoryTracks(id, {search?, sort?, order?, tags?, match?})`, `addToCategory(id, trackId)`, `removeFromCategory(id, trackId)`, `createCategory(styleId, name)` (also adds a STAGING bucket to the style's open blocks), `renameCategory(id, name)`, `deleteCategory(id)` (its STAGING buckets become `inactive`), `reorderCategories(styleId, ids)`, `playlists({status?, search?})`, `playlist(id)`, `createPlaylist({name, description?, is_public?})`, `patchPlaylist(id, patch)`, `deletePlaylist(id)`, `playlistTracks(id)`, `addToPlaylist(id, trackIds) → {added, skipped_duplicates, position_after}`, `removeFromPlaylist(id, trackId)`, `reorderPlaylist(id, trackIds)`, `tags()`, `createTag(name, color)`, `patchTag(id, patch)`, `deleteTag(id)`, `trackTags(trackId)`, `tagTrack(trackId, tagId)`, `untagTrack(trackId, tagId)`. Unknown ids throw `DemoError(404, '<entity>_not_found', …)`; finalizing a finalized block throws `DemoError(409, 'block_finalized', …)`. `bucketTracks` on an unknown bucket returns `[]`.

`samples.ts` — the analytics (30-day listening, funnel, time per track), coverage (6 styles × 39 weeks, two failed cells) and auto-ingest payloads now inline in `readme.shot.tsx`, as functions; `readme.shot.tsx` imports them.

- [ ] **Step 4 (GREEN):** `pnpm test src/demo` → pass; `pnpm typecheck`; `pnpm lint`.
- [ ] **Step 5: Commit** (`feat(demo): sample catalog and in-memory store`).

---

### Task 2: MSW handlers + worker start

**Files:** Create `frontend/src/demo/handlers.ts`, `frontend/src/demo/start.ts`, `frontend/src/demo/__tests__/handlers.test.ts`, `frontend/src/demo/__tests__/openapi.test.ts`.

**Interfaces:** Consumes `DemoDb`, `DemoError`, `samples.*` (Task 1). Produces `demoRoutes(db, origin): DemoRoute[]` (`{method, path, status?, resolve}`), `demoHandlers(db = new DemoDb(), origin = location.origin)`, `startDemo(): Promise<void>`, `DEMO_STRINGS`.

- [ ] **Step 1: Failing tests** — `handlers.test.ts` uses the shared test server (`import { server } from '../../test/setup'`; `server.use(...demoHandlers())`, origin `http://localhost`):

```ts
import { beforeEach, describe, expect, it } from 'vitest';
import { server } from '../../test/setup';
import { demoHandlers } from '../handlers';

const get = (p: string) => fetch(`http://localhost${p}`);
const send = (method: string, p: string, body?: unknown) =>
  fetch(`http://localhost${p}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

beforeEach(() => server.use(...demoHandlers()));

describe('demo handlers', () => {
  it('signs the visitor in as an admin without a 401', async () => {
    const refresh = await (await send('POST', '/auth/refresh')).json();
    expect(refresh.expires_in).toBe(3600);
    const me = await (await get('/me')).json();
    expect(me.is_admin).toBe(true);
  });

  it('serves the core loop with state', async () => {
    const styles = await (await get('/styles?limit=200&offset=0')).json();
    const styleId = styles.items[0].id;
    const blocks = await (await get(`/styles/${styleId}/triage/blocks?status=IN_PROGRESS&limit=50&offset=0`)).json();
    const block = await (await get(`/triage/blocks/${blocks.items[0].id}`)).json();
    const fresh = block.buckets.find((b: { bucket_type: string }) => b.bucket_type === 'NEW');
    const fav = block.buckets.find((b: { bucket_type: string }) => b.bucket_type === 'FAV');
    const tracks = await (await get(`/triage/blocks/${block.id}/buckets/${fresh.id}/tracks?limit=50&offset=0`)).json();
    const moved = await send('POST', `/triage/blocks/${block.id}/move`, { from_bucket_id: fresh.id, to_bucket_id: fav.id, track_ids: [tracks.items[0].track_id] });
    expect((await moved.json()).moved).toBe(1);
    const favTracks = await (await get(`/triage/blocks/${block.id}/buckets/${fav.id}/tracks?limit=50&offset=0`)).json();
    expect(favTracks.items.map((t: { track_id: string }) => t.track_id)).toContain(tracks.items[0].track_id);
  });

  it('answers unknown reads with 404 and unknown writes with 403', async () => {
    const read = await get('/admin/labels/backlog?limit=100');
    expect(read.status).toBe(404);
    expect((await read.json()).error_code).toBe('not_found');
    const write = await send('POST', '/playlists/p1/publish', { confirm_overwrite: false });
    expect(write.status).toBe(403);
    expect((await write.json()).message).toMatch(/demo/i);
  });

  it('maps store errors to API errors', async () => {
    const res = await get('/triage/blocks/nope');
    expect(res.status).toBe(404);
  });
});
```

`openapi.test.ts`:

```ts
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
import { DemoDb } from '../db';
import { demoRoutes } from '../handlers';

it('test_demo_routes_exist_in_openapi', () => {
  const spec = readFileSync(resolve(__dirname, '../../../../docs/api/openapi.yaml'), 'utf8');
  const known = new Set<string>();
  let path = '';
  for (const line of spec.split('\n')) {
    const p = line.match(/^ {2}(\/\S*):\s*$/);
    if (p) path = p[1].replace(/\{[^}]+\}/g, '{}');
    const m = line.match(/^ {4}(get|post|put|patch|delete):\s*$/);
    if (m && path) known.add(`${m[1]} ${path}`);
  }
  const missing = demoRoutes(new DemoDb(), 'http://localhost')
    .map((r) => `${r.method} ${r.path.replace(/:[^/]+/g, '{}')}`)
    .filter((k) => !known.has(k));
  expect(missing).toEqual([]);
});
```

- [ ] **Step 2 (RED):** → FAIL (modules missing).
- [ ] **Step 3:** `handlers.ts`:

```ts
import { http, HttpResponse } from 'msw';
import { DemoDb, DemoError } from './db';
import { sampleAutoIngest, sampleCoverage, sampleFunnel, sampleListening, sampleTimePerTrack } from './samples';

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete';
interface Ctx { params: Record<string, string>; query: URLSearchParams; body: any }
export interface DemoRoute { method: Method; path: string; status?: number; resolve: (c: Ctx) => unknown }

/** Every API path prefix the SPA calls; anything else (assets, fonts) passes through. */
const API_PREFIXES = ['/auth/', '/me', '/styles', '/triage/', '/categories', '/tracks', '/playlists', '/tags', '/labels', '/artists', '/admin/', '/runs/', '/v1/'];
const NOT_IN_DEMO = 'Not available in the demo — it runs on sample data in your browser.';

function page<T>(items: T[], q: URLSearchParams) {
  const limit = Number(q.get('limit') ?? 50);
  const offset = Number(q.get('offset') ?? 0);
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

export function demoRoutes(db: DemoDb, origin: string): DemoRoute[] {
  void origin;
  const me = { id: 'u-demo', spotify_id: 'demo', display_name: 'Demo DJ', is_admin: true, ytmusic_connected: false, sessions: [] };
  return [
    { method: 'post', path: '/auth/refresh', resolve: () => ({ access_token: 'demo', spotify_access_token: 'demo', expires_in: 3600 }) },
    { method: 'post', path: '/auth/logout', status: 204, resolve: () => undefined },
    { method: 'get', path: '/me', resolve: () => me },
    { method: 'get', path: '/styles', resolve: ({ query }) => page(db.styles(query.get('scope') === 'all' ? 'all' : 'mine'), query) },
    { method: 'put', path: '/me/styles', status: 204, resolve: ({ body }) => db.setMyStyles(body.style_ids) },
    { method: 'get', path: '/styles/:styleId/triage/blocks', resolve: ({ params, query }) => page(db.blocksByStyle(params.styleId, (query.get('status') as never) ?? undefined), query) },
    { method: 'get', path: '/triage/blocks/:id', resolve: ({ params }) => db.block(params.id) },
    { method: 'get', path: '/triage/blocks/:id/buckets/:bucketId/tracks', resolve: ({ params, query }) => page(db.bucketTracks(params.id, params.bucketId, query.get('search') ?? undefined), query) },
    { method: 'post', path: '/triage/blocks/:id/move', resolve: ({ params, body }) => ({ moved: db.move(params.id, body.from_bucket_id, body.to_bucket_id, body.track_ids) }) },
    { method: 'post', path: '/triage/blocks/:id/finalize', resolve: ({ params }) => db.finalize(params.id) },
    { method: 'get', path: '/styles/:styleId/categories', resolve: ({ params, query }) => page(db.categoriesByStyle(params.styleId), query) },
    { method: 'post', path: '/styles/:styleId/categories', status: 201, resolve: ({ params, body }) => db.createCategory(params.styleId, body.name) },
    { method: 'put', path: '/styles/:styleId/categories/order', resolve: ({ params, body }) => ({ items: db.reorderCategories(params.styleId, body.category_ids) }) },
    { method: 'get', path: '/categories/:id', resolve: ({ params }) => db.category(params.id) },
    { method: 'patch', path: '/categories/:id', resolve: ({ params, body }) => db.renameCategory(params.id, body.name) },
    { method: 'delete', path: '/categories/:id', status: 204, resolve: ({ params }) => db.deleteCategory(params.id) },
    { method: 'get', path: '/categories/:id/tracks', resolve: ({ params, query }) => page(db.categoryTracks(params.id, {
      search: query.get('search') ?? undefined, sort: (query.get('sort') as never) ?? undefined, order: (query.get('order') as never) ?? undefined,
      tags: query.get('tags')?.split(',').filter(Boolean), match: (query.get('match') as never) ?? undefined }), query) },
    { method: 'post', path: '/categories/:id/tracks', status: 201, resolve: ({ params, body }) => db.addToCategory(params.id, body.track_id) },
    { method: 'delete', path: '/categories/:id/tracks/:trackId', status: 204, resolve: ({ params }) => db.removeFromCategory(params.id, params.trackId) },
    { method: 'get', path: '/playlists', resolve: ({ query }) => page(db.playlists({ status: (query.get('status') as never) ?? undefined, search: query.get('search') ?? undefined }), query) },
    { method: 'post', path: '/playlists', status: 201, resolve: ({ body }) => db.createPlaylist(body) },
    { method: 'get', path: '/playlists/:id', resolve: ({ params }) => db.playlist(params.id) },
    { method: 'patch', path: '/playlists/:id', resolve: ({ params, body }) => db.patchPlaylist(params.id, body) },
    { method: 'delete', path: '/playlists/:id', status: 204, resolve: ({ params }) => db.deletePlaylist(params.id) },
    { method: 'get', path: '/playlists/:id/tracks', resolve: ({ params, query }) => page(db.playlistTracks(params.id), query) },
    { method: 'post', path: '/playlists/:id/tracks', status: 201, resolve: ({ params, body }) => db.addToPlaylist(params.id, body.track_ids) },
    { method: 'delete', path: '/playlists/:id/tracks/:trackId', status: 204, resolve: ({ params }) => db.removeFromPlaylist(params.id, params.trackId) },
    { method: 'post', path: '/playlists/:id/tracks/order', resolve: ({ params, body }) => (db.reorderPlaylist(params.id, body.track_ids), { correlation_id: 'demo' }) },
    { method: 'get', path: '/tags', resolve: ({ query }) => page(db.tags(), query) },
    { method: 'post', path: '/tags', status: 201, resolve: ({ body }) => db.createTag(body.name, body.color ?? null) },
    { method: 'patch', path: '/tags/:tagId', resolve: ({ params, body }) => db.patchTag(params.tagId, body) },
    { method: 'delete', path: '/tags/:tagId', status: 204, resolve: ({ params }) => db.deleteTag(params.tagId) },
    { method: 'get', path: '/tracks/:trackId/tags', resolve: ({ params }) => ({ items: db.trackTags(params.trackId) }) },
    { method: 'post', path: '/tracks/:trackId/tags', resolve: ({ params, body }) => ({ items: db.tagTrack(params.trackId, body.tag_id) }) },
    { method: 'delete', path: '/tracks/:trackId/tags/:tagId', status: 204, resolve: ({ params }) => db.untagTrack(params.trackId, params.tagId) },
    { method: 'get', path: '/tracks/:trackId/comments', resolve: () => ({ status: 'empty', comment_count: 0, video_url: null, comments: [] }) },
    { method: 'get', path: '/v1/analytics/listening', resolve: () => sampleListening() },
    { method: 'get', path: '/v1/analytics/funnel', resolve: () => sampleFunnel() },
    { method: 'get', path: '/v1/analytics/time-per-track', resolve: ({ query }) => sampleTimePerTrack(Number(query.get('days') ?? 30)) },
    { method: 'get', path: '/admin/coverage', resolve: ({ query }) => sampleCoverage(Number(query.get('week_year') ?? 2026)) },
    { method: 'get', path: '/admin/runs', resolve: () => ({ items: [] }) },
    { method: 'get', path: '/admin/auto-ingest', resolve: () => sampleAutoIngest() },
    { method: 'get', path: '/admin/users', resolve: () => ({ users: [{ id: me.id, display_name: me.display_name }] }) },
    { method: 'get', path: '/labels', resolve: ({ query }) => ({ items: [], total: 0, page: 1, limit: Number(query.get('limit') ?? 50) }) },
    { method: 'get', path: '/artists', resolve: ({ query }) => ({ items: [], total: 0, page: 1, limit: Number(query.get('limit') ?? 50) }) },
  ];
}

export function demoHandlers(db = new DemoDb(), origin = globalThis.location?.origin ?? 'http://localhost') {
  const routes = demoRoutes(db, origin).map((r) =>
    http[r.method](`${origin}${r.path}`, async ({ request, params }) => {
      const body = r.method === 'get' || r.method === 'delete' ? undefined : await request.json().catch(() => ({}));
      try {
        const out = r.resolve({ params: params as Record<string, string>, query: new URL(request.url).searchParams, body });
        if (r.status === 204) return new HttpResponse(null, { status: 204 });
        return HttpResponse.json(out as Record<string, unknown>, { status: r.status ?? 200 });
      } catch (e) {
        if (e instanceof DemoError) return HttpResponse.json({ error_code: e.code, message: e.message }, { status: e.status });
        throw e;
      }
    }),
  );
  // Everything else under the API: reads are "not found" (the SPA does not retry them),
  // writes are refused with a message. Never 401 — it would start the refresh loop.
  const fallback = http.all(`${origin}/*`, ({ request }) => {
    const { pathname } = new URL(request.url);
    if (!API_PREFIXES.some((p) => pathname.startsWith(p))) return undefined;
    return request.method === 'GET'
      ? HttpResponse.json({ error_code: 'not_found', message: 'Not in the demo data.' }, { status: 404 })
      : HttpResponse.json({ error_code: 'forbidden', message: NOT_IN_DEMO }, { status: 403 });
  });
  return [...routes, fallback];
}
```

(Response shapes follow the SPA types; adjust a field if the typecheck or a test says the SPA expects another — and record it in the ledger.)

`start.ts`:

```ts
import i18n from '../i18n';
import { demoHandlers } from './handlers';

export const DEMO_STRINGS = {
  playback: {
    reconnect_spotify: 'Playback needs Spotify — not available in the demo',
    open_device_picker: 'Everything else works on sample data',
  },
};

/** Start the in-browser API before React mounts: AuthProvider fetches on mount. */
export async function startDemo(): Promise<void> {
  const { setupWorker } = await import('msw/browser');
  await setupWorker(...demoHandlers()).start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledRequest: 'bypass',
    quiet: true,
  });
  i18n.addResourceBundle('en', 'translation', DEMO_STRINGS, true, true);
}

export { DemoBanner } from './DemoBanner';
```

- [ ] **Step 4 (GREEN):** both test files pass; typecheck, lint.
- [ ] **Step 5: Commit** (`feat(demo): MSW handlers over the sample store`).

---

### Task 3: Wire the demo mode into the app

**Files:** Create `frontend/src/demo/mode.ts`, `frontend/src/demo/DemoBanner.tsx`; modify `frontend/vite.config.ts` (`base`, `publicDir`), `frontend/src/routes/router.tsx` (`basename`), `frontend/src/main.tsx` (async boot), `frontend/src/features/playback/PlaybackProvider.tsx` (no SDK in the demo), `frontend/src/routes/login.tsx` (sign-in goes to the demo root), `frontend/package.json` (`build:demo`, `dev:demo`), `frontend/.gitignore` (`demo-public/`); test `frontend/src/features/playback/__tests__/PlaybackProvider.demo.test.tsx`.

- [ ] **Step 1: Failing test** — with `vi.mock('../../../demo/mode', () => ({ isDemo: () => true }))` and `vi.mock('../lib/sdkLoader')`, render `PlaybackProvider` with a child calling `controls.prewarm()` and `controls.play(...)`: the SDK loader is never called and the exposed `sdk.error.kind` is `'init'` (the existing "disconnected" state).
- [ ] **Step 2 (RED):** FAIL (loader called / error null).
- [ ] **Step 3:**
  - `mode.ts`: `export const isDemo = (): boolean => import.meta.env.MODE === 'demo';`
  - `PlaybackProvider.tsx`: `useState<SdkError | null>(isDemo() ? { kind: 'init', message: 'demo' } : null)`; first line of `ensureSdk`: `if (isDemo()) return Promise.resolve();` (no `setSdkError` inside — it would loop the prewarm effects).
  - `login.tsx`: `window.location.href = isDemo() ? import.meta.env.BASE_URL : '/auth/login';`
  - `router.tsx`: `createBrowserRouter([...], { basename: import.meta.env.BASE_URL })`.
  - `vite.config.ts`: `base: mode === 'demo' ? '/clouder-core/demo/' : '/'`, `publicDir: mode === 'demo' ? 'demo-public' : 'public'`.
  - `main.tsx`: render inside `async function boot()`; when `import.meta.env.MODE === 'demo'`, `const demo = await import('./demo/start'); await demo.startDemo();` and render `<demo.DemoBanner />` next to the router (no top-level `await`: the build target is es2020).
  - `DemoBanner.tsx`: a small fixed pill at the bottom left — "Demo · sample data, changes stay in this tab · playback needs Spotify · [Source](https://github.com/tarodo/clouder-core)".
  - `package.json`: `"build:demo": "msw init demo-public && tsc -b && vite build --mode demo"`, `"dev:demo": "msw init demo-public && vite --mode demo"` (the worker file is generated from the installed msw version, never committed).
- [ ] **Step 4 (GREEN):** test passes; `pnpm typecheck && pnpm lint && pnpm test`; `pnpm build` then `! grep -rlE "mockServiceWorker|msw" dist` (production bundle has no demo code); `pnpm build:demo` then `grep -q '/clouder-core/demo/assets/' dist/index.html && test -f dist/mockServiceWorker.js`.
- [ ] **Step 5: Local smoke** — `pnpm build:demo && pnpm exec vite preview --mode demo --port 4173`, then a Playwright script (scratchpad) opens `http://localhost:4173/clouder-core/demo/`: Home shows "Tech House"; `/clouder-core/demo/curate/s-tech` shows a track title; pressing the hotkey for a destination moves it (the bucket count changes); `/clouder-core/demo/categories/s-tech` lists Warm-up/Peak time/Closing; `/clouder-core/demo/playlists` lists "Saturday warm-up"; no page error in the console except the expected bypassed font requests.
- [ ] **Step 6: Commit** (`feat(demo): demo build mode for the SPA`).

---

### Task 4: One Pages site — landing, `/lineage/`, `/demo/`

**Files:** Create `pages/index.html`, `.github/workflows/pages.yml`, `docs/frontend/demo.md`; delete `.github/workflows/dbt-docs.yml`; modify `.github/workflows/pr.yml` (frontend job also runs `pnpm build:demo`), `README.md` (badges/links: lineage → `/lineage/`, new "Try it" link), `docs/frontend/README.md` (index link if it lists pages), `tests/unit/test_ci_workflows.py` (append).

- [ ] **Step 1: Failing tests** (append to `tests/unit/test_ci_workflows.py`):

```python
def test_one_pages_workflow_publishes_landing_lineage_and_demo() -> None:
    assert not (WF / "dbt-docs.yml").exists(), "two Pages workflows overwrite each other"
    pages = (WF / "pages.yml").read_text()
    for needle in ("dbt docs generate", "pnpm build:demo", "site/lineage/index.html", "site/demo", "site/404.html", "pages/index.html"):
        assert needle in pages, needle


def test_pr_builds_the_demo() -> None:
    runs = [step.get("run", "") for step in PR["jobs"]["frontend"]["steps"]]
    assert "pnpm build:demo" in runs
```

- [ ] **Step 2 (RED):** FAIL.
- [ ] **Step 3:**
  - `pages.yml` — `on: push: branches: [main], paths: [dbt/**, frontend/**, pages/**, docs/assets/curate.png, .github/workflows/pages.yml]` + `workflow_dispatch`; `permissions: contents: read, pages: write, id-token: write`; `concurrency: pages`; job `build` (checkout; Python 3.12 + `pip install -r dbt/requirements.txt`; `dbt seed/run/docs generate --target ci --static` in `dbt/` with `DBT_PROFILES_DIR=.`; pnpm 9 + Node 22 exactly as `pr.yml`; `pnpm install --frozen-lockfile && pnpm build:demo` in `frontend/`; assemble: `mkdir -p site/lineage site/demo && cp pages/index.html site/ && cp docs/assets/curate.png site/ && cp dbt/target/static_index.html site/lineage/index.html && cp -R frontend/dist/. site/demo/ && cp frontend/dist/index.html site/404.html`; `actions/upload-pages-artifact@v5` with `path: site`); job `deploy` (`needs: build`, `environment: github-pages`, `actions/deploy-pages@v5`).
  - `pages/index.html` — one static page, inline CSS, light/dark via `prefers-color-scheme`, no external requests: CLOUDER, one sentence on what it is, two cards — **Try the app** (`demo/`, "Sample data in your browser — no login; nothing leaves the tab") and **Data lineage** (`lineage/`, "dbt models and tests of the Iceberg lakehouse"), the `curate.png` screenshot, a link to the repository.
  - `pr.yml` frontend job: `- run: pnpm build:demo` after `pnpm build`.
  - README: lineage badge → `https://tarodo.github.io/clouder-core/lineage/`; add a "Try it with sample data" badge/link → `https://tarodo.github.io/clouder-core/demo/` near the top; one sentence where the README says the live app sits behind an allow-list.
  - `docs/frontend/demo.md`: what the demo is, how it is built (`pnpm dev:demo` / `pnpm build:demo`), what is stateful vs static vs refused, playback off, where to add a handler, the openapi guard.
- [ ] **Step 4 (GREEN):** Python suite green (incl. doc-link and README guards); frontend `pnpm test` green.
- [ ] **Step 5: Commit** (`ci(pages): landing, lineage and demo in one site`).

---

### Task 5: PR, review, merge, deploy, verify

- [ ] Plan commit, graphify, push, PR; fresh review; one fix pass.
- [ ] Checks green (frontend job builds the demo) → merge → Deploy green (smoke 9/9; the SPA code changed only behind the demo flag) → the Pages workflow runs and deploys.
- [ ] Live checks: `curl -sI https://tarodo.github.io/clouder-core/` (200, landing), `/lineage/` (200, dbt docs), `/demo/` (200); Playwright on the live demo: Home → curate a track → triage bucket shows it → finalize → category gains it → add to playlist; deep link `/clouder-core/demo/triage/s-tech` (404 status, app renders).
- [ ] README badge targets resolve; repo About homepage stays `https://tarodo.github.io/clouder-core/` (now the landing page).
- [ ] §0 board: phase 7 done → no todo phases left → stop the loop.

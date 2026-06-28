# Telemetry SDK (frontend) — Phase 1 · Increment 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Dispatch each task to a subagent, review its work against the task's acceptance criteria before moving on, and keep the loop tight. Steps use checkbox (- [ ]) syntax.

**Goal:** Ship a behind-a-flag, in-house telemetry SDK plus the `track()` wiring at every real fire-point, with zero backend dependency. The SDK buffers events, flushes on 3 triggers, transports via fetch-keepalive to `/v1/telemetry` with auth-failure suppressed, and supplies timing/seen helpers so `triage_session_end.tracks_seen` is real. `VITE_TELEMETRY_ENABLED` defaults off, so `track()` no-ops in production until the route lands in Increment 2.

**Architecture:** Module-level singleton (`frontend/src/lib/telemetry/sdk.ts`) mirroring the `tokenStore`/`spotifyTokenStore` pattern — no React context. A thin hooks layer (`hooks.ts`) exposes `useTelemetry()`, `useTelemetryRoute()`, `useTrackView()`. Transport reuses the existing `api()` client (`frontend/src/api/client.ts`) extended with a `{suppressAuthFailure}` option so a background/unload 401 never logs the user out. The `/v1` API prefix is registered in CloudFront (`infra/frontend.tf`) + the Vite dev proxy so a future real POST reaches API Gateway. Catalog/handler/Firehose/dbt are all out of scope for this increment (Increment 2+).

**Task ordering note (MUST-FIX 5):** the `api()` `{suppressAuthFailure}` option (Task 1) lands **before** the SDK (Task 2). `sdk.ts` references that option in its `api()` call; if the `ApiInit` type does not exist yet, `pnpm typecheck` in the SDK task fails with TS2353. So client.ts ships first and also opens the feature branch.

**Tech Stack:** React 19, Mantine 9, TanStack Query, Vite + Vitest (jsdom), MSW, `@testing-library/react` + `user-event`, native `crypto` (ULID/UUID — no new dependency), Terraform.

**Spec:** docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md (§3 envelope + MVP events, §4 SDK, §13–§14 privacy + tests, §17 step 1)

---

## File structure

**Created**
- `frontend/src/lib/telemetry/sdk.ts` — singleton buffer, ULID/UUID, per-tab session, 3 flush triggers, chunked keepalive transport, `markShown`/`msSinceShown`, session-scoped seen Set, `debounceTrack`, `setRoute`.
- `frontend/src/lib/telemetry/hooks.ts` — `useTelemetry()`, `useTelemetryRoute(route)`, `useTrackView(trackId)`.
- `frontend/src/lib/telemetry/sdk.test.ts` — SDK unit tests (ULID/UUID/envelope/flush triggers/chunking/debounce/enabled-noop/privacy dir-scan).
- `frontend/src/lib/telemetry/hooks.test.tsx` — route + track_view hook tests.
- `frontend/src/features/playback/lib/telemetryMap.ts` — `resolvePlaybackSource()`, `seekEventProps()` pure mappers (where the MUST-FIX 1/2 defects lived).
- `frontend/src/features/playback/lib/telemetryMap.test.ts` — mapper unit tests.

**Modified**
- `frontend/src/api/client.ts` — add `{suppressAuthFailure}` option; bypass `notifyAuthFailure()` on refresh-failure when set.
- `frontend/src/api/client.test.ts` *(create)* — suppressAuthFailure on/off behaviour.
- `frontend/eslint.config.js` — privacy lint rule (`no-restricted-imports`/`no-restricted-globals`) scoped to `src/lib/telemetry/**`.
- `frontend/src/vite-env.d.ts` — declare `VITE_TELEMETRY_ENABLED`, `VITE_APP_VERSION`, global `__APP_VERSION__`.
- `frontend/vite.config.ts` — add `/v1` to `BACKEND_ONLY_PREFIXES`; inject `__APP_VERSION__` via `define`.
- `infra/frontend.tf` — add `/v1` to `api_gw_pure_path_patterns`.
- `frontend/src/features/playback/lib/types.ts` — add `PlaybackSource` type.
- `frontend/src/features/playback/PlaybackProvider.tsx` — `play()` gains `source?: PlaybackSource`; emit `playback_play` (var `track`) + `playback_seek` (debounced); bind SDK via `useTelemetry()`.
- `frontend/src/features/triage/components/BucketTrackRow.tsx` — `useTrackView(track.track_id)`.
- `frontend/src/features/triage/components/BucketTrackRow.test.tsx` *(create)* — track_view render/unmount test.
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — `triage_session_start`/`end` (real `tracks_seen`/`undo_rate`), `track_categorized`(moved_to_bucket) in `handleMove`, `track_categorized`(undo) in the inline toast undo.
- `frontend/src/features/triage/routes/BucketDetailPage.telemetry.test.tsx` *(create)* — session + categorize (usePlayback mocked, real `/move` endpoint).
- `frontend/src/features/curate/hooks/useCurateSession.ts` — `track_categorized`(categorized_curate / undo) with real `decision_ms`/`category_key`; `markShown` when current track changes.
- `frontend/src/features/curate/hooks/useCurateSession.telemetry.test.tsx` *(create)* — assign + undo emits (usePlayback mocked).
- `frontend/src/features/curate/hooks/useCurateHotkeys.ts` — `hotkey_used`(curate), 4-value action enum.
- `frontend/src/features/curate/hooks/useCurateHotkeys.telemetry.test.tsx` *(create)* — per-case emit.
- `frontend/src/features/curate/routes/CurateSessionPage.tsx` — `useTelemetryRoute('/curate/:styleId/:blockId/:bucketId')`.
- `frontend/src/features/curate/routes/CurateSessionPage.test.tsx` *(create)* — route wiring.
- `frontend/src/features/playlists/components/AddTracksModal.tsx` — `playlist_add` with `track_ids` from `selected`, `source_category_id` from the modal's `categoryId` state.
- `frontend/src/features/playlists/components/AddTracksModal.telemetry.test.tsx` *(create)*.
- `frontend/src/features/playlists/components/PublishButton.tsx` — `trackIds` prop + `playlist_publish`(spotify).
- `frontend/src/features/playlists/components/PublishYtMusicButton.tsx` — `trackIds` prop + `playlist_publish`(ytmusic).
- `frontend/src/features/playlists/components/PublishButton.telemetry.test.tsx` + `PublishYtMusicButton.telemetry.test.tsx` *(create)*.
- `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` — pass `trackIds={tracks.map(t=>t.track_id)}` to both publish buttons; pass `source` to `play()`.

**Out of scope (deferred — documented, not silent):**
- `track_view` at the *categories* (`CategoryDetailPage`) and *playlists* (`PlaylistTracksList`) rows — identical `useTrackView()` call, deferred to **Increment 1b**. Triage `track_view` ships now because it feeds `tracks_seen` (MUST-FIX 5). This is the explicit scoped deferral MUST-FIX 4 permits; the hook is reusable so the follow-up is a one-line add per row.
- `playback_play` + `playback_seek` (the MUST-FIX 1/2 targets) ship now. Their defect-prone logic (wrong variable / wrong default map / undefined position / `track.id`-vs-`track_id`) lives in two pure mappers covered by `telemetryMap.test.ts`. The **render-level emit assertion is deferred**: after Task 7 switches the curate test from a real `<PlaybackProvider>` to a mocked `usePlayback` (blocker fix below), there is **no** `PlaybackProvider`+`AuthProvider`+Spotify-SDK test harness anywhere in the suite, and building one to assert a single `track()` call would mean simulating the whole Spotify Connect state machine — over-engineering for this increment. The emit code locks the field shape with an inline comment (`track.id`, not `track_id`).
- `playback_pause` / `playback_ended` / `playback_skip` / `hotkey_used`(playback) / `playlist_reorder` — wired emits deferred to **Increment 1c** (see *Follow-ups (tracked)* below).
- `app_version` is injected at build (`__APP_VERSION__` = `YYYY-MM-DD+<git sha>`), falling back to `'dev'` in tests/local — implemented here (MUST-FIX 13), not deferred.

**Follow-ups (tracked, must be created before this increment merges):**
- **Increment 1b** — `useTrackView()` on `CategoryDetailPage` rows and `PlaylistTracksList` rows (one line each, reuses the shipped hook).
- **Increment 1c** — playback secondary events + `playlist_reorder`. *Design note:* `playback_pause`/`ended`/`skip` must read the **`queueDispatch` status** (the remote-device source of truth, §3.2), not raw Spotify SDK `player_state_changed` flags, and must distinguish auto-advance (queue ran out) from a user-initiated `skip`. This needs its own short design note and a `PlaybackProvider` test harness, which is why it is not folded into Increment 1.

---

## Tasks

### Task 1: `api()` `{suppressAuthFailure}` option (lands first; opens the branch)

**Files:**
- Modify `frontend/src/api/client.ts` (L48 signature; L58-78 401 branch)
- Test: `frontend/src/api/client.test.ts` *(create)*

- [ ] Write the failing test `frontend/src/api/client.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';
import { ApiError } from './error';
import { tokenStore } from '../auth/tokenStore';

describe('api() suppressAuthFailure', () => {
  beforeEach(() => tokenStore.set('jwt-1'));
  afterEach(() => {
    vi.restoreAllMocks();
    tokenStore.set(null);
  });

  function mock401ThenRefreshFail() {
    // Every request (incl. /auth/refresh) 401s → refresh fails → unrecoverable 401.
    return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 401 }));
  }

  it('default path logs the user out on unrecoverable 401', async () => {
    mock401ThenRefreshFail();
    const expired = vi.fn();
    window.addEventListener('auth:expired', expired);
    await expect(api('/me')).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledTimes(1);
    expect(tokenStore.get()).toBeNull();
    window.removeEventListener('auth:expired', expired);
  });

  it('suppressed path swallows logout: no auth:expired, token kept', async () => {
    mock401ThenRefreshFail();
    const expired = vi.fn();
    window.addEventListener('auth:expired', expired);
    await expect(
      api('/v1/telemetry', { method: 'POST', keepalive: true, suppressAuthFailure: true, body: '{}' }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(expired).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe('jwt-1');
    window.removeEventListener('auth:expired', expired);
  });

  it('forwards keepalive to fetch and never leaks suppressAuthFailure into RequestInit', async () => {
    // 202 with a parseable body: api() does `await res.json()` on non-204 success,
    // and Response.json() on an empty body throws 'Unexpected end of JSON input'.
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    await api('/v1/telemetry', { method: 'POST', keepalive: true, suppressAuthFailure: true, body: '{}' });
    const init = spy.mock.calls[0][1] as RequestInit & { suppressAuthFailure?: unknown };
    expect(init.keepalive).toBe(true);
    expect('suppressAuthFailure' in init).toBe(false);
  });
});
```
- [ ] Run it, expect FAIL: `cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend && pnpm test src/api/client.test.ts` → TS error `Object literal may only specify known properties … 'suppressAuthFailure'` and the suppressed test fails because `auth:expired` still fires.
- [ ] Edit `frontend/src/api/client.ts` — replace the `api()` signature + body. New signature destructures the option out so it never reaches `fetch`:
```ts
export interface ApiInit extends RequestInit {
  suppressAuthFailure?: boolean;
}

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const { suppressAuthFailure, ...rest } = init;
  const url = path.startsWith('http') ? path : `${baseUrl}${path}`;
  const token = tokenStore.get();
  const headers = new Headers(rest.headers);
  headers.set('Accept', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (rest.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  const res = await fetch(url, { ...rest, headers, credentials: 'include' });

  if (res.status === 401 && token) {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      const retryHeaders = new Headers(rest.headers);
      retryHeaders.set('Accept', 'application/json');
      retryHeaders.set('Authorization', `Bearer ${tokenStore.get()}`);
      if (rest.body && !retryHeaders.has('Content-Type')) {
        retryHeaders.set('Content-Type', 'application/json');
      }
      const retry = await fetch(url, { ...rest, headers: retryHeaders, credentials: 'include' });
      if (!retry.ok) throw await ApiError.from(retry);
      if (retry.status === 204) return undefined as T;
      return (await retry.json()) as T;
    }
    if (!suppressAuthFailure) notifyAuthFailure();
    throw await ApiError.from(res);
  }

  if (!res.ok) throw await ApiError.from(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
```
- [ ] Run it, expect PASS: `pnpm test src/api/client.test.ts` → `Tests 3 passed (3)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Commit: create the branch and commit. Generate the subject via the `caveman:caveman-commit` skill, then:
```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve && git checkout -b feat/telemetry-sdk && git add frontend/src/api/client.ts frontend/src/api/client.test.ts && git commit -m "<caveman-commit subject>"
```

---

### Task 2: Telemetry SDK core (`sdk.ts`) + env flag + app_version + privacy lint rule

**Files:**
- Create `frontend/src/lib/telemetry/sdk.ts`
- Modify `frontend/src/vite-env.d.ts`
- Modify `frontend/vite.config.ts` (imports + `define`)
- Modify `frontend/eslint.config.js` (privacy rule)
- Test: `frontend/src/lib/telemetry/sdk.test.ts`

- [ ] Write the failing test `frontend/src/lib/telemetry/sdk.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { tokenStore } from '../../auth/tokenStore';

async function freshSdk() {
  vi.resetModules();
  return import('./sdk');
}

describe('telemetry sdk', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true');
    tokenStore.set('jwt-123');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    tokenStore.set(null);
  });

  it('no-ops when the flag is off', async () => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'false');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const { telemetry, flush } = await freshSdk();
    for (let i = 0; i < 30; i++) telemetry.track('track_view', { track_id: String(i) });
    await flush();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('ulid is 26 Crockford chars and time-sortable', async () => {
    const { __ulidForTest } = await freshSdk();
    const a = __ulidForTest();
    const b = __ulidForTest();
    expect(a).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
    expect(b).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
    expect(a.slice(0, 10) <= b.slice(0, 10)).toBe(true);
  });

  it('session id is a uuid, stable per module, fresh per tab', async () => {
    const { telemetry } = await freshSdk();
    const id = telemetry.getSessionId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(telemetry.getSessionId()).toBe(id);
    const { telemetry: t2 } = await freshSdk();
    expect(t2.getSessionId()).not.toBe(id);
  });

  it('flushes at the 25-event size cap with keepalive + bearer + envelope shape', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    const { telemetry } = await freshSdk();
    for (let i = 0; i < 25; i++) telemetry.track('track_view', { track_id: String(i) });
    await Promise.resolve();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain('/v1/telemetry');
    expect(init?.keepalive).toBe(true);
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer jwt-123');
    const body = JSON.parse(init?.body as string);
    expect(body.events).toHaveLength(25);
    const e = body.events[0];
    expect(e).toMatchObject({
      event_name: 'track_view',
      session_id: telemetry.getSessionId(),
      context: { user_id: null, route: null },
      props: { track_id: '0' },
    });
    expect(typeof e.event_id).toBe('string');
    expect(typeof e.ts_client).toBe('string');
    expect(typeof e.context.app_version).toBe('string');
    expect(e.context.app_version.length).toBeGreaterThan(0);
  });

  it('flushes on visibilitychange→hidden', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    const { telemetry } = await freshSdk();
    telemetry.track('triage_session_end', { session_ms: 1 });
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('chunks the keepalive flush under 64KB', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    const { telemetry, flush } = await freshSdk();
    const big = 'x'.repeat(2000);
    for (let i = 0; i < 60; i++) telemetry.track('track_view', { track_id: String(i), pad: big });
    await flush();
    expect(fetchSpy.mock.calls.length).toBeGreaterThan(1);
    for (const [, init] of fetchSpy.mock.calls) {
      expect((init?.body as string).length).toBeLessThan(64_000);
    }
  });

  it('seen counter dedupes by key and resets per session', async () => {
    const { telemetry } = await freshSdk();
    telemetry.markSeen('a');
    telemetry.markSeen('a');
    telemetry.markSeen('b');
    expect(telemetry.seenCount()).toBe(2);
    telemetry.resetSeen();
    expect(telemetry.seenCount()).toBe(0);
  });

  it('msSinceShown returns 0 for unknown keys and a positive int after markShown', async () => {
    const { telemetry } = await freshSdk();
    expect(telemetry.msSinceShown('nope')).toBe(0);
    telemetry.markShown('k');
    expect(telemetry.msSinceShown('k')).toBeGreaterThanOrEqual(0);
    expect(Number.isInteger(telemetry.msSinceShown('k'))).toBe(true);
  });

  it('debounceTrack collapses rapid calls into one track() with the last props', async () => {
    vi.useFakeTimers();
    const { telemetry, debounceTrack } = await freshSdk();
    const spy = vi.spyOn(telemetry, 'track');
    const d = debounceTrack(500);
    d('playback_seek', { to_position_ms: 1 });
    d('playback_seek', { to_position_ms: 2 });
    d('playback_seek', { to_position_ms: 3 });
    vi.advanceTimersByTime(500);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('playback_seek', { to_position_ms: 3 });
    vi.useRealTimers();
  });

  it('telemetry dir never imports bpTokenStore or touches web storage (privacy §14)', async () => {
    const fs = await import('node:fs/promises');
    const dir = new URL('.', import.meta.url);
    const files = (await fs.readdir(dir)).filter(
      (n) => /\.(ts|tsx)$/.test(n) && !n.includes('.test.'),
    );
    expect(files).toContain('sdk.ts');
    for (const f of files) {
      const src = await fs.readFile(new URL(f, dir), 'utf8');
      expect(src, f).not.toContain('bpTokenStore');
      expect(src, f).not.toContain('localStorage');
      expect(src, f).not.toContain('sessionStorage');
    }
  });
});
```
- [ ] Run it, expect FAIL: `pnpm test src/lib/telemetry/sdk.test.ts` → `Failed to resolve import "./sdk"`.
- [ ] Add the env declarations to `frontend/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_TELEMETRY_ENABLED?: string;
  readonly VITE_APP_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```
- [ ] Inject `__APP_VERSION__` in `frontend/vite.config.ts` — add to the imports and the returned config object:
```ts
import { execSync } from 'node:child_process';
// ...existing imports...

function appVersion(): string {
  if (process.env.VITE_APP_VERSION) return process.env.VITE_APP_VERSION;
  try {
    const sha = execSync('git rev-parse --short HEAD').toString().trim();
    return `${new Date().toISOString().slice(0, 10)}+${sha}`;
  } catch {
    return 'dev';
  }
}
```
  and inside the returned object (sibling of `plugins`):
```ts
    define: { __APP_VERSION__: JSON.stringify(appVersion()) },
```
- [ ] Create `frontend/src/lib/telemetry/sdk.ts`:
```ts
import { api } from '../../api/client';

export type TelemetryProps = Record<string, unknown>;

export interface TelemetryEnvelope {
  event_name: string;
  event_id: string;
  session_id: string;
  ts_client: string;
  context: {
    user_id: null;
    device: 'desktop' | 'mobile' | 'tablet';
    route: string | null;
    app_version: string;
  };
  props: TelemetryProps;
}

const FLUSH_INTERVAL_MS = 10_000;
const FLUSH_SIZE = 25;
const MAX_CHUNK_BYTES = 60_000; // headroom under the 64KB keepalive cap

const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function ulid(): string {
  let now = Date.now();
  const time = new Array<string>(10);
  for (let i = 9; i >= 0; i--) {
    time[i] = CROCKFORD[now % 32];
    now = Math.floor(now / 32);
  }
  const rnd = new Uint8Array(16);
  crypto.getRandomValues(rnd);
  let r = '';
  for (let i = 0; i < 16; i++) r += CROCKFORD[rnd[i] % 32];
  return time.join('') + r;
}

function uuidv4(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0'));
  return `${h[0]}${h[1]}${h[2]}${h[3]}-${h[4]}${h[5]}-${h[6]}${h[7]}-${h[8]}${h[9]}-${h[10]}${h[11]}${h[12]}${h[13]}${h[14]}${h[15]}`;
}

const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev';

function telemetryEnabled(): boolean {
  return import.meta.env.VITE_TELEMETRY_ENABLED === 'true';
}

function device(): 'desktop' | 'mobile' | 'tablet' {
  if (typeof window === 'undefined') return 'desktop';
  return window.innerWidth > 0 && window.innerWidth < 768 ? 'mobile' : 'desktop';
}

const SESSION_ID = uuidv4(); // fresh per tab, never persisted (§4.1)
let currentRoute: string | null = null;
let buffer: TelemetryEnvelope[] = [];
const shownAt = new Map<string, number>();
let seen = new Set<string>();
let triggersBound = false;

function bindFlushTriggers(): void {
  if (triggersBound || typeof window === 'undefined') return;
  triggersBound = true;
  setInterval(() => {
    if (buffer.length) void flush();
  }, FLUSH_INTERVAL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flush();
  });
  window.addEventListener('pagehide', () => void flush());
}

export function chunkEvents(
  events: TelemetryEnvelope[],
  maxBytes = MAX_CHUNK_BYTES,
): TelemetryEnvelope[][] {
  const chunks: TelemetryEnvelope[][] = [];
  let cur: TelemetryEnvelope[] = [];
  let bytes = 2; // {"events":[]} braces approximated
  for (const e of events) {
    const size = JSON.stringify(e).length + 1;
    if (cur.length && bytes + size > maxBytes) {
      chunks.push(cur);
      cur = [];
      bytes = 2;
    }
    cur.push(e);
    bytes += size;
  }
  if (cur.length) chunks.push(cur);
  return chunks;
}

export async function flush(): Promise<void> {
  if (!buffer.length) return;
  const events = buffer;
  buffer = [];
  for (const chunk of chunkEvents(events)) {
    // Fire-and-forget: failure (incl. swallowed 401) drops the batch silently (§4.2).
    void api('/v1/telemetry', {
      method: 'POST',
      keepalive: true,
      suppressAuthFailure: true,
      body: JSON.stringify({ events: chunk }),
    }).catch(() => {});
  }
}

export function debounceTrack(
  ms: number,
): (eventName: string, props?: TelemetryProps) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let name = '';
  let lastProps: TelemetryProps = {};
  return (eventName, props = {}) => {
    name = eventName;
    lastProps = props;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      telemetry.track(name, lastProps);
    }, ms);
  };
}

export const telemetry = {
  track(eventName: string, props: TelemetryProps = {}): void {
    if (!telemetryEnabled()) return; // VITE_TELEMETRY_ENABLED default off → no-op
    bindFlushTriggers();
    buffer.push({
      event_name: eventName,
      event_id: ulid(),
      session_id: SESSION_ID,
      ts_client: new Date().toISOString(),
      context: { user_id: null, device: device(), route: currentRoute, app_version: APP_VERSION },
      props,
    });
    if (buffer.length >= FLUSH_SIZE) void flush();
  },
  markShown(key: string): void {
    shownAt.set(key, performance.now());
  },
  msSinceShown(key: string): number {
    const t = shownAt.get(key);
    return t == null ? 0 : Math.round(performance.now() - t);
  },
  markSeen(key: string): void {
    seen.add(key);
  },
  seenCount(): number {
    return seen.size;
  },
  resetSeen(): void {
    seen = new Set();
  },
  setRoute(route: string | null): void {
    currentRoute = route;
  },
  getSessionId(): string {
    return SESSION_ID;
  },
};

export const __ulidForTest = ulid;
```
- [ ] Add the privacy lint rule to `frontend/eslint.config.js` — append a scoped config object as the last argument of `tseslint.config(...)`, after the main block:
```js
  {
    files: ['src/lib/telemetry/**/*.{ts,tsx}'],
    ignores: ['src/lib/telemetry/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/bpTokenStore'],
              message: 'Telemetry must not read admin/bp token state (privacy §14).',
            },
          ],
        },
      ],
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: 'Telemetry must not persist to web storage (privacy §14).' },
        { name: 'sessionStorage', message: 'Telemetry must not persist to web storage (privacy §14).' },
      ],
    },
  },
```
- [ ] Run it, expect PASS: `pnpm test src/lib/telemetry/sdk.test.ts` → `Test Files 1 passed (1)`, `Tests 10 passed (10)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0 (the new lint block passes — `sdk.ts` imports neither `bpTokenStore` nor web storage).
- [ ] Commit via caveman-commit: `git add frontend/src/lib/telemetry/sdk.ts frontend/src/lib/telemetry/sdk.test.ts frontend/src/vite-env.d.ts frontend/vite.config.ts frontend/eslint.config.js && git commit -m "<subject>"`.

---

### Task 3: Register the `/v1` API prefix (CloudFront + Vite proxy)

**Files:**
- Modify `frontend/vite.config.ts` (`BACKEND_ONLY_PREFIXES`)
- Modify `infra/frontend.tf` (`api_gw_pure_path_patterns`)

No new unit test (Terraform + dev-proxy config); verified by `terraform fmt`/`validate`, `tsc`, and a literal grep. This is config, not logic — a self-check assertion would be tautological.

- [ ] Add `'/v1'` to `BACKEND_ONLY_PREFIXES` in `frontend/vite.config.ts` (top of the list — it is a pure API prefix, no SPA collision):
```ts
const BACKEND_ONLY_PREFIXES = [
  '/v1',
  '/auth/login',
  '/auth/callback',
  '/auth/refresh',
  '/auth/logout',
  '/me',
  '/styles',
  '/tracks',
  '/artists',
  '/labels',
  '/albums',
  '/runs',
  '/collect_bp_releases',
];
```
- [ ] Add `"/v1*"` to `api_gw_pure_path_patterns` in `infra/frontend.tf` (after `"/triage/blocks*"`):
```hcl
    "/triage/blocks*",
    "/v1*",
    "/tags*",
```
- [ ] Verify config:
```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform fmt -check frontend.tf && grep -c '"/v1\*"' frontend.tf
```
→ `fmt` exits 0 (no reformat needed), grep prints `1`.
- [ ] Verify frontend still typechecks: `cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend && pnpm typecheck && grep -c "'/v1'" vite.config.ts` → exit 0, grep prints `1`.
- [ ] Commit via caveman-commit: `git add frontend/vite.config.ts infra/frontend.tf && git commit -m "<subject>"`.

---

### Task 4: Telemetry hooks (`hooks.ts`)

**Files:**
- Create `frontend/src/lib/telemetry/hooks.ts`
- Test: `frontend/src/lib/telemetry/hooks.test.tsx`

- [ ] Write the failing test `frontend/src/lib/telemetry/hooks.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { telemetry } from './sdk';
import { useTelemetry, useTelemetryRoute, useTrackView } from './hooks';

describe('telemetry hooks', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('useTelemetry returns the singleton', () => {
    let captured: unknown;
    function Probe() {
      captured = useTelemetry();
      return null;
    }
    render(<Probe />);
    expect(captured).toBe(telemetry);
  });

  it('useTelemetryRoute sets the route on mount and clears it on unmount', () => {
    const setRoute = vi.spyOn(telemetry, 'setRoute');
    function Probe() {
      useTelemetryRoute('/curate/:styleId/:blockId/:bucketId');
      return null;
    }
    const { unmount } = render(<Probe />);
    expect(setRoute).toHaveBeenCalledWith('/curate/:styleId/:blockId/:bucketId');
    unmount();
    expect(setRoute).toHaveBeenLastCalledWith(null);
  });

  it('useTrackView marks shown+seen on mount and emits track_view on unmount', () => {
    const track = vi.spyOn(telemetry, 'track');
    const markSeen = vi.spyOn(telemetry, 'markSeen');
    function Probe() {
      useTrackView('track-42');
      return null;
    }
    const { unmount } = render(<Probe />);
    expect(markSeen).toHaveBeenCalledWith('track-42');
    expect(track).not.toHaveBeenCalled();
    unmount();
    expect(track).toHaveBeenCalledTimes(1);
    const [name, props] = track.mock.calls[0];
    expect(name).toBe('track_view');
    expect(props).toMatchObject({ track_id: 'track-42' });
    expect(typeof (props as { dwell_ms: number }).dwell_ms).toBe('number');
  });
});
```
- [ ] Run it, expect FAIL: `pnpm test src/lib/telemetry/hooks.test.tsx` → `Failed to resolve import "./hooks"`.
- [ ] Create `frontend/src/lib/telemetry/hooks.ts`:
```ts
import { useEffect } from 'react';
import { telemetry } from './sdk';

export function useTelemetry(): typeof telemetry {
  return telemetry;
}

/** Stamp `context.route` for events fired while this route is mounted. */
export function useTelemetryRoute(route: string): void {
  useEffect(() => {
    telemetry.setRoute(route);
    return () => telemetry.setRoute(null);
  }, [route]);
}

/**
 * Track a row's view lifecycle: start the dwell timer + count it toward the
 * session seen-set on mount, emit `track_view` with dwell_ms on unmount/exit.
 */
export function useTrackView(trackId: string): void {
  useEffect(() => {
    telemetry.markShown(trackId);
    telemetry.markSeen(trackId);
    return () => {
      telemetry.track('track_view', { track_id: trackId, dwell_ms: telemetry.msSinceShown(trackId) });
    };
  }, [trackId]);
}
```
- [ ] Run it, expect PASS: `pnpm test src/lib/telemetry/hooks.test.tsx` → `Tests 3 passed (3)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0 (the privacy lint block now also scans `hooks.ts` — it imports only `./sdk`).
- [ ] Commit via caveman-commit: `git add frontend/src/lib/telemetry/hooks.ts frontend/src/lib/telemetry/hooks.test.tsx && git commit -m "<subject>"`.

---

### Task 5: Playback — `PlaybackSource` + `play()` source arg + `playback_play`/`playback_seek` emits

**Files:**
- Modify `frontend/src/features/playback/lib/types.ts` (add `PlaybackSource`)
- Create `frontend/src/features/playback/lib/telemetryMap.ts`
- Test: `frontend/src/features/playback/lib/telemetryMap.test.ts`
- Modify `frontend/src/features/playback/PlaybackProvider.tsx` (controls type; `play`; `seekMs`; provider body for `useTelemetry`/`debounceTrack`)
- Modify call sites: `frontend/src/features/triage/routes/BucketDetailPage.tsx`, `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx`

The MUST-FIX 1/2 defects (wrong variable, wrong default map, undefined position) live in two pure mappers — those are what the tests exercise. The render-level emit assertion is deferred (see *Out of scope*); the wiring locks the `track.id` field shape with an inline comment.

- [ ] Write the failing test `frontend/src/features/playback/lib/telemetryMap.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { resolvePlaybackSource, seekEventProps } from './telemetryMap';
import type { QueueSource } from './types';

describe('resolvePlaybackSource', () => {
  it('prefers the explicit source arg', () => {
    const q: QueueSource = { type: 'bucket', blockId: 'b', bucketId: 'k' };
    expect(resolvePlaybackSource('category_player', q)).toBe('category_player');
  });
  it('maps bucket→triage_player, category→category_player, playlist→playlist_player', () => {
    expect(resolvePlaybackSource(undefined, { type: 'bucket', blockId: 'b', bucketId: 'k' })).toBe(
      'triage_player',
    );
    expect(resolvePlaybackSource(undefined, { type: 'category', categoryId: 'c', styleId: 's' })).toBe(
      'category_player',
    );
    expect(resolvePlaybackSource(undefined, { type: 'playlist', playlistId: 'p' })).toBe(
      'playlist_player',
    );
  });
  it('falls back to triage_player when no queue source is bound', () => {
    expect(resolvePlaybackSource(undefined, null)).toBe('triage_player');
  });
});

describe('seekEventProps', () => {
  it('reads from_position from the current player position and clamps the target', () => {
    expect(seekEventProps(12_345, 200_000, 50_000)).toEqual({
      from_position_ms: 12_345,
      to_position_ms: 50_000,
    });
  });
  it('clamps to_position to [0, duration]', () => {
    expect(seekEventProps(0, 100_000, 999_999).to_position_ms).toBe(100_000);
    expect(seekEventProps(0, 100_000, -5).to_position_ms).toBe(0);
  });
});
```
  (If `QueueSource`'s variant fields differ, match the real `types.ts` shape — the mapper switches on `.type` only, so the extra fields are inert.)
- [ ] Run it, expect FAIL: `pnpm test src/features/playback/lib/telemetryMap.test.ts` → `Failed to resolve import "./telemetryMap"`.
- [ ] Add `PlaybackSource` to `frontend/src/features/playback/lib/types.ts` (after the `QueueSource` union):
```ts
export type PlaybackSource = 'triage_player' | 'playlist_player' | 'category_player';
```
- [ ] Create `frontend/src/features/playback/lib/telemetryMap.ts`:
```ts
import { clampMs } from './seekHotkeys';
import type { PlaybackSource, QueueSource } from './types';

const SOURCE_BY_QUEUE: Record<QueueSource['type'], PlaybackSource> = {
  bucket: 'triage_player',
  category: 'category_player',
  playlist: 'playlist_player',
};

export function resolvePlaybackSource(
  explicit: PlaybackSource | undefined,
  queueSource: QueueSource | null,
): PlaybackSource {
  if (explicit) return explicit;
  return queueSource ? SOURCE_BY_QUEUE[queueSource.type] : 'triage_player';
}

export function seekEventProps(
  currentPositionMs: number,
  durationMs: number,
  targetMs: number,
): { from_position_ms: number; to_position_ms: number } {
  return {
    from_position_ms: currentPositionMs,
    to_position_ms: clampMs(targetMs, durationMs),
  };
}
```
  (If `clampMs` lives elsewhere or has a different signature, import the real clamp helper; the test pins the [0, duration] behaviour.)
- [ ] Run it, expect PASS: `pnpm test src/features/playback/lib/telemetryMap.test.ts` → `Tests 5 passed (5)`.
- [ ] Wire the emits in `frontend/src/features/playback/PlaybackProvider.tsx`:
  - Add imports:
```ts
import { useTelemetry } from '../../lib/telemetry/hooks';
import { debounceTrack } from '../../lib/telemetry/sdk';
import { resolvePlaybackSource, seekEventProps } from './lib/telemetryMap';
import type { PlaybackSource } from './lib/types';
```
  - In `PlaybackProvider`, near the top of the body (after `onAuthExpired`):
```ts
  const telemetry = useTelemetry();
  const seekTrackRef = useRef(debounceTrack(500));
```
  - Change the `controls.play` type in `PlaybackContextValue`:
```ts
    play: (idx?: number, overrideTrack?: PlaybackTrack, source?: PlaybackSource) => Promise<void>;
```
  - Update `play` signature + emit. Replace the callback head and add the emit right after the existing `setTrack(() => ({ current: track, ... }))` seeding:
```ts
  const play = useCallback(
    async (idx?: number, overrideTrack?: PlaybackTrack, source?: PlaybackSource) => {
```
    …and after the existing `setTrack(() => ({ current: track, durationMs: track.duration_ms || 0, positionMs: 0 }));`:
```ts
      // track.id is PlaybackTrack.id (NOT track_id) — the BucketTrack/PlaybackTrack footgun (MUST-FIX 3).
      telemetry.track('playback_play', {
        track_id: track.id,
        position_ms: 0,
        duration_ms: track.duration_ms,
        source: resolvePlaybackSource(source, queue.source),
      });
```
    …and extend the dep array to include `queue.source` and `telemetry`:
```ts
    [queue.cursor, queue.tracks, queue.source, ensureSdk, onAuthExpired, telemetry],
```
  - In `seekMs`, emit the debounced seek before dispatching to SDK/Web API. Insert at the top of the callback body, after `const clamped = clampMs(...)`:
```ts
      seekTrackRef.current('playback_seek', {
        track_id: track.current?.id ?? null,
        ...seekEventProps(track.positionMs, track.durationMs || 0, ms),
      });
```
    `track.positionMs` is the SDK-source-of-truth position state (set by `player_state_changed`) — the real reducer/ref variable, not an undefined field. Add `track.positionMs` and `track.current` to the dep array:
```ts
    [track.durationMs, track.positionMs, track.current, onAuthExpired],
```
- [ ] Pass `source` at the two real initiating call sites:
  - `frontend/src/features/triage/routes/BucketDetailPage.tsx` `playTrack` → `play(queueIdx, undefined, 'triage_player')` and `play(undefined, toPlaybackTrack(tr), 'triage_player')`.
  - `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` `onPlay` → `play(queueIdx, undefined, 'playlist_player')` and `play(undefined, toPlaybackTrack(track), 'playlist_player')`.
  (Curate auto-play/undo keep the call unchanged — they bind a `bucket` queue source, so the default map already yields `triage_player`.)
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Run the full playback area to confirm no regression: `pnpm test src/features/playback` → all green.
- [ ] Commit via caveman-commit: `git add frontend/src/features/playback frontend/src/features/triage/routes/BucketDetailPage.tsx frontend/src/features/playlists/routes/PlaylistDetailPage.tsx && git commit -m "<subject>"`.

---

### Task 6: Triage — `track_view`, session start/end, categorize, undo

**Files:**
- Modify `frontend/src/features/triage/components/BucketTrackRow.tsx` (add hook)
- Create `frontend/src/features/triage/components/BucketTrackRow.test.tsx`
- Modify `frontend/src/features/triage/routes/BucketDetailPage.tsx` (refs/telemetry; session effect; `handleMove`)
- Create `frontend/src/features/triage/routes/BucketDetailPage.telemetry.test.tsx`

- [ ] Write the failing test `frontend/src/features/triage/components/BucketTrackRow.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MantineProvider, Table } from '@mantine/core';
import { BucketTrackRow } from './BucketTrackRow';
import { telemetry } from '../../../lib/telemetry/sdk';
import type { BucketTrack } from '../hooks/useBucketTracks';

const track: BucketTrack = {
  track_id: 'tr-7',
  title: 'Title',
  mix_name: null,
  isrc: null,
  bpm: 120,
  length_ms: 200_000,
  publish_date: null,
  spotify_release_date: null,
  spotify_id: 'sp-7',
  release_type: null,
  is_ai_suspected: false,
  artists: [{ id: 'a', name: 'Artist', role: 'main' }],
  label_id: null,
  label_name: null,
  added_at: '2026-01-01',
};

function renderRow() {
  return render(
    <MantineProvider>
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={[]}
            currentBucketId="b1"
            onMove={() => {}}
            showMoveMenu={false}
          />
        </Table.Tbody>
      </Table>
    </MantineProvider>,
  );
}

describe('BucketTrackRow track_view', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('counts the row as seen on mount and emits track_view (track_id, not id) on unmount', () => {
    const trackSpy = vi.spyOn(telemetry, 'track');
    const seenSpy = vi.spyOn(telemetry, 'markSeen');
    const { unmount } = renderRow();
    expect(seenSpy).toHaveBeenCalledWith('tr-7');
    unmount();
    expect(trackSpy).toHaveBeenCalledWith(
      'track_view',
      expect.objectContaining({ track_id: 'tr-7' }),
    );
  });
});
```
- [ ] Run it, expect FAIL: `pnpm test src/features/triage/components/BucketTrackRow.test.tsx` → assertion fail (`markSeen` never called).
- [ ] Wire `BucketTrackRow.tsx` — add import + call at the top of the component body:
```ts
import { useTrackView } from '../../../lib/telemetry/hooks';
// ...inside BucketTrackRow, first line of the body:
  useTrackView(track.track_id);
```
- [ ] Run it, expect PASS: `pnpm test src/features/triage/components/BucketTrackRow.test.tsx` → `Tests 1 passed (1)`.
- [ ] Wire `BucketDetailPage.tsx` — in `BucketDetailInner`:
  - Import:
```ts
import { useTelemetry } from '../../../lib/telemetry/hooks';
```
  - After `const undoInflight = useRef(false);`:
```ts
  const telemetry = useTelemetry();
  const assignsRef = useRef(0); // total_assigns = moved_to_bucket count
  const undoCountRef = useRef(0);
```
  - Session start/end effect (place with the other top-level hooks, before the early returns):
```ts
  useEffect(() => {
    telemetry.resetSeen();
    assignsRef.current = 0;
    undoCountRef.current = 0;
    const startedAt = Date.now();
    telemetry.track('triage_session_start', { block_id: blockId, bucket_id: bucketId });
    return () => {
      const total = assignsRef.current;
      telemetry.track('triage_session_end', {
        session_ms: Date.now() - startedAt,
        tracks_seen: telemetry.seenCount(),
        tracks_categorized: total,
        undo_rate: total > 0 ? undoCountRef.current / total : 0,
      });
    };
  }, [telemetry, blockId, bucketId]);
```
  - In `handleMove`, inside `move.mutate`'s `onSuccess` (right after the opening `onSuccess: () => {`):
```ts
        assignsRef.current += 1;
        telemetry.track('track_categorized', {
          track_id: trackId,
          decision_ms: telemetry.msSinceShown(trackId),
          category_key: toBucket.bucket_type,
          action: 'moved_to_bucket',
        });
```
  - In the inline undo `onClick`, inside the `try` block right after `await undoMoveDirect(...)` succeeds (before the success toast):
```ts
                    undoCountRef.current += 1;
                    telemetry.track('track_categorized', {
                      track_id: trackId,
                      surface: 'triage',
                      category_key: toBucket.bucket_type, // reverted-from bucket type
                      action: 'undo',
                    });
```
  (`trackId` and `toBucket` are the real `handleMove` params in closure scope.)
- [ ] Write the failing test `frontend/src/features/triage/routes/BucketDetailPage.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';

// BucketDetailInner + BucketTrackRow/PlayPauseButton call usePlayback(), which throws
// without a <PlaybackProvider>. Mock it the way the existing integration test does.
vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: true, error: null },
    controls: {
      prewarm: async () => {},
      play: async () => {},
      pause: async () => {},
      togglePlayPause: async () => {},
      next: async () => {},
      prev: async () => {},
      seekMs: async () => {},
      seekPct: async () => {},
      bindQueue: () => {},
      clearQueue: () => {},
      cancelPendingAdvance: () => {},
      openSpotifyExternal: () => {},
    },
    devices: {
      list: [], active: null, cloderTabId: null, isLoading: false, error: null,
      isOpen: false, pickerAnchor: null,
      open: () => {}, close: () => {}, refresh: async () => {}, pick: async () => {},
    },
  }),
}));

import { server } from '../../../test/setup';
import { telemetry } from '../../../lib/telemetry/sdk';
import { tokenStore } from '../../../auth/tokenStore';
import { BucketDetailPage } from './BucketDetailPage';

const BLOCK = {
  id: 'blk1',
  style_id: 'sty1',
  name: 'Block',
  status: 'IN_PROGRESS',
  date_from: '2026-01-01',
  date_to: '2026-01-07',
  buckets: [
    { id: 'src', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
    { id: 'dst', bucket_type: 'FAV', category_id: null, category_name: null, inactive: false, track_count: 0 },
  ],
};
const TRACK = {
  track_id: 'tr-1', title: 'Song', mix_name: null, isrc: null, bpm: 120, length_ms: 200000,
  publish_date: null, spotify_release_date: null, spotify_id: 'sp-1', release_type: null,
  is_ai_suspected: false, artists: [{ id: 'a', name: 'Art', role: 'main' }],
  label_id: null, label_name: null, added_at: '2026-01-01',
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <MemoryRouter initialEntries={['/triage/sty1/blk1/buckets/src']}>
          <Routes>
            <Route path="/triage/:styleId/:id/buckets/:bucketId" element={<BucketDetailPage />} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('BucketDetailPage telemetry', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true');
    tokenStore.set('jwt');
    server.use(
      http.get('http://localhost/triage/blocks/blk1', () => HttpResponse.json(BLOCK)),
      http.get('http://localhost/triage/blocks/blk1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [TRACK], total: 1, limit: 50, offset: 0 })),
      // Real move endpoint is /triage/blocks/{blockId}/move; MoveResponse.moved is a number.
      http.post('http://localhost/triage/blocks/blk1/move', () => HttpResponse.json({ moved: 1 })),
    );
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    tokenStore.set(null);
  });

  it('emits session_start on enter and session_end (real tracks_seen) on leave', async () => {
    const trackSpy = vi.spyOn(telemetry, 'track');
    const { unmount } = renderPage();
    await screen.findByText('Song');
    expect(trackSpy).toHaveBeenCalledWith('triage_session_start', { block_id: 'blk1', bucket_id: 'src' });
    unmount();
    const end = trackSpy.mock.calls.find((c) => c[0] === 'triage_session_end');
    expect(end).toBeDefined();
    expect((end![1] as { tracks_seen: number }).tracks_seen).toBeGreaterThanOrEqual(1);
  });

  it('emits track_categorized(moved_to_bucket) on a move success', async () => {
    const trackSpy = vi.spyOn(telemetry, 'track');
    renderPage();
    await screen.findByText('Song');
    await userEvent.click(await screen.findByRole('button', { name: /move track/i }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /move to FAV/i }));
    await waitFor(() =>
      expect(trackSpy).toHaveBeenCalledWith(
        'track_categorized',
        expect.objectContaining({ track_id: 'tr-1', category_key: 'FAV', action: 'moved_to_bucket' }),
      ),
    );
  });
});
```
  (Move trigger/menuitem selectors mirror the existing `BucketDetailPage.integration.test.tsx` — `/Move track/` button → `/Move to <bucket>/` menuitem. If `bucketLabel` renders FAV differently, adjust the menuitem text; the `telemetry.track('track_categorized', …)` assertion is the load-bearing part.)
- [ ] Run it, expect PASS: `pnpm test src/features/triage/routes/BucketDetailPage.telemetry.test.tsx` → `Tests 2 passed (2)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Commit via caveman-commit: `git add frontend/src/features/triage && git commit -m "<subject>"`.

---

### Task 7: Curate — `track_categorized` (categorize + undo) with real `decision_ms`/`category_key`

**Files:**
- Modify `frontend/src/features/curate/hooks/useCurateSession.ts` (telemetry; `markShown` effect; `fireMutation`; `assign`; `undo`)
- Create `frontend/src/features/curate/hooks/useCurateSession.telemetry.test.tsx`

`LastOp` has no `decisionMs`/`categoryKey`/`action`. Source `decision_ms` from `msSinceShown(trackId)` + a `markShown` effect when the current track changes; `category_key` from the destination bucket object (`dst`) in `assign`; `action` from the real assign vs undo path.

- [ ] Wire `useCurateSession.ts`:
  - Import: `import { useTelemetry } from '../../../lib/telemetry/hooks';` (ensure `useEffect` is imported from React).
  - After `const playback = usePlayback();`: `const telemetry = useTelemetry();`
  - Start the decision timer when the current track becomes visible (add after `const currentTrack = queue[state.currentIndex] ?? null;`):
```ts
  useEffect(() => {
    if (currentTrack) telemetry.markShown(currentTrack.track_id);
  }, [currentTrack?.track_id, telemetry]);
```
  - Give `fireMutation` the destination bucket type. Change its signature to accept `categoryKey` and emit in `onSuccess`:
```ts
  const fireMutation = useCallback(
    (input: MoveInput, lastOp: LastOp, categoryKey: string) => {
      moveMutate(input, {
        onSuccess: () => {
          writeLastCurateLocation(styleId, blockId, bucketId);
          writeLastCurateStyle(styleId);
          const trackId = input.trackIds[0];
          if (trackId) {
            telemetry.track('track_categorized', {
              track_id: trackId,
              decision_ms: telemetry.msSinceShown(trackId),
              category_key: categoryKey,
              action: 'categorized_curate',
            });
          }
          const cur = stateRef.current.lastOp;
          if (!cur || cur !== lastOp) return;
          if (lastOp.forceCategoryId && trackId) {
            addToCategoryMutate(/* …unchanged… */);
          }
        },
        onError: (err) => { /* …unchanged… */ },
      });
    },
    [moveMutate, addToCategoryMutate, blockId, bucketId, styleId, emitErrorToast, t, telemetry],
  );
```
  - In `assign`, both `fireMutation(...)` call sites pass `dst?.bucket_type ?? ''` (the in-scope destination bucket object: `const dst = destinations.find((b) => b.id === toBucketId)`):
    - replace-path: `fireMutation(input, newLastOp, dst?.bucket_type ?? '');`
    - fresh-path: `fireMutation(input, newLastOp, dst?.bucket_type ?? '');`
  - In `undo`, emit `action: 'undo'` after the rollback in both branches. Compute the reverted-from category key from the destination bucket the op targeted:
```ts
    const revertedKey =
      destinations.find((b) => b.id === lastOp.input.toBucketId)?.bucket_type ?? '';
    const undoTrackId = lastOp.input.trackIds[0];
    if (undoTrackId) {
      telemetry.track('track_categorized', {
        track_id: undoTrackId,
        surface: 'curate',
        category_key: revertedKey,
        action: 'undo',
      });
    }
```
    Place this right after each `void undoMoveDirect(...).catch(...)` call (the `isPending` branch and the else branch). Add `destinations` and `telemetry` to the `undo` dep array.
- [ ] Write the test `frontend/src/features/curate/hooks/useCurateSession.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { renderHook, waitFor, act } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

// useCurateSession calls usePlayback(); mounting a real <PlaybackProvider> would need an
// <AuthProvider> (PlaybackProvider's first line is useAuth()). Mock usePlayback instead —
// this mirrors the established frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx.
vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: async () => {}, pause: async () => {}, togglePlayPause: async () => {},
      next: async () => {}, prev: async () => {}, seekMs: async () => {}, seekPct: async () => {},
      bindQueue: () => {}, clearQueue: () => {}, cancelPendingAdvance: () => {},
      prewarm: async () => {}, openSpotifyExternal: () => {},
    },
  }),
}));

import { server } from '../../../test/setup';
import { telemetry } from '../../../lib/telemetry/sdk';
import { tokenStore } from '../../../auth/tokenStore';
import { useCurateSession } from './useCurateSession';

const BLOCK = {
  id: 'blk1', style_id: 'sty1', name: 'B', status: 'IN_PROGRESS',
  date_from: '2026-01-01', date_to: '2026-01-07',
  buckets: [
    { id: 'src', bucket_type: 'STAGING', category_id: null, category_name: 'S', inactive: false, track_count: 1 },
    { id: 'dst', bucket_type: 'FAV', category_id: null, category_name: null, inactive: false, track_count: 0 },
  ],
};
const TRACK = {
  track_id: 'tr-1', title: 'S', mix_name: null, isrc: null, bpm: 1, length_ms: 1000,
  publish_date: null, spotify_release_date: null, spotify_id: 'sp', release_type: null,
  is_ai_suspected: false, artists: [], label_id: null, label_name: null, added_at: '2026-01-01',
};

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

describe('useCurateSession telemetry', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true');
    tokenStore.set('jwt');
    server.use(
      http.get('http://localhost/triage/blocks/blk1', () => HttpResponse.json(BLOCK)),
      http.get('http://localhost/triage/blocks/blk1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [TRACK], total: 1, limit: 50, offset: 0 })),
      // Real move endpoint; undoMoveDirect also POSTs here. MoveResponse.moved is a number.
      http.post('http://localhost/triage/blocks/blk1/move', () => HttpResponse.json({ moved: 1 })),
    );
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    tokenStore.set(null);
  });

  it('assign emits track_categorized(categorized_curate) with category_key from the destination', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'blk1', bucketId: 'src', styleId: 'sty1' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.currentTrack?.track_id).toBe('tr-1'));
    act(() => result.current.assign('dst'));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'track_categorized',
        expect.objectContaining({ track_id: 'tr-1', category_key: 'FAV', action: 'categorized_curate' }),
      ),
    );
    const props = spy.mock.calls.find(
      (c) => c[0] === 'track_categorized' && (c[1] as { action: string }).action === 'categorized_curate',
    )![1] as { decision_ms: number };
    expect(Number.isInteger(props.decision_ms)).toBe(true);
  });

  it('undo emits track_categorized(undo, surface=curate)', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'blk1', bucketId: 'src', styleId: 'sty1' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.currentTrack?.track_id).toBe('tr-1'));
    act(() => result.current.assign('dst'));
    await waitFor(() => expect(result.current.canUndo).toBe(true));
    act(() => result.current.undo());
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'track_categorized',
        expect.objectContaining({ track_id: 'tr-1', surface: 'curate', action: 'undo' }),
      ),
    );
  });
});
```
  (If `useCurateSession`'s public surface uses different names than `currentTrack`/`assign`/`undo`/`canUndo`, match the real hook return — the `telemetry.track('track_categorized', …)` assertions are load-bearing.)
- [ ] Run it, expect PASS after wiring: `pnpm test src/features/curate/hooks/useCurateSession.telemetry.test.tsx` → `Tests 2 passed (2)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Commit via caveman-commit: `git add frontend/src/features/curate/hooks/useCurateSession.ts frontend/src/features/curate/hooks/useCurateSession.telemetry.test.tsx && git commit -m "<subject>"`.

---

### Task 8: Curate — `hotkey_used` + `CurateSessionPage` route context

**Files:**
- Modify `frontend/src/features/curate/hooks/useCurateHotkeys.ts` (telemetry import; per-case emit)
- Create `frontend/src/features/curate/hooks/useCurateHotkeys.telemetry.test.tsx`
- Modify `frontend/src/features/curate/routes/CurateSessionPage.tsx`
- Create `frontend/src/features/curate/routes/CurateSessionPage.test.tsx`

Map ONLY the real cases to the 4-value enum `{assign_destination, undo, toggle_force, open_help}`. There is no `Slash` switch case and no `action` local — emit inline at each real branch. Escape (exit/close-overlay) is not one of the four, so it emits nothing.

- [ ] Wire `useCurateHotkeys.ts`:
  - Import: `import { useTelemetry } from '../../../lib/telemetry/hooks';`
  - In the hook body: `const telemetry = useTelemetry();`
  - `?` branch (open help) — before `onOpenOverlay()`:
```ts
        telemetry.track('hotkey_used', { hotkey_code: 'Slash', action: 'open_help', source: 'curate' });
```
  - `KeyU` (undo) — before `onUndo()`:
```ts
          telemetry.track('hotkey_used', { hotkey_code: 'KeyU', action: 'undo', source: 'curate' });
```
  - `KeyL` (toggle force) — before `onToggleForce()` (inside the non-overlay path):
```ts
          telemetry.track('hotkey_used', { hotkey_code: 'KeyL', action: 'toggle_force', source: 'curate' });
```
  - `KeyQ`/`KeyW`/`KeyE`/`KeyZ` and the `DIGIT_CODES` default — emit `assign_destination` with the real `event.code` only when a destination resolves (`if (b)`), immediately before `onAssign(b.id)`:
```ts
          telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
```
  - Add `telemetry` to the effect dependency array.
- [ ] Write the test `frontend/src/features/curate/hooks/useCurateHotkeys.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { telemetry } from '../../../lib/telemetry/sdk';
import { useCurateHotkeys } from './useCurateHotkeys';

const BUCKETS = [
  { id: 'q', bucket_type: 'NEW', inactive: false, track_count: 0 },
  { id: 'd', bucket_type: 'DISCARD', inactive: false, track_count: 0 },
] as const;

function setup(over: Partial<Parameters<typeof useCurateHotkeys>[0]> = {}) {
  const onAssign = vi.fn();
  const onUndo = vi.fn();
  const onToggleForce = vi.fn();
  const onOpenOverlay = vi.fn();
  renderHook(() =>
    useCurateHotkeys({
      buckets: BUCKETS as never,
      overlayOpen: false,
      onAssign,
      onUndo,
      onOpenOverlay,
      onCloseOverlay: vi.fn(),
      onExit: vi.fn(),
      onToggleForce,
      ...over,
    }),
  );
  return { onAssign, onUndo, onToggleForce, onOpenOverlay };
}

function key(init: KeyboardEventInit) {
  window.dispatchEvent(new KeyboardEvent('keydown', init));
}

describe('useCurateHotkeys telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('KeyU emits action=undo and fires onUndo', () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { onUndo } = setup();
    key({ code: 'KeyU' });
    expect(onUndo).toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyU', action: 'undo', source: 'curate' });
  });

  it('KeyL emits action=toggle_force', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ code: 'KeyL' });
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyL', action: 'toggle_force', source: 'curate' });
  });

  it('KeyQ emits action=assign_destination with the real code', () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { onAssign } = setup();
    key({ code: 'KeyQ' });
    expect(onAssign).toHaveBeenCalledWith('q');
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyQ', action: 'assign_destination', source: 'curate' });
  });

  it('"?" emits action=open_help with hotkey_code Slash', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ key: '?', code: 'Slash' });
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'Slash', action: 'open_help', source: 'curate' });
  });

  it('Escape emits nothing (not one of the four actions)', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ code: 'Escape' });
    expect(spy).not.toHaveBeenCalled();
  });
});
```
  (Match the real `useCurateHotkeys` argument object keys and the `KeyQ→bucket` mapping; if `onToggleForce`/`onOpenOverlay` have different names, align the stub.)
- [ ] Run it, expect PASS after wiring: `pnpm test src/features/curate/hooks/useCurateHotkeys.telemetry.test.tsx` → `Tests 5 passed (5)`.
- [ ] Wire `CurateSessionPage.tsx` — add the route hook so curate events carry `context.route`:
```ts
import { useTelemetryRoute } from '../../../lib/telemetry/hooks';
// ...inside CurateSessionPage, before the early-return guard:
  useTelemetryRoute('/curate/:styleId/:blockId/:bucketId');
```
- [ ] Write the test `frontend/src/features/curate/routes/CurateSessionPage.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { telemetry } from '../../../lib/telemetry/sdk';
import { CurateSessionPage } from './CurateSessionPage';

vi.mock('../components/CurateSession', () => ({ CurateSession: () => <div>session</div> }));

describe('CurateSessionPage route telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('sets the curate route pattern on mount, clears on unmount', () => {
    const setRoute = vi.spyOn(telemetry, 'setRoute');
    const { unmount } = render(
      <MemoryRouter initialEntries={['/curate/sty1/blk1/buck1']}>
        <Routes>
          <Route path="/curate/:styleId/:blockId/:bucketId" element={<CurateSessionPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(setRoute).toHaveBeenCalledWith('/curate/:styleId/:blockId/:bucketId');
    unmount();
    expect(setRoute).toHaveBeenLastCalledWith(null);
  });
});
```
  (If `CurateSessionPage` renders a different child than `CurateSession`, mock that child so the page mounts without a full data/playback stack.)
- [ ] Run it, expect PASS: `pnpm test src/features/curate/routes/CurateSessionPage.test.tsx` → `Tests 1 passed (1)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Commit via caveman-commit: `git add frontend/src/features/curate && git commit -m "<subject>"`.

---

### Task 9: Playlists — `playlist_add` + `playlist_publish` (spotify + ytmusic)

**Files:**
- Modify `frontend/src/features/playlists/components/AddTracksModal.tsx` (`handleSubmit`)
- Create `frontend/src/features/playlists/components/AddTracksModal.telemetry.test.tsx`
- Modify `frontend/src/features/playlists/components/PublishButton.tsx` (props + `doPublish`)
- Modify `frontend/src/features/playlists/components/PublishYtMusicButton.tsx` (props + `doPublish`)
- Modify `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` (pass `trackIds`)
- Create `frontend/src/features/playlists/components/PublishButton.telemetry.test.tsx`
- Create `frontend/src/features/playlists/components/PublishYtMusicButton.telemetry.test.tsx`

`playlist_add` `track_ids` come from the `selected` set; `source_category_id` is the modal's real in-scope `categoryId` state (§3.2's "category the tracks came from when in scope") — use `categoryId ?? null`. `playlist_publish` `track_ids` come from the playlist's current track list (passed in as a prop); `PublishResult`/`YtmusicPublishResult` have **no** `published_count` — use `trackIds.length` for `track_count` and `r.skipped_tracks.length` for `skipped_count`.

- [ ] Wire `AddTracksModal.tsx` — import + emit in `handleSubmit`, in the `try` block after `mutateAsync` resolves and before `onAdded()`:
```ts
import { useTelemetry } from '../../../lib/telemetry/hooks';
// ...in the component body:
  const telemetry = useTelemetry();
// ...inside handleSubmit, after the await resolves:
      telemetry.track('playlist_add', {
        track_ids: Array.from(selected),
        playlist_id: playlistId,
        track_count: selected.size,
        source_category_id: categoryId ?? null,
      });
```
- [ ] Wire `PublishButton.tsx`:
  - Props: add `trackIds: string[]` to `PublishButtonProps`; destructure `{ playlist, trackIds }`.
  - Import `useTelemetry`; `const telemetry = useTelemetry();`.
  - In `doPublish`, after `setConfirmOpen(false);` (publish succeeded), before the success toast:
```ts
      telemetry.track('playlist_publish', {
        track_ids: trackIds,
        playlist_id: playlist.id,
        track_count: trackIds.length,
        confirm_overwrite: confirmOverwrite,
        skipped_count: r.skipped_tracks.length,
        target: 'spotify',
      });
```
- [ ] Wire `PublishYtMusicButton.tsx` — identical, `target: 'ytmusic'` (the `usePublishYtmusic` success path resolves `YtmusicPublishResult`, which also has `skipped_tracks`): add `trackIds: string[]` prop, destructure `{ playlist, trackIds }`, `useTelemetry`, and after `setConfirmOpen(false);` in `doPublish`:
```ts
      telemetry.track('playlist_publish', {
        track_ids: trackIds,
        playlist_id: playlist.id,
        track_count: trackIds.length,
        confirm_overwrite: confirmOverwrite,
        skipped_count: r.skipped_tracks.length,
        target: 'ytmusic',
      });
```
- [ ] Pass the playlist's current track ids in `PlaylistDetailPage.tsx` (both publish buttons):
```tsx
            <PublishButton playlist={playlist} trackIds={tracks.map((t) => t.track_id)} />
            <PublishYtMusicButton playlist={playlist} trackIds={tracks.map((t) => t.track_id)} />
```
- [ ] Write the test `frontend/src/features/playlists/components/AddTracksModal.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { telemetry } from '../../../lib/telemetry/sdk';
import { AddTracksModal } from './AddTracksModal';

vi.mock('../../../hooks/useStyles', () => ({
  useStyles: () => ({ data: { items: [{ id: 's1', name: 'Style' }] } }),
}));
vi.mock('../../categories/hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({ data: { items: [{ id: 'c1', name: 'Cat' }] } }),
}));
vi.mock('../../categories/hooks/useCategoryTracks', () => ({
  useCategoryTracks: () => ({ data: { pages: [{ items: [{ id: 't1', title: 'Song A' }] }] } }),
}));
const mutateAsync = vi.fn().mockResolvedValue({ added: ['t1'], skipped_duplicates: [], position_after: 1 });
vi.mock('../hooks/useAddTracksToPlaylist', () => ({
  useAddTracksToPlaylist: () => ({ mutateAsync, isPending: false }),
}));

function renderModal() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <AddTracksModal opened playlistId="pl-1" onClose={() => {}} onAdded={() => {}} />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AddTracksModal telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_add with track_ids from the selected set and the source category', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    renderModal();
    // pick style + category so the track list renders
    await userEvent.click(screen.getByLabelText(/style/i));
    await userEvent.click(await screen.findByText('Style'));
    await userEvent.click(screen.getByLabelText(/category/i));
    await userEvent.click(await screen.findByText('Cat'));
    await userEvent.click(await screen.findByText('Song A'));
    await userEvent.click(screen.getByRole('button', { name: /add|submit/i }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'playlist_add',
        expect.objectContaining({
          track_ids: ['t1'],
          playlist_id: 'pl-1',
          track_count: 1,
          source_category_id: 'c1',
        }),
      ),
    );
  });
});
```
  (Hook mock paths and `getByLabelText`/`getByRole` selectors mirror the real `AddTracksModal` imports + i18n labels; adjust if they differ. The `telemetry.track('playlist_add', …)` assertion is load-bearing.)
- [ ] Write the test `frontend/src/features/playlists/components/PublishButton.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { telemetry } from '../../../lib/telemetry/sdk';
import { PublishButton } from './PublishButton';
import type { Playlist, PublishResult } from '../lib/playlistTypes';

const RESULT: PublishResult = {
  spotify_playlist_id: 'spl', spotify_url: 'https://x', skipped_tracks: [],
  cover_failed: false, published_at: '2026-01-01',
};
const mutateAsync = vi.fn().mockResolvedValue(RESULT);
vi.mock('../hooks/usePublishPlaylist', () => ({
  usePublishPlaylist: () => ({ mutateAsync, isPending: false }),
}));

const playlist = { id: 'pl-1', name: 'P', track_count: 2, spotify_playlist_id: null } as Playlist;

describe('PublishButton telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_publish(spotify) with track_ids + skipped_count from the result', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    render(
      <MantineProvider>
        <Notifications />
        <PublishButton playlist={playlist} trackIds={['t1', 't2']} />
      </MantineProvider>,
    );
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'playlist_publish',
        expect.objectContaining({
          track_ids: ['t1', 't2'],
          playlist_id: 'pl-1',
          track_count: 2,
          skipped_count: 0,
          target: 'spotify',
        }),
      ),
    );
  });
});
```
- [ ] Write the test `frontend/src/features/playlists/components/PublishYtMusicButton.telemetry.test.tsx`:
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { telemetry } from '../../../lib/telemetry/sdk';
import { PublishYtMusicButton } from './PublishYtMusicButton';
import type { Playlist, YtmusicPublishResult } from '../lib/playlistTypes';

const RESULT: YtmusicPublishResult = {
  ytmusic_playlist_id: 'ypl', ytmusic_url: 'https://music.youtube.com/x',
  skipped_tracks: [], cover_failed: false, published_at: '2026-01-01',
};
const mutateAsync = vi.fn().mockResolvedValue(RESULT);
vi.mock('../hooks/usePublishYtmusic', () => ({
  usePublishYtmusic: () => ({ mutateAsync, isPending: false }),
}));
// PublishYtMusicButton gates handleClick on me.data.ytmusic_connected — must be connected.
vi.mock('../../../api/queries/useMe', () => ({
  useMe: () => ({ data: { ytmusic_connected: true } }),
}));

const playlist = { id: 'pl-1', name: 'P', track_count: 2, ytmusic_playlist_id: null } as Playlist;

describe('PublishYtMusicButton telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_publish(ytmusic) with track_ids + skipped_count from the result', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    render(
      <MantineProvider>
        <Notifications />
        <PublishYtMusicButton playlist={playlist} trackIds={['t1', 't2']} />
      </MantineProvider>,
    );
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'playlist_publish',
        expect.objectContaining({
          track_ids: ['t1', 't2'],
          playlist_id: 'pl-1',
          track_count: 2,
          skipped_count: 0,
          target: 'ytmusic',
        }),
      ),
    );
  });
});
```
- [ ] Run all three, expect PASS:
```bash
pnpm test src/features/playlists/components/AddTracksModal.telemetry.test.tsx src/features/playlists/components/PublishButton.telemetry.test.tsx src/features/playlists/components/PublishYtMusicButton.telemetry.test.tsx
```
  → `Test Files 3 passed (3)`, `Tests 3 passed (3)`.
- [ ] Typecheck + lint: `pnpm typecheck && pnpm lint` → exit 0.
- [ ] Commit via caveman-commit: `git add frontend/src/features/playlists && git commit -m "<subject>"`.

---

### Task 10: Full suite + gates + finish

**Files:** none (verification only)

- [ ] Run the whole frontend suite: `cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend && pnpm test` → `Test Files … passed`, `Tests … passed`, exit 0 (no regressions in playback/triage/curate/playlists).
- [ ] CI gates: `pnpm typecheck && pnpm lint && pnpm build` → all exit 0 (the production `vite build` runs `tsc -b` and the `__APP_VERSION__` `define`).
- [ ] Confirm no backend/OpenAPI drift was introduced (this increment adds no API route — that is Increment 2): `cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve && git diff --name-only origin/main -- docs/api/openapi.yaml frontend/src/api/schema.d.ts` → prints nothing.
- [ ] Manual sanity (flag default off): `grep -n "VITE_TELEMETRY_ENABLED" frontend/.env.local 2>/dev/null || echo "flag unset → track() no-ops in dev, as designed"`.
- [ ] Create the deferred-work follow-ups (Increment 1b: categories/playlists `track_view`; Increment 1c: playback secondary events + `playlist_reorder`, with the queueDispatch-status / auto-advance-vs-skip design note) as tracked issues so the uncovered §3.2 fire-points are not lost.
- [ ] Use superpowers:finishing-a-development-branch to open the PR. PR title + body generated via the `caveman:caveman-commit` skill (no hand-written subject, no `Co-Authored-By` trailer). PR body must state: SDK behind `VITE_TELEMETRY_ENABLED` (default off), the explicit deferrals (Increment 1b categories/playlists `track_view`; Increment 1c playback `pause`/`ended`/`skip`, playback `hotkey_used`, `playlist_reorder`; playback `play`/`seek` render-emit assertion deferred — logic covered by `telemetryMap` unit tests), and that `/v1/telemetry` has no backend yet (Increment 2). Then `gh pr create` from the worktree against `origin/main`.
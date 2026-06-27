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
    // vi.resetModules() creates a fresh tokenStore; set token on the fresh instance
    // ponytail: vitest v2 re-evaluates tokenStore.ts after resetModules; beforeEach token lives on old instance
    const { tokenStore: freshTs } = await import('../../auth/tokenStore');
    freshTs.set('jwt-123');
    for (let i = 0; i < 25; i++) telemetry.track('track_view', { track_id: String(i) });
    await Promise.resolve();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0]!;
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
    // ponytail: import.meta.dirname avoids vite's new URL(rel, import.meta.url) transform
    // which maps to http://localhost/... in jsdom; dirname gives the real fs path directly
    const dirPath = import.meta.dirname;
    const files = (await fs.readdir(dirPath)).filter(
      (n) => /\.(ts|tsx)$/.test(n) && !n.includes('.test.'),
    );
    expect(files).toContain('sdk.ts');
    for (const f of files) {
      const src = await fs.readFile(`${dirPath}/${f}`, 'utf8');
      expect(src, f).not.toContain('bpTokenStore');
      expect(src, f).not.toContain('localStorage');
      expect(src, f).not.toContain('sessionStorage');
    }
  });
});

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { useCurateSession } from '../useCurateSession';

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: vi.fn(async () => {}),
      pause: vi.fn(async () => {}),
      togglePlayPause: vi.fn(async () => {}),
      next: vi.fn(async () => {}),
      prev: vi.fn(async () => {}),
      seekMs: vi.fn(async () => {}),
      seekPct: vi.fn(async () => {}),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
      cancelPendingAdvance: vi.fn(),
      prewarm: vi.fn().mockResolvedValue(undefined),
      openSpotifyExternal: vi.fn(),
    },
  }),
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}
function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const block = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 1 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 0 },
  ],
};

const tracksPage = {
  items: [
    {
      track_id: 't1', title: 'Track t1', mix_name: null, isrc: null,
      bpm: 124, length_ms: 360000, publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15', spotify_id: 'sp-t1',
      release_type: 'single', is_ai_suspected: false,
      artists: ['Artist'], label_name: 'Label', added_at: '2026-04-21T00:00:00Z',
    },
  ],
  total: 1, limit: 50, offset: 0,
};

function defaults() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () => HttpResponse.json(tracksPage)),
    http.post('http://localhost/triage/blocks/b1/move', () =>
      HttpResponse.json({ moved: 1, correlation_id: 'cid-x' }),
    ),
  ];
}

describe('useCurateSession Force chain — happy path + variants', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(...defaults());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it('Force ON + tap staging fires move + category POST', async () => {
    let categoryHit = false;
    let categoryBody: unknown = null;
    server.use(
      http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
        categoryHit = true;
        categoryBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    await act(async () => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(categoryHit).toBe(true));
    expect(categoryBody).toEqual({ track_id: 't1' });
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });

  it('partial fail (category POST 500) keeps move; forceMode resets', async () => {
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    await act(async () => { vi.advanceTimersByTime(300); });
    // Move stayed (queue shrunk):
    await waitFor(() => expect(result.current.queue.length).toBe(0));
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });

  it('Force ON + tap OLD does NOT POST to /categories', async () => {
    let categoryHit = false;
    server.use(
      http.post('http://localhost/categories/:cid/tracks', () => {
        categoryHit = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('b-old'));
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(categoryHit).toBe(false);
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });

  it('skip while Force ON resets Force without HTTP', async () => {
    let moveHit = false;
    let categoryHit = false;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () => {
        moveHit = true;
        return HttpResponse.json({ moved: 1, correlation_id: 'x' });
      }),
      http.post('http://localhost/categories/:cid/tracks', () => {
        categoryHit = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.skip());
    expect(result.current.forceMode).toBe(false);
    expect(moveHit).toBe(false);
    expect(categoryHit).toBe(false);
  });

  it('undo before move response blocks category POST (race guard)', async () => {
    let categoryHit = false;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', async () => {
        await new Promise((r) => setTimeout(r, 100));
        return HttpResponse.json({ moved: 1, correlation_id: 'x' });
      }),
      http.post('http://localhost/categories/:cid/tracks', () => {
        categoryHit = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    // Within hold window, before move resolves:
    act(() => result.current.undo());
    // Let everything settle:
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(categoryHit).toBe(false);
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });
});

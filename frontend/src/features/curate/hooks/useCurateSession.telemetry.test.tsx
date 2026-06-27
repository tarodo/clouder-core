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

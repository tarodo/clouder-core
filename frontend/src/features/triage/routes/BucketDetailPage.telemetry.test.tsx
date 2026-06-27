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

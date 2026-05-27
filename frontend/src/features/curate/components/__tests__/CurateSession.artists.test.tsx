// frontend/src/features/curate/components/__tests__/CurateSession.artists.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSession } from '../CurateSession';

// Force DESKTOP mode: the ArtistsPanel lives inside the !isMobile side panel.
vi.mock('@mantine/hooks', async () => {
  const actual = await vi.importActual<typeof import('@mantine/hooks')>(
    '@mantine/hooks',
  );
  return { ...actual, useMediaQuery: vi.fn(() => false) };
});

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
    devices: {
      list: [],
      active: null,
      cloderTabId: null,
      isLoading: false,
      error: null,
      refresh: vi.fn(async () => {}),
      pick: vi.fn(async () => {}),
      open: vi.fn(),
    },
  }),
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
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
    {
      id: 'dst1',
      bucket_type: 'STAGING' as const,
      inactive: false,
      track_count: 0,
      category_id: 'c1',
      category_name: 'Big Room',
    },
  ],
};

function tracksPageWithArtists() {
  return {
    items: [
      {
        track_id: 't1',
        title: 'Track T1',
        mix_name: null,
        isrc: null,
        bpm: 124,
        length_ms: 360000,
        publish_date: '2026-04-15',
        spotify_release_date: '2026-04-15',
        spotify_id: 'sp-t1',
        release_type: 'single',
        is_ai_suspected: false,
        artists: [{ id: 'a1', name: 'Joja', role: 'main' }],
        label_id: null,
        label_name: null,
        added_at: '2026-04-21T00:00:00Z',
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  };
}

function defaultHandlers() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracksPageWithArtists()),
    ),
    http.get('http://localhost/artists/a1', () =>
      HttpResponse.json({ artist_name: 'Joja', my_preference: null }),
    ),
    http.get('http://localhost/labels/:id', () =>
      HttpResponse.json({ label_name: 'Unknown', my_preference: null }),
    ),
  ];
}

function renderSession() {
  const qc = makeClient();
  return render(
    <MemoryRouter initialEntries={['/curate/s1/b1/src']}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route
              path="/curate/:styleId/:blockId/:bucketId"
              element={<CurateSession styleId="s1" blockId="b1" bucketId="src" />}
            />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('CurateSession — artist tile', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(...defaultHandlers());
  });
  afterEach(() => {
    tokenStore.set(null);
  });

  it('renders the artist tile for the current track', async () => {
    renderSession();
    expect(await screen.findByText('Joja')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^like artist$/i })).toBeInTheDocument();
  });
});

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';

// PlaylistDetailPage now calls usePlayback() + usePlaylistPlayerQueue() on
// mount. The PlaybackProvider lives in the authenticated layout, not in this
// test harness, so stub usePlayback with a minimal noop value.
// jsdom's matchMedia stub returns matches:false → isDesktop is false → only
// the tiles list renders (not the desktop split/panel), matching pre-split
// behaviour and avoiding the need to stub the PlayerPanel hooks.
vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
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
      list: [],
      active: null,
      cloderTabId: null,
      isLoading: false,
      error: null,
      isOpen: false,
      pickerAnchor: null,
      open: () => {},
      close: () => {},
      refresh: async () => {},
      pick: async () => {},
    },
  }),
}));

import { PlaylistDetailPage } from '../PlaylistDetailPage';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: '/playlists/:id', element: children }],
    { initialEntries: ['/playlists/p1'] },
  );
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
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
  ytmusic_playlist_id: null,
  ytmusic_last_published_at: null,
  ytmusic_needs_republish: false,
  track_count: 1,
  status: 'active' as const,
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
      mix_name: null,
      artists: [],
      label: null,
      bpm: null,
      spotify_release_date: null,
      is_ai_suspected: false,
      tags: [],
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
    http.get('http://localhost/styles', () =>
      HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
    ),
  );
});

describe('PlaylistDetailPage', () => {
  it('renders title, stats, and the single track row', async () => {
    render(
      <Wrapper>
        <PlaylistDetailPage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: 'Saturday techno' })).toBeInTheDocument(),
    );
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

  it('renders YT Music drift badge when ytmusic_needs_republish is true', async () => {
    server.use(
      http.get('http://localhost/playlists/p1', () =>
        HttpResponse.json({
          ...seedPlaylist,
          ytmusic_playlist_id: 'yt1',
          ytmusic_last_published_at: '2026-05-12T00:00:00Z',
          ytmusic_needs_republish: true,
          needs_republish: false,
        }),
      ),
    );
    render(
      <Wrapper>
        <PlaylistDetailPage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: 'Saturday techno' })).toBeInTheDocument(),
    );
    expect(screen.getByText('YT Music · needs republish')).toBeInTheDocument();
    expect(screen.queryByText('Needs republish')).not.toBeInTheDocument();
  });
});

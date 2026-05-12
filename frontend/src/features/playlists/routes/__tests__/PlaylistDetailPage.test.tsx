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
});

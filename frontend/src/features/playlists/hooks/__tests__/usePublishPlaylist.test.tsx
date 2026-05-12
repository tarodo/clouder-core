import React from 'react';
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

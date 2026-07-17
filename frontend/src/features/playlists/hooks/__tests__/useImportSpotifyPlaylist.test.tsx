import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, act } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useImportSpotifyPlaylist } from '../useImportSpotifyPlaylist';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useImportSpotifyPlaylist', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/import-spotify-playlist', () =>
        HttpResponse.json({
          playlist_id: 'pl-new', name: 'Spotify Mix', imported: 2,
          skipped: 0, truncated: false, total: 2,
        }),
      ),
    );
  });

  it('posts the ref and invalidates the playlists list', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useImportSpotifyPlaylist(), {
      wrapper: makeWrapper(qc),
    });
    let res!: { playlist_id: string };
    await act(async () => {
      res = await result.current.mutateAsync({ spotifyRef: 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M' });
    });
    expect(res.playlist_id).toBe('pl-new');
    expect(spy).toHaveBeenCalledWith({ queryKey: ['playlists', 'list'] });
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useResolveMatch } from '../useResolveMatch';
import { playlistTracksKey } from '../../lib/queryKeys';
import type { PaginatedPlaylistTracks } from '../../lib/playlistTypes';

vi.mock('../../../../api/client', () => ({
  api: vi.fn(async () => ({ ytmusic: { status: 'matched', video_id: 'dQw4w9WgXcQ',
    url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', confidence: 1 } })),
}));

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useResolveMatch', () => {
  let qc: QueryClient;
  beforeEach(() => {
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const seed: PaginatedPlaylistTracks = {
      items: [{ track_id: 't1', position: 0, added_at: '', title: 'X', spotify_id: null,
        isrc: null, length_ms: null, origin: 'beatport', mix_name: null, artists: [],
        label: null, bpm: null, spotify_release_date: null, is_ai_suspected: false, tags: [],
        ytmusic: { status: 'needs_review' } }] as any,
      total: 1, limit: 200, offset: 0,
    };
    qc.setQueryData(playlistTracksKey('pl1'), seed);
  });

  it('optimistically flips the track to matched on accept', async () => {
    const { result } = renderHook(() => useResolveMatch('pl1', 't1'), { wrapper: wrapper(qc) });
    result.current.mutate({ action: 'accept', vendorTrackId: 'dQw4w9WgXcQ' });
    await waitFor(() => {
      const data = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey('pl1'));
      expect(data!.items[0].ytmusic!.status).toBe('matched');
    });
  });
});

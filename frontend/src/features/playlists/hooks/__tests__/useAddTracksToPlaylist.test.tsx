import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { renderHook, act } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useAddTracksToPlaylist } from '../useAddTracksToPlaylist';
import {
  categoryTracksKey,
  type PaginatedTracks,
} from '../../../categories/hooks/useCategoryTracks';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

function seed(qc: QueryClient, key: ReturnType<typeof categoryTracksKey>) {
  const data: InfiniteData<PaginatedTracks> = {
    pages: [
      {
        items: [
          { id: 't1', used_in_playlist: false } as never,
          { id: 't2', used_in_playlist: false } as never,
        ],
        total: 2,
        limit: 50,
        offset: 0,
      },
    ],
    pageParams: [0],
  };
  qc.setQueryData(key, data);
}

describe('useAddTracksToPlaylist patches category-tracks cache', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/:id/tracks', () =>
        HttpResponse.json({
          added: ['t1'],
          skipped_duplicates: [],
          position_after: 1,
        }),
      ),
    );
  });

  it('sets used_in_playlist=true on affected items in fresh=false cache', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = categoryTracksKey('cat-1', '', 'added_at', 'desc', [], 'all', false);
    seed(qc, key);
    const { result } = renderHook(() => useAddTracksToPlaylist(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ playlistId: 'pl-1', trackIds: ['t1'] });
    });
    const patched = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    const items = patched?.pages[0]?.items ?? [];
    const t1 = items.find((i) => i.id === 't1') as
      | { used_in_playlist: boolean }
      | undefined;
    const t2 = items.find((i) => i.id === 't2') as
      | { used_in_playlist: boolean }
      | undefined;
    expect(t1?.used_in_playlist).toBe(true);
    expect(t2?.used_in_playlist).toBe(false);
  });

  it('drops affected items from fresh=true cache and shrinks total', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = categoryTracksKey('cat-1', '', 'added_at', 'desc', [], 'all', true);
    seed(qc, key);
    const { result } = renderHook(() => useAddTracksToPlaylist(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ playlistId: 'pl-1', trackIds: ['t1'] });
    });
    const patched = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    const firstPage = patched?.pages[0];
    const ids = (firstPage?.items ?? []).map((i) => i.id);
    expect(ids).toEqual(['t2']);
    expect(firstPage?.total).toBe(1);
  });
});

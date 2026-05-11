import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRemoveTrackTag } from '../useRemoveTrackTag';
import {
  categoryTracksKey,
  type PaginatedTracks,
} from '../../../categories/hooks/useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function seed(qc: QueryClient, categoryId: string): readonly unknown[] {
  const items: PaginatedTracks['items'] = [
    {
      id: 't1', title: 't1', mix_name: null, artists: [], label: null,
      bpm: null, length_ms: null, publish_date: null,
      spotify_release_date: null, isrc: null, spotify_id: null,
      release_type: null, is_ai_suspected: false,
      added_at: 'now', source_triage_block_id: null,
      tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800' }],
    },
  ];
  const page: PaginatedTracks = { items, total: 1, limit: 50, offset: 0 };
  const key = categoryTracksKey(categoryId, '', 'added_at', 'desc', [], 'all');
  qc.setQueryData<InfiniteData<PaginatedTracks>>(key, {
    pages: [page], pageParams: [0],
  });
  return key;
}

describe('useRemoveTrackTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and optimistically removes pill', async () => {
    server.use(
      http.delete('http://localhost/tracks/t1/tags/tg1', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useRemoveTrackTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1', tagId: 'tg1',
      });
    });
    expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it('rolls back on error', async () => {
    server.use(
      http.delete('http://localhost/tracks/t1/tags/tg1', () =>
        HttpResponse.json({ error_code: 'boom', message: 'fail' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useRemoveTrackTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({ categoryId: 'c1', trackId: 't1', tagId: 'tg1' }),
    ).rejects.toBeTruthy();
    const data = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    expect(data?.pages[0]?.items[0]?.tags.map((t) => t.id)).toEqual(['tg1']);
  });
});

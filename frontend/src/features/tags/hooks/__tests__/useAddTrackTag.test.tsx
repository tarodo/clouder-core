import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useAddTrackTag } from '../useAddTrackTag';
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
      release_type: null, is_ai_suspected: false, used_in_playlist: false,
      added_at: 'now', source_triage_block_id: null,
      tags: [],
    },
  ];
  const page: PaginatedTracks = { items, total: 1, limit: 50, offset: 0 };
  const key = categoryTracksKey(categoryId, '', 'added_at', 'desc', [], 'all');
  qc.setQueryData<InfiniteData<PaginatedTracks>>(key, {
    pages: [page], pageParams: [0],
  });
  return key;
}

describe('useAddTrackTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs and resolves on 201', async () => {
    server.use(
      http.post('http://localhost/tracks/t1/tags', async ({ request }) => {
        const body = (await request.json()) as { tag_id: string };
        expect(body).toEqual({ tag_id: 'tg1' });
        return HttpResponse.json(
          { tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800',
                     created_at: 'x', updated_at: 'y' }] },
          { status: 201 },
        );
      }),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useAddTrackTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1',
        tag: { id: 'tg1', name: 'Vocal', color: '#ff8800' },
      });
    });
    expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it('optimistically appends the tag to every page; rolls back on error', async () => {
    server.use(
      http.post('http://localhost/tracks/t1/tags', () =>
        HttpResponse.json({ error_code: 'boom', message: 'fail' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useAddTrackTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1',
        tag: { id: 'tg1', name: 'Vocal', color: '#ff8800' },
      }),
    ).rejects.toBeTruthy();
    const data = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    expect(data?.pages[0]?.items[0]?.tags).toEqual([]);
  });
});

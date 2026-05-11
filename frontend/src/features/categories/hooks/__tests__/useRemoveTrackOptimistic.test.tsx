import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import { useRemoveTrackOptimistic } from '../useRemoveTrackOptimistic';
import { categoryTracksKey, type PaginatedTracks } from '../useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function seed(qc: QueryClient, categoryId: string, ids: string[]): void {
  const items = ids.map((id) => ({
    id,
    title: id,
    mix_name: null,
    artists: [],
    label: null,
    bpm: null,
    length_ms: null,
    publish_date: null,
    spotify_release_date: null,
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
  const page: PaginatedTracks = { items, total: items.length, limit: 50, offset: 0 };
  qc.setQueryData(categoryTracksKey(categoryId, '', 'added_at', 'desc'), {
    pages: [page],
    pageParams: [0],
  });
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useRemoveTrackOptimistic', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and resolves on 204', async () => {
    let hit = false;
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(hit).toBe(true);
  });

  it('treats 404 track_not_in_category as success (idempotent)', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () =>
        HttpResponse.json(
          { error_code: 'track_not_in_category', message: 'gone' },
          { status: 404 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await act(async () => {
      const r = await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      expect(r).toBeUndefined();
    });
  });

  it('invalidates source list and ["categories"] after success', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = makeClient();
    seed(qc, 'c1', ['t1']);
    qc.setQueryData(['categories'], { sentinel: true });
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(qc.getQueryState(categoryTracksKey('c1', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories'])?.isInvalidated).toBe(true);
  });

  it('optimistically shrinks source list before the network call resolves', async () => {
    let resolveDelete: (() => void) | null = null;
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', async () => {
        await new Promise<void>((r) => {
          resolveDelete = r;
        });
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });

    let p!: Promise<unknown>;
    act(() => {
      p = result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });

    // Wait until the optimistic shrink lands in the cache.
    await waitFor(() => {
      const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
        categoryTracksKey('c1', '', 'added_at', 'desc'),
      );
      expect(cached?.pages[0]?.items.map((x) => x.id)).toEqual(['t2']);
    });
    const cachedMid = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cachedMid?.pages[0]?.total).toBe(1);

    // Release the network call and settle the mutation.
    resolveDelete!();
    await act(async () => {
      await p;
    });
  });

  it('rolls back the source list on error', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = makeClient();
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).rejects.toBeInstanceOf(ApiError);
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0]?.items.map((x) => x.id)).toEqual(['t1', 't2']);
    expect(cached?.pages[0]?.total).toBe(2);
  });
});

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import {
  useMoveTrackBetweenCategories,
  MovePartialError,
} from '../useMoveTrackBetweenCategories';
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

describe('useMoveTrackBetweenCategories', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs to target then DELETEs from source on happy path', async () => {
    const calls: string[] = [];
    server.use(
      http.post('http://localhost/categories/c2/tracks', async ({ request }) => {
        calls.push(`POST ${(await request.json() as { track_id: string }).track_id}`);
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        calls.push('DELETE');
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });
    expect(calls).toEqual(['POST t1', 'DELETE']);
  });

  it('rejects without calling DELETE when POST fails', async () => {
    let deleteHit = false;
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => new HttpResponse(null, { status: 500 })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    // Catch inside act to avoid React 19 queuing the rejection for later act() calls.
    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      } catch (e) {
        caught = e;
      }
    });
    expect(caught).toBeInstanceOf(ApiError);
    expect(deleteHit).toBe(false);
  });

  it('throws MovePartialError when POST succeeds but DELETE fails', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    // Catch inside act to avoid React 19 queuing the rejection for later act() calls.
    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      } catch (e) {
        caught = e;
      }
    });
    expect(caught).toBeInstanceOf(MovePartialError);
  });

  it('optimistically shrinks the source list on mutate', async () => {
    let resolvePost: (() => void) | null = null;
    server.use(
      http.post('http://localhost/categories/c2/tracks', async () => {
        await new Promise<void>((r) => {
          resolvePost = r;
        });
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = makeClient();
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });

    let p!: Promise<unknown>;
    act(() => {
      p = result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });

    await waitFor(() => {
      const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
        categoryTracksKey('c1', '', 'added_at', 'desc'),
      );
      expect(cached?.pages[0]?.items.map((x) => x.id)).toEqual(['t2']);
    });

    resolvePost!();
    await act(async () => {
      await p;
    });
  });

  it('rolls back the source list when POST fails', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = makeClient();
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    // Catch inside act to avoid React 19 queuing the rejection for later act() calls.
    await act(async () => {
      try {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      } catch {
        // expected rejection
      }
    });
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0]?.items.map((x) => x.id)).toEqual(['t1', 't2']);
  });

  it('invalidates both categories and ["categories"] on settle', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = makeClient();
    qc.setQueryData(categoryTracksKey('c1', '', 'added_at', 'desc'), { pages: [], pageParams: [] });
    qc.setQueryData(categoryTracksKey('c2', '', 'added_at', 'desc'), { pages: [], pageParams: [] });
    qc.setQueryData(['categories'], { sentinel: true });
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });
    expect(qc.getQueryState(categoryTracksKey('c1', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(categoryTracksKey('c2', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories'])?.isInvalidated).toBe(true);
  });
});

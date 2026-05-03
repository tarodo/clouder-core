import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useBucketTracks, bucketTracksKey } from '../useBucketTracks';

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function trackFixture(id: string) {
  return {
    track_id: id,
    title: `Track ${id}`,
    mix_name: null,
    isrc: null,
    bpm: 124,
    length_ms: 360_000,
    publish_date: '2026-04-21',
    spotify_release_date: '2026-04-15',
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    artists: ['Artist'],
    added_at: '2026-04-21T08:00:00Z',
  };
}

describe('useBucketTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches the first page', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [trackFixture('t1')], total: 1, limit: 50, offset: 0 }),
      ),
    );
    const { result } = renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0]?.items[0]?.title).toBe('Track t1');
  });

  it('omits the search param when search is empty', async () => {
    let receivedUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        receivedUrl = request.url;
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(receivedUrl).toContain('limit=50'));
    expect(receivedUrl).not.toContain('search=');
  });

  it('includes the search param when search is non-empty', async () => {
    let receivedUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        receivedUrl = request.url;
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    renderHook(() => useBucketTracks('b1', 'bk1', 'foo'), { wrapper: wrap() });
    await waitFor(() => expect(receivedUrl).toContain('search=foo'));
  });

  it('paginates via getNextPageParam', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) {
          return HttpResponse.json({ items: [trackFixture('t1')], total: 2, limit: 1, offset: 0 });
        }
        return HttpResponse.json({ items: [trackFixture('t2')], total: 2, limit: 1, offset: 1 });
      }),
    );
    const { result } = renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(result.current.data?.pages.flatMap((p) => p.items)).toHaveLength(2);
  });

  it('produces a stable cache key per search term', () => {
    expect(bucketTracksKey('b1', 'bk1', '')).toEqual(['triage', 'bucketTracks', 'b1', 'bk1', '']);
    expect(bucketTracksKey('b1', 'bk1', 'foo')).toEqual([
      'triage',
      'bucketTracks',
      'b1',
      'bk1',
      'foo',
    ]);
  });
});

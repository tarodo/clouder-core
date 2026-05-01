import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoryTracks } from '../useCategoryTracks';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: 'Original Mix',
    artists: [{ id: 'a1', name: 'Artist' }],
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
}

describe('useCategoryTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('paginates with fetchNextPage', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? '0');
        return HttpResponse.json({
          items: offset === 0 ? mkTracks(0, 50) : mkTracks(50, 10),
          total: 60,
          limit: 50,
          offset,
        });
      }),
    );
    const { result } = renderHook(() => useCategoryTracks('c1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].items).toHaveLength(50);
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.data?.pages[1].items).toHaveLength(10);
    expect(result.current.hasNextPage).toBe(false);
  });

  it('passes ?search=', async () => {
    let captured = '';
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        captured = new URL(request.url).searchParams.get('search') ?? '';
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    const { result } = renderHook(() => useCategoryTracks('c1', 'tech'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('tech');
  });
});

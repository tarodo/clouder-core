import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import { useAddTrackToCategory } from '../useAddTrackToCategory';
import { categoryTracksKey } from '../useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useAddTrackToCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs /categories/:id/tracks with body { track_id }', async () => {
    let receivedBody: unknown = null;
    server.use(
      http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(receivedBody).toEqual({ track_id: 't1' });
  });

  it('invalidates ["categories", "tracks", categoryId] after success', async () => {
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => HttpResponse.json({ ok: true })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    qc.setQueryData(categoryTracksKey('c1', ''), { items: [], total: 0 });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    const state = qc.getQueryState(categoryTracksKey('c1', ''));
    expect(state?.isInvalidated).toBe(true);
  });

  it('throws ApiError on 5xx', async () => {
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

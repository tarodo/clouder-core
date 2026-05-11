import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useDeleteTag } from '../useDeleteTag';
import { tagsKey } from '../useTags';

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

describe('useDeleteTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and resolves on 204', async () => {
    let hit = false;
    server.use(
      http.delete('http://localhost/tags/tg1', () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1' });
    });
    expect(hit).toBe(true);
  });

  it('treats 404 tag_not_found as success (idempotent)', async () => {
    server.use(
      http.delete('http://localhost/tags/missing', () =>
        HttpResponse.json(
          { error_code: 'tag_not_found', message: 'gone' },
          { status: 404 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'missing' });
    });
    // No throw means "success" path was taken
  });

  it('invalidates tags AND categories/tracks on settle', async () => {
    server.use(
      http.delete('http://localhost/tags/tg1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'tg1' }]);
    qc.setQueryData(['categories', 'tracks', 'c1', '', 'added_at', 'desc', '', 'all'], { sentinel: true });
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1' });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories', 'tracks', 'c1', '', 'added_at', 'desc', '', 'all'])?.isInvalidated).toBe(true);
  });
});

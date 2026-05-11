import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRenameTag } from '../useRenameTag';
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

describe('useRenameTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('PATCHes and returns the updated row', async () => {
    server.use(
      http.patch('http://localhost/tags/tg1', async ({ request }) => {
        const body = (await request.json()) as { name?: string; color?: string | null };
        expect(body).toEqual({ name: 'Vocal F', color: null });
        return HttpResponse.json({
          id: 'tg1', name: 'Vocal F', color: null,
          created_at: 'x', updated_at: 'y',
        });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useRenameTag(), { wrapper: wrap(qc) });
    let row;
    await act(async () => {
      row = await result.current.mutateAsync({
        tagId: 'tg1',
        patch: { name: 'Vocal F', color: null },
      });
    });
    expect(row).toMatchObject({ id: 'tg1', name: 'Vocal F', color: null });
  });

  it('invalidates the tags list on success', async () => {
    server.use(
      http.patch('http://localhost/tags/tg1', () =>
        HttpResponse.json({
          id: 'tg1', name: 'X', color: '#fff',
          created_at: 'x', updated_at: 'y',
        }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'tg1' }]);
    const { result } = renderHook(() => useRenameTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1', patch: { name: 'X' } });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
  });
});

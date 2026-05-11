import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCreateTag } from '../useCreateTag';
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

describe('useCreateTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs and returns the new row', async () => {
    server.use(
      http.post('http://localhost/tags', async ({ request }) => {
        const body = (await request.json()) as { name: string; color: string | null };
        expect(body).toEqual({ name: 'Vocal', color: '#ff8800' });
        return HttpResponse.json({
          id: 'tg-new', name: 'Vocal', color: '#ff8800',
          created_at: 'now', updated_at: 'now',
        }, { status: 201 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    let created;
    await act(async () => {
      created = await result.current.mutateAsync({ name: 'Vocal', color: '#ff8800' });
    });
    expect(created).toMatchObject({ id: 'tg-new', color: '#ff8800' });
  });

  it('invalidates the tags list on success', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json({
          id: 'tg-new', name: 'Vocal', color: null,
          created_at: 'now', updated_at: 'now',
        }, { status: 201 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'old' }]);
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'Vocal', color: null });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
  });

  it('surfaces 409 tag_name_conflict as ApiError', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json(
          { error_code: 'tag_name_conflict', message: 'dup' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({ name: 'Vocal', color: null }),
    ).rejects.toMatchObject({ status: 409, code: 'tag_name_conflict' });
  });
});

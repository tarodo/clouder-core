import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCreateCategory } from '../useCreateCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCreateCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('posts and invalidates byStyle', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: [], total: 0, limit: 200, offset: 0 });
    server.use(
      http.post('http://localhost/styles/s1/categories', async () =>
        HttpResponse.json(
          {
            id: 'c1',
            style_id: 's1',
            style_name: 'House',
            name: 'Deep',
            position: 0,
            track_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    );
    const { result } = renderHook(() => useCreateCategory('s1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'Deep' });
    });
    expect(result.current.data?.name).toBe('Deep');
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });

  it('surfaces 409 error', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    server.use(
      http.post('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          { error_code: 'name_conflict', message: 'duplicate', correlation_id: 'c' },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useCreateCategory('s1'), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ name: 'Deep' });
      }),
    ).rejects.toThrow();
    expect(result.current.error).toBeDefined();
  });
});

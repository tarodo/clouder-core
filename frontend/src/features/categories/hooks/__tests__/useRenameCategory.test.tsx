import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRenameCategory } from '../useRenameCategory';

const baseCategory = {
  id: 'c1',
  style_id: 's1',
  style_name: 'House',
  name: 'Old',
  position: 0,
  track_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useRenameCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('patches caches optimistically and confirms on 200', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], {
      items: [baseCategory],
      total: 1,
      limit: 200,
      offset: 0,
    });
    qc.setQueryData(['categories', 'detail', 'c1'], baseCategory);
    server.use(
      http.patch('http://localhost/categories/c1', () =>
        HttpResponse.json({ ...baseCategory, name: 'New' }),
      ),
    );
    const { result } = renderHook(() => useRenameCategory('c1', 's1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'New' });
    });
    const list = qc.getQueryData<{ items: typeof baseCategory[] }>(['categories', 'byStyle', 's1']);
    expect(list?.items[0]?.name).toBe('New');
  });

  it('rolls back on 409', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], {
      items: [baseCategory],
      total: 1,
      limit: 200,
      offset: 0,
    });
    server.use(
      http.patch('http://localhost/categories/c1', () =>
        HttpResponse.json(
          { error_code: 'name_conflict', message: 'dup', correlation_id: 'c' },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useRenameCategory('c1', 's1'), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ name: 'New' });
      }),
    ).rejects.toThrow();
    const list = qc.getQueryData<{ items: typeof baseCategory[] }>(['categories', 'byStyle', 's1']);
    expect(list?.items[0]?.name).toBe('Old');
  });
});

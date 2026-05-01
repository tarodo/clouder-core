import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useDeleteCategory } from '../useDeleteCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useDeleteCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('deletes and invalidates byStyle', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: [], total: 0, limit: 200, offset: 0 });
    server.use(
      http.delete('http://localhost/categories/c1', () => new HttpResponse(null, { status: 204 })),
    );
    const { result } = renderHook(() => useDeleteCategory('s1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync('c1');
    });
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });
});

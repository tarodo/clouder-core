import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useReorderCategories } from '../useReorderCategories';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const cats = [
  { id: 'c1', position: 0 },
  { id: 'c2', position: 1 },
  { id: 'c3', position: 2 },
];

describe('useReorderCategories', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    vi.useFakeTimers();
  });

  it('coalesces multiple swaps into one PUT', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let putCount = 0;
    let lastBody: { category_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/styles/s1/categories/order', async ({ request }) => {
        putCount += 1;
        lastBody = (await request.json()) as { category_ids: string[] };
        return HttpResponse.json({ items: cats });
      }),
    );
    const { result } = renderHook(() => useReorderCategories('s1'), { wrapper: wrap(qc) });

    act(() => result.current.queueOrder(['c2', 'c1', 'c3']));
    act(() => result.current.queueOrder(['c2', 'c3', 'c1']));
    act(() => result.current.queueOrder(['c3', 'c2', 'c1']));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(putCount).toBe(1);
    const body = lastBody as { category_ids: string[] } | null;
    expect(body?.category_ids).toEqual(['c3', 'c2', 'c1']);
  });

  it('invalidates on 422 order_mismatch', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: cats, total: 3, limit: 200, offset: 0 });
    server.use(
      http.put('http://localhost/styles/s1/categories/order', () =>
        HttpResponse.json(
          { error_code: 'order_mismatch', message: 'race', correlation_id: 'c' },
          { status: 422 },
        ),
      ),
    );
    const { result } = renderHook(() => useReorderCategories('s1'), { wrapper: wrap(qc) });
    act(() => result.current.queueOrder(['c2', 'c1', 'c3']));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });
});

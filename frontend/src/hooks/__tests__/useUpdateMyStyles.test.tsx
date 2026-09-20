import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { useUpdateMyStyles } from '../useUpdateMyStyles';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useUpdateMyStyles', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    vi.useFakeTimers();
  });

  it('coalesces rapid changes into one PUT with the last order', async () => {
    let putCount = 0;
    let lastBody: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        putCount += 1;
        lastBody = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUpdateMyStyles(), { wrapper: wrap(qc) });

    act(() => result.current.queueSelection(['s1']));
    act(() => result.current.queueSelection(['s1', 's2']));
    act(() => result.current.queueSelection(['s2', 's1']));

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });

    expect(putCount).toBe(1);
    expect(lastBody).toEqual({ style_ids: ['s2', 's1'] });
  });

  it('invalidates both style caches after a successful PUT', async () => {
    server.use(
      http.put('http://localhost/me/styles', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateMyStyles(), { wrapper: wrap(qc) });

    act(() => result.current.queueSelection(['s1']));
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });

    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys.some((k) => k?.includes('"styles"'))).toBe(true);
    expect(keys.some((k) => k?.includes('"all"'))).toBe(true);
  });
});

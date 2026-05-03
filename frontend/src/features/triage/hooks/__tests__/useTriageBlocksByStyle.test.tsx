import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import {
  useTriageBlocksByStyle,
  triageBlocksByStyleKey,
} from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
  ...overrides,
});

describe('useTriageBlocksByStyle', () => {
  it('builds a stable query key including style and status', () => {
    expect(triageBlocksByStyleKey('s1', 'IN_PROGRESS')).toEqual([
      'triage',
      'byStyle',
      's1',
      'IN_PROGRESS',
    ]);
    expect(triageBlocksByStyleKey('s1', undefined)).toEqual([
      'triage',
      'byStyle',
      's1',
      'all',
    ]);
  });

  it('fetches the first page with status filter', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get('status')).toBe('IN_PROGRESS');
        expect(url.searchParams.get('limit')).toBe('50');
        expect(url.searchParams.get('offset')).toBe('0');
        return HttpResponse.json({
          items: [sampleBlock()],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
    );

    const { result } = renderHook(
      () => useTriageBlocksByStyle('s1', 'IN_PROGRESS'),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0]?.items).toHaveLength(1);
  });

  it('omits status param when undefined (All tab)', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.has('status')).toBe(false);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
        });
      }),
    );

    const { result } = renderHook(() => useTriageBlocksByStyle('s1', undefined), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('paginates with getNextPageParam', async () => {
    let call = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset'));
        call++;
        if (offset === 0) {
          return HttpResponse.json({
            items: Array.from({ length: 50 }, (_, i) =>
              sampleBlock({ id: `a${i}` }),
            ),
            total: 60,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({
          items: Array.from({ length: 10 }, (_, i) =>
            sampleBlock({ id: `b${i}` }),
          ),
          total: 60,
          limit: 50,
          offset: 50,
        });
      }),
    );

    const { result } = renderHook(
      () => useTriageBlocksByStyle('s1', 'IN_PROGRESS'),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(result.current.data?.pages).toHaveLength(2);
    expect(result.current.hasNextPage).toBe(false);
    expect(call).toBe(2);
  });
});

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { useStyles } from '../useStyles';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useStyles', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('returns paginated items', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useStyles(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.items[0]?.name).toBe('House');
  });

  it('hits limit=200', async () => {
    let called = '';
    server.use(
      http.get('http://localhost/styles', ({ request }) => {
        called = new URL(request.url).search;
        return HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 });
      }),
    );
    const { result } = renderHook(() => useStyles(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(called).toContain('limit=200');
  });
});

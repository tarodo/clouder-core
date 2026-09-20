import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { useAllStyles } from '../useAllStyles';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useAllStyles', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('requests scope=all and exposes selection flags', async () => {
    let seenUrl = '';
    server.use(
      http.get('http://localhost/styles', ({ request }) => {
        seenUrl = request.url;
        return HttpResponse.json({
          items: [
            { id: 's1', name: 'DnB', selected: true, position: 0 },
            { id: 's2', name: 'House', selected: false, position: null },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAllStyles(), { wrapper: wrap(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seenUrl).toContain('scope=all');
    expect(seenUrl).toContain('limit=200');
    expect(result.current.data?.items[1]?.position).toBeNull();
  });
});

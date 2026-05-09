import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { homeActiveBlocksQueryOptions, homeActiveBlocksKey } from '../homeActiveBlocksQueryOptions';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('homeActiveBlocksQueryOptions', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('builds a query that fetches IN_PROGRESS blocks for a style', async () => {
    let capturedUrl = '';
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          items: [
            {
              id: 'b1',
              style_id: 's1',
              style_name: 'House',
              name: '2026-W18',
              date_from: '2026-05-04',
              date_to: '2026-05-10',
              status: 'IN_PROGRESS',
              created_at: '2026-05-04T00:00:00Z',
              updated_at: '2026-05-05T00:00:00Z',
              finalized_at: null,
              track_count: 42,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
    );
    const { result } = renderHook(() => useQuery(homeActiveBlocksQueryOptions('s1')), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain('status=IN_PROGRESS');
    expect(capturedUrl).toContain('limit=50');
    expect(result.current.data?.[0]?.id).toBe('b1');
  });

  it('exposes a stable cache key', () => {
    expect(homeActiveBlocksKey('s1')).toEqual(['home', 'activeBlocks', 's1']);
  });

  it('disables itself when styleId is empty', () => {
    const { result } = renderHook(() => useQuery(homeActiveBlocksQueryOptions('')), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });
});

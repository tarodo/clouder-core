import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelsList } from '../useLabelsList';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useLabelsList', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches the first page with style + q + sort params', async () => {
    let received = '';
    server.use(
      http.get('http://localhost/labels', ({ request }) => {
        received = request.url;
        return HttpResponse.json({
          items: [{ id: 'l1', name: 'A', style: 'dnb', status: 'completed', info: null }],
          next_cursor: 'cur2',
        });
      }),
    );
    const { result } = renderHook(
      () => useLabelsList({ styleId: 'dnb', q: 'foo', sort: 'recent' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toContain('style=dnb');
    expect(received).toContain('q=foo');
    expect(received).toContain('sort=recent');
  });

  it('paginates via next_cursor', async () => {
    server.use(
      http.get('http://localhost/labels', ({ request }) => {
        const url = new URL(request.url);
        const cursor = url.searchParams.get('cursor');
        return HttpResponse.json({
          items: [{ id: cursor ?? 'first', name: 'X', style: 'dnb', status: 'none', info: null }],
          next_cursor: cursor ? null : 'cur2',
        });
      }),
    );
    const { result } = renderHook(
      () => useLabelsList({ styleId: 'dnb', q: '', sort: 'name' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await result.current.fetchNextPage();
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(result.current.data?.pages[1]?.items[0]?.id).toBe('cur2');
  });
});

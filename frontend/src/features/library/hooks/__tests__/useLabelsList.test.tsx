import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
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

  it('forwards next_cursor as cursor query param on fetchNextPage', async () => {
    const received: string[] = [];
    server.use(
      http.get('http://localhost/labels', ({ request }) => {
        received.push(request.url);
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
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(received).toHaveLength(2));
    expect(received[1]).toContain('cursor=cur2');
  });
});

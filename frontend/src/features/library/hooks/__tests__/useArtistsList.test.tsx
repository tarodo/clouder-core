import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useArtistsList } from '../useArtistsList';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useArtistsList', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches with style, q, sort, page and limit query params', async () => {
    let received = '';
    server.use(
      http.get('http://localhost/artists', ({ request }) => {
        received = request.url;
        return HttpResponse.json({
          items: [{ id: 'a1', name: 'Noisia', style: 'dnb', status: 'completed', info: null }],
          total: 1,
          page: 1,
          limit: 25,
        });
      }),
    );
    const { result } = renderHook(
      () => useArtistsList({ styleId: 'dnb', q: 'foo', sort: 'recent', page: 1, limit: 25, my: 'all' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toContain('style=dnb');
    expect(received).toContain('q=foo');
    expect(received).toContain('sort=recent');
    expect(received).toContain('page=1');
    expect(received).toContain('limit=25');
  });

  it('omits my param when my is "all"', async () => {
    let received = '';
    server.use(
      http.get('http://localhost/artists', ({ request }) => {
        received = request.url;
        return HttpResponse.json({ items: [], total: 0, page: 1, limit: 25 });
      }),
    );
    const { result } = renderHook(
      () => useArtistsList({ styleId: 'dnb', q: '', sort: 'name', page: 1, limit: 25, my: 'all' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).not.toContain('my=');
  });

  it('includes my param when my is not "all"', async () => {
    let received = '';
    server.use(
      http.get('http://localhost/artists', ({ request }) => {
        received = request.url;
        return HttpResponse.json({ items: [], total: 0, page: 1, limit: 25 });
      }),
    );
    const { result } = renderHook(
      () => useArtistsList({ styleId: 'dnb', q: '', sort: 'name', page: 1, limit: 25, my: 'liked' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toContain('my=liked');
  });

  it('refetches when page changes', async () => {
    const received: string[] = [];
    server.use(
      http.get('http://localhost/artists', ({ request }) => {
        received.push(request.url);
        return HttpResponse.json({
          items: [],
          total: 50,
          page: Number(new URL(request.url).searchParams.get('page')),
          limit: 25,
        });
      }),
    );
    const { result, rerender } = renderHook(
      ({ page }: { page: number }) =>
        useArtistsList({ styleId: 'dnb', q: '', sort: 'name', page, limit: 25, my: 'all' }),
      { wrapper: wrap(), initialProps: { page: 1 } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender({ page: 2 });
    await waitFor(() => expect(received).toHaveLength(2));
    expect(received[1]).toContain('page=2');
  });
});

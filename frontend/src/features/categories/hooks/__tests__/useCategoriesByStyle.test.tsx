import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoriesByStyle } from '../useCategoriesByStyle';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCategoriesByStyle', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches categories for a style', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({
          items: [
            {
              id: 'c1',
              style_id: 's1',
              style_name: 'House',
              name: 'Deep',
              position: 0,
              track_count: 12,
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useCategoriesByStyle('s1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items[0].name).toBe('Deep');
    expect(result.current.data?.items[0].track_count).toBe(12);
  });

  it('does not fetch when styleId is empty', () => {
    const { result } = renderHook(() => useCategoriesByStyle(''), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });
});

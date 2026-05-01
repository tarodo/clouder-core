import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoryDetail } from '../useCategoryDetail';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCategoryDetail', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches a single category', async () => {
    server.use(
      http.get('http://localhost/categories/c1', () =>
        HttpResponse.json({
          id: 'c1',
          style_id: 's1',
          style_name: 'House',
          name: 'Deep',
          position: 0,
          track_count: 5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    );
    const { result } = renderHook(() => useCategoryDetail('c1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe('Deep');
  });
});

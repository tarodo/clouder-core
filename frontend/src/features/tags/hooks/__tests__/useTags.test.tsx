import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTags, tagsKey } from '../useTags';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useTags', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('GETs /tags and returns items array', async () => {
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: '2026-05-11T12:00:00Z',
              updated_at: '2026-05-11T12:00:00Z' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: '2026-05-11T12:00:00Z',
              updated_at: '2026-05-11T12:00:00Z' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useTags(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((t) => t.id)).toEqual(['tg1', 'tg2']);
    expect(result.current.data?.[1].color).toBeNull();
  });

  it('uses the stable cache key', () => {
    expect(tagsKey()).toEqual(['tags']);
  });
});

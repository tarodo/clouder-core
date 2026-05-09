import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useHomeData } from '../useHomeData';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function block(id: string, styleId: string, styleName: string, updatedAt: string, trackCount: number) {
  return {
    id,
    style_id: styleId,
    style_name: styleName,
    name: `${id}-name`,
    date_from: '2026-05-04',
    date_to: '2026-05-10',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-05-04T00:00:00Z',
    updated_at: updatedAt,
    finalized_at: null,
    track_count: trackCount,
  };
}

beforeEach(() => {
  tokenStore.set('TOK');
});

describe('useHomeData', () => {
  it('aggregates IN_PROGRESS blocks across styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({
          items: [
            block('b2', 's2', 'Techno', '2026-05-09T00:00:00Z', 50),
            block('b3', 's2', 'Techno', '2026-05-07T00:00:00Z', 12),
          ],
          total: 2, limit: 50, offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.activeBlocksCount).toBe(3);
    expect(result.current.data?.awaitingTriageCount).toBe(92);
    expect(result.current.data?.topActiveBlocks.map((b) => b.id)).toEqual(['b2', 'b1', 'b3']);
    expect(result.current.data?.partialError).toBe(false);
  });

  it('flags partialError when one style query fails', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({ error_code: 'server', message: 'boom', correlation_id: 'x' }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.partialError).toBe(true);
    expect(result.current.data?.activeBlocksCount).toBe(1);
  });

  it('returns empty aggregates when there are no styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.activeBlocksCount).toBe(0);
    expect(result.current.data?.styles).toEqual([]);
  });
});

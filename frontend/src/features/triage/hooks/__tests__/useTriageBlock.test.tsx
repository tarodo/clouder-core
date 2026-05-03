import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTriageBlock } from '../useTriageBlock';

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const blockFixture = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House — week 17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
    { id: 'bk2', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 2 },
  ],
};

describe('useTriageBlock', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches a block by id', async () => {
    server.use(http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(blockFixture)));
    const { result } = renderHook(() => useTriageBlock('b1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe('House — week 17');
    expect(result.current.data?.buckets).toHaveLength(2);
  });

  it('throws on 404', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/missing', () =>
        HttpResponse.json({ error_code: 'triage_block_not_found', message: 'no' }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useTriageBlock('missing'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

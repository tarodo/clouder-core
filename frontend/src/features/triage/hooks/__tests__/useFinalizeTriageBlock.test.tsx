import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import {
  useFinalizeTriageBlock,
  type FinalizeResponse,
} from '../useFinalizeTriageBlock';
import { triageBlockKey, type TriageBlock } from '../useTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';
import { categoriesByStyleKey } from '../../../categories/hooks/useCategoriesByStyle';
import { categoryDetailKey } from '../../../categories/hooks/useCategoryDetail';
import { ApiError } from '../../../../api/error';

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const FINALIZED_BLOCK: TriageBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'Style One',
  name: 'Block 1',
  date_from: '2026-01-01',
  date_to: '2026-01-07',
  status: 'FINALIZED',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-08T00:00:00Z',
  finalized_at: '2026-01-08T00:00:00Z',
  buckets: [],
};

const SUCCESS: FinalizeResponse = {
  block: FINALIZED_BLOCK,
  promoted: { catA: 3, catB: 5 },
  correlation_id: 'cid-1',
};

afterEach(() => server.resetHandlers());

describe('useFinalizeTriageBlock', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('invalidates triage + categories caches on success', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json(SUCCESS, { status: 200 }),
      ),
    );
    const qc = makeClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), {
      wrapper: wrap(qc),
    });

    await act(async () => {
      await result.current.mutateAsync();
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calls = spy.mock.calls.map((c) => c[0]);
    const queryKeys = calls.map((c) => (c as { queryKey?: unknown }).queryKey);

    expect(queryKeys).toContainEqual(triageBlockKey('b1'));
    expect(queryKeys).toContainEqual(triageBlocksByStyleKey('s1', 'IN_PROGRESS'));
    expect(queryKeys).toContainEqual(triageBlocksByStyleKey('s1', 'FINALIZED'));
    expect(queryKeys).toContainEqual(triageBlocksByStyleKey('s1', undefined));
    expect(queryKeys).toContainEqual(categoriesByStyleKey('s1'));
    expect(queryKeys).toContainEqual(categoryDetailKey('catA'));
    expect(queryKeys).toContainEqual(categoryDetailKey('catB'));

    const predicateCalls = calls.filter(
      (c) => typeof (c as { predicate?: unknown }).predicate === 'function',
    );
    expect(predicateCalls.length).toBeGreaterThanOrEqual(2);

    // Sanity check: each predicate matches its target categoryTracks key.
    const matched = predicateCalls.map((c) => {
      const pred = (c as { predicate: (q: { queryKey: readonly unknown[] }) => boolean })
        .predicate;
      return {
        catA: pred({ queryKey: ['categories', 'tracks', 'catA', ''] }),
        catB: pred({ queryKey: ['categories', 'tracks', 'catB', ''] }),
        other: pred({ queryKey: ['categories', 'tracks', 'catZ', ''] }),
      };
    });
    expect(matched.some((m) => m.catA && !m.other)).toBe(true);
    expect(matched.some((m) => m.catB && !m.other)).toBe(true);
  });

  it('rejects with ApiError on 503 cold start', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), {
      wrapper: wrap(qc),
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync();
      } catch (e) {
        caught = e;
      }
    });
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
  });

  it('rejects with ApiError carrying inactive_buckets in raw on 409', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            error_code: 'inactive_buckets_have_tracks',
            message: '1 inactive staging bucket holds tracks',
            inactive_buckets: [
              { id: 'bk1', category_id: 'catX', track_count: 5 },
            ],
          },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), {
      wrapper: wrap(qc),
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync();
      } catch (e) {
        caught = e;
      }
    });
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught).toMatchObject({ code: 'inactive_buckets_have_tracks', status: 409 });
    const raw = (caught as ApiError).raw as {
      inactive_buckets: { id: string; category_id: string; track_count: number }[];
    };
    expect(raw.inactive_buckets).toHaveLength(1);
    expect(raw.inactive_buckets[0]).toMatchObject({ id: 'bk1', track_count: 5 });
  });
});

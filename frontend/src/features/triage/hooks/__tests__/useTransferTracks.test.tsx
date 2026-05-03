import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTransferTracks } from '../useTransferTracks';
import { triageBlockKey } from '../useTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useTransferTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs target_bucket_id + track_ids to /transfer and returns transferred count', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    expect(bodySeen).toEqual({ target_bucket_id: 'bk1', track_ids: ['t1'] });
    expect(result.current.data).toEqual({ transferred: 1 });
  });

  it('invalidates target bucketTracks, target blockDetail, and byStyle on success', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json({ transferred: 1 }),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    const calls = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(calls).toContainEqual(['triage', 'bucketTracks', 'tgt1', 'bk1']);
    expect(calls).toContainEqual(triageBlockKey('tgt1'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', 'IN_PROGRESS'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', 'FINALIZED'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', undefined));
  });

  it('does not invalidate source caches on success (snapshot semantics)', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json({ transferred: 1 }),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    const calls = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(calls).not.toContainEqual(triageBlockKey('src1'));
    expect(calls.find((k) => Array.isArray(k) && k[0] === 'triage' && k[1] === 'bucketTracks' && k[2] === 'src1')).toBeUndefined();
  });

  it('rejects with ApiError on 409 and does not invalidate target caches', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({
          targetBlockId: 'tgt1',
          targetBucketId: 'bk1',
          trackIds: ['t1'],
          styleId: 'st1',
        })
        .catch(() => {});
    });

    expect(result.current.isError).toBe(true);
    expect(invalidate).not.toHaveBeenCalled();
  });
});

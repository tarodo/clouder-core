import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useMoveTracks, undoMoveDirect, takeSnapshot } from '../useMoveTracks';
import { triageBlockKey } from '../useTriageBlock';
import { bucketTracksKey } from '../useBucketTracks';

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

function block(buckets: { id: string; track_count: number }[]) {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'House',
    name: 'W17',
    date_from: '2026-04-21',
    date_to: '2026-04-28',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z',
    finalized_at: null,
    buckets: buckets.map((b) => ({
      id: b.id,
      bucket_type: 'NEW' as const,
      category_id: null,
      category_name: null,
      inactive: false,
      track_count: b.track_count,
    })),
  };
}

function tracksPage(ids: string[], total: number) {
  return {
    pageParams: [0],
    pages: [
      {
        items: ids.map((id) => ({
          track_id: id,
          title: `t${id}`,
          mix_name: null,
          isrc: null,
          bpm: null,
          length_ms: null,
          publish_date: null,
          spotify_release_date: null,
          spotify_id: null,
          release_type: null,
          is_ai_suspected: false,
          artists: [],
          added_at: '2026-04-21T00:00:00Z',
        })),
        total,
        limit: 50,
        offset: 0,
      },
    ],
  };
}

describe('useMoveTracks — optimistic write', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('removes the track from source list and adjusts counters on success', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ moved: 1 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        fromBucketId: 'src',
        toBucketId: 'dst',
        trackIds: ['t1'],
      });
    });

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0]?.items.map((t) => t.track_id)).toEqual(['t2']);
    expect(after?.pages[0]?.total).toBe(1);
  });

  it('rolls back on 409 target_bucket_inactive', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({ fromBucketId: 'src', toBucketId: 'dst', trackIds: ['t1'] })
        .catch(() => {});
    });

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0]?.items.map((t) => t.track_id)).toEqual(['t1', 't2']);
    expect(after?.pages[0]?.total).toBe(2);
  });

  it('rolls back on 404 stale-state', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'no' },
          { status: 404 },
        ),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({ fromBucketId: 'src', toBucketId: 'dst', trackIds: ['t1'] })
        .catch(() => {});
    });

    const blockAfter = qc.getQueryData<ReturnType<typeof block>>(triageBlockKey('b1'));
    expect(blockAfter?.buckets.find((b) => b.id === 'src')?.track_count).toBe(2);
    expect(blockAfter?.buckets.find((b) => b.id === 'dst')?.track_count).toBe(0);
  });
});

describe('undoMoveDirect', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('restores snapshot and fires inverse call', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ moved: 1 });
      }),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const snap = takeSnapshot(qc, 'b1', 'src');
    // Simulate: optimistic move already applied
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t2'], 1));

    await undoMoveDirect(qc, 'b1', 's1', {
      fromBucketId: 'src',
      toBucketId: 'dst',
      trackIds: ['t1'],
    }, snap);

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0]?.items.map((t) => t.track_id)).toEqual(['t1', 't2']);
    expect(bodySeen).toMatchObject({
      from_bucket_id: 'dst',
      to_bucket_id: 'src',
      track_ids: ['t1'],
    });
  });

  it('re-applies optimistic write if inverse call fails', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ error_code: 'unknown', message: 'no' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const snap = takeSnapshot(qc, 'b1', 'src');
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t2'], 1));

    await expect(
      undoMoveDirect(qc, 'b1', 's1', {
        fromBucketId: 'src',
        toBucketId: 'dst',
        trackIds: ['t1'],
      }, snap),
    ).rejects.toBeTruthy();

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0]?.items.map((t) => t.track_id)).toEqual(['t2']);
  });
});

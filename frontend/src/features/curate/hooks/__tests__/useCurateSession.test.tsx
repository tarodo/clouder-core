import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { useCurateSession } from '../useCurateSession';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../lib/lastCurateLocation';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const block = {
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
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'dst2', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c2', category_name: 'Hard Techno' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 0 },
  ],
};

function tracksPage(ids: string[]) {
  return {
    items: ids.map((id) => ({
      track_id: id,
      title: `Track ${id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360000,
      publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15',
      spotify_id: `sp-${id}`,
      release_type: 'single',
      is_ai_suspected: false,
      artists: ['Artist A'],
      label_name: 'Label X',
      added_at: '2026-04-21T00:00:00Z',
    })),
    total: ids.length,
    limit: 50,
    offset: 0,
  };
}

function defaultHandlers() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracksPage(['t1', 't2', 't3'])),
    ),
    http.post('http://localhost/triage/blocks/b1/move', () =>
      HttpResponse.json({ moved: 1, correlation_id: 'cid-x' }),
    ),
  ];
}

describe('useCurateSession — initial state', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
  });
  afterEach(() => localStorage.clear());

  it('starts in loading then becomes active with the first track', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );

    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('active'));
    expect(result.current.queue).toHaveLength(3);
    expect(result.current.currentTrack?.track_id).toBe('t1');
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.totalAssigned).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.lastTappedBucketId).toBeNull();
    expect(result.current.destinations.map((d) => d.id)).toEqual(['dst1', 'dst2', 'b-old']);
  });

  it('becomes empty when the source bucket has zero tracks', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('empty'));
    expect(result.current.currentTrack).toBeNull();
  });
});

describe('useCurateSession — assign + advance', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('schedules advance 200ms after assign and writes localStorage on success', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => {
      result.current.assign('dst1');
    });
    expect(result.current.lastTappedBucketId).toBe('dst1');
    expect(result.current.canUndo).toBe(true);
    expect(result.current.totalAssigned).toBe(1);
    // pulse has not yet cleared; advance has not yet fired
    expect(result.current.currentIndex).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });
    expect(result.current.lastTappedBucketId).toBeNull();
    expect(result.current.currentIndex).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120); // 80 + 120 = 200ms total
    });
    await waitFor(() => expect(result.current.currentIndex).toBe(1));

    // localStorage updated by onSuccess
    await waitFor(() => {
      expect(localStorage.getItem(LAST_CURATE_STYLE_KEY)).toBe('s1');
      const stored = JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}');
      expect(stored.s1).toMatchObject({ blockId: 'b1', bucketId: 'src' });
    });
  });

  it('double-tap with different destination — first reverted, second applied, single advance', async () => {
    let firstSeen = false;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () => {
        firstSeen = true;
        return HttpResponse.json({ moved: 1, correlation_id: 'cid' });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => result.current.assign('dst1'));
    expect(result.current.totalAssigned).toBe(1);
    act(() => result.current.assign('dst2'));
    expect(result.current.lastTappedBucketId).toBe('dst2');
    // totalAssigned stays at 1 — replace doesn't double-count
    expect(result.current.totalAssigned).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(result.current.currentIndex).toBe(1);
    expect(firstSeen).toBe(true);
  });

  it('double-tap with same destination — no rollback, single advance, timer reset', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150); // not yet at 200
    });
    expect(result.current.currentIndex).toBe(0);

    act(() => result.current.assign('dst1'));
    // Timer reset — wait another 199ms, still no advance
    await act(async () => {
      await vi.advanceTimersByTimeAsync(199);
    });
    expect(result.current.currentIndex).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2);
    });
    expect(result.current.currentIndex).toBe(1);
    expect(result.current.totalAssigned).toBe(1);
  });

  it('rejects assign to the source bucket itself (no-op)', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('src'));
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });
});

describe('useCurateSession — undo + skip + prev', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('undo within window cancels the advance and restores state', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    act(() => result.current.undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('undo after advance restores index to the just-undone track', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(result.current.currentIndex).toBe(1);
    act(() => result.current.undo());
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('undo with no lastOp is a no-op', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.undo());
    expect(result.current.currentIndex).toBe(0);
  });

  it('skip advances index without assigning', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.skip());
    expect(result.current.currentIndex).toBe(1);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('prev decrements index but never below 0', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.skip());
    expect(result.current.currentIndex).toBe(1);
    act(() => result.current.prev());
    act(() => result.current.prev());
    expect(result.current.currentIndex).toBe(0);
  });
});

describe('useCurateSession — error path', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json(tracksPage(['t1', 't2'])),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'race', correlation_id: 'x' },
          { status: 422 },
        ),
      ),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('on 422 tracks_not_in_source: clears lastOp and pending timer', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    // Mutation onError fires; reducer should clean up
    await waitFor(() => expect(result.current.canUndo).toBe(false));
    expect(result.current.totalAssigned).toBe(0);
  });
});

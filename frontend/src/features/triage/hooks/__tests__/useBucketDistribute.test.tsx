import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PlaybackTrack } from '../../../playback/lib/types';
import type { TriageBucket } from '../../lib/bucketLabels';

const moveMutate = vi.fn();
const playSpy = vi.fn();
let current: PlaybackTrack | null = null;
let queueTracks: PlaybackTrack[] = [];

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    track: { current, positionMs: 0, durationMs: 0 },
    queue: { source: null, tracks: queueTracks, cursor: 0, status: 'playing' },
    controls: { play: playSpy },
  }),
}));

vi.mock('../useMoveTracks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../useMoveTracks')>();
  return {
    ...actual,
    useMoveTracks: () => ({ mutate: moveMutate, isPending: false }),
  };
});

import { useBucketDistribute } from '../useBucketDistribute';

const T = (id: string): PlaybackTrack => ({
  id, title: id, artists: '', cover_url: null, duration_ms: 0, spotify_id: `sp-${id}`,
});

const buckets: TriageBucket[] = [
  { id: 'bk1', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Cur', inactive: false, track_count: 1 },
  { id: 'dst', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Dst', inactive: false, track_count: 0 },
];

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderDistribute() {
  const { result } = renderHook(
    () => useBucketDistribute({ blockId: 'b1', bucketId: 'bk1', styleId: 's1', buckets }),
    { wrapper },
  );
  return result;
}

beforeEach(() => {
  moveMutate.mockReset();
  playSpy.mockReset();
  current = null;
  queueTracks = [];
});

describe('useBucketDistribute', () => {
  it('moves the current track and plays the successor', () => {
    current = T('t1');
    queueTracks = [T('t1'), T('t2'), T('t3')];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).toHaveBeenCalledTimes(1);
    expect(moveMutate.mock.calls[0]![0]).toEqual({
      fromBucketId: 'bk1', toBucketId: 'dst', trackIds: ['t1'],
    });
    expect(playSpy).toHaveBeenCalledWith(undefined, queueTracks[1]);
  });

  it('is a no-op when nothing is playing', () => {
    current = null;
    queueTracks = [];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).not.toHaveBeenCalled();
    expect(playSpy).not.toHaveBeenCalled();
  });

  it('moves but does not advance when the current track is last', () => {
    current = T('t3');
    queueTracks = [T('t1'), T('t2'), T('t3')];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).toHaveBeenCalledTimes(1);
    expect(playSpy).not.toHaveBeenCalled();
  });
});

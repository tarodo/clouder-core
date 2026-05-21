import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useBucketPlayerQueue } from '../useBucketPlayerQueue';
import type { PlaybackTrack } from '../../../playback/lib/types';

const bindQueue = vi.fn();
const clearQueue = vi.fn();
const playback = {
  controls: { bindQueue, clearQueue },
  queue: { source: null, tracks: [] as PlaybackTrack[], cursor: 0, status: 'idle' as const },
  track: { current: null as PlaybackTrack | null, positionMs: 0, durationMs: 0 },
  sdk: { ready: false, error: null },
  devices: undefined as never,
};

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => playback,
}));

const T = (id: string): PlaybackTrack => ({
  id,
  title: `t-${id}`,
  artists: '',
  duration_ms: 200000,
  spotify_id: `sp-${id}`,
  cover_url: null,
});

beforeEach(() => {
  bindQueue.mockReset();
  clearQueue.mockReset();
  playback.queue.tracks = [];
  playback.queue.cursor = 0;
  playback.track.current = null;
});

describe('useBucketPlayerQueue', () => {
  it('binds queue on mount with a bucket source and cursor 0 when nothing playing', () => {
    const tracks = [T('a'), T('b'), T('c')];
    renderHook(() => useBucketPlayerQueue('blk-1', 'bk-1', tracks));
    expect(bindQueue).toHaveBeenCalledWith({
      source: { type: 'bucket', blockId: 'blk-1', bucketId: 'bk-1' },
      tracks,
      cursor: 0,
      onCursorChange: expect.any(Function),
    });
  });

  it('preserves the playing track id when the list identity changes', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    const next = [T('a'), T('b'), T('c'), T('d')];
    rerender({ tracks: next });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ tracks: next, cursor: 1 }),
    );
  });

  it('cursor = -1 when the top track is removed (advance lands on new tracks[0])', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 0;
    playback.track.current = T('a');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('b'), T('c')] });
    expect(bindQueue).toHaveBeenCalledWith(expect.objectContaining({ cursor: -1 }));
  });

  it('calls clearQueue on unmount', () => {
    const { unmount } = renderHook(() =>
      useBucketPlayerQueue('blk-1', 'bk-1', [T('a')]),
    );
    unmount();
    expect(clearQueue).toHaveBeenCalledOnce();
  });

  it('cursor = lastCursor - 1 when the tail track is removed', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 2;
    playback.track.current = T('c');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('a'), T('b')] });
    expect(bindQueue).toHaveBeenCalledWith(expect.objectContaining({ cursor: 1 }));
  });

  it('cursor = lastCursor - 1 when a middle track is removed (advance lands on successor)', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c'), T('d')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('a'), T('c'), T('d')] });
    expect(bindQueue).toHaveBeenCalledWith(expect.objectContaining({ cursor: 0 }));
  });
});

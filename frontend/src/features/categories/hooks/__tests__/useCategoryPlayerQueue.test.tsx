import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useCategoryPlayerQueue } from '../useCategoryPlayerQueue';
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

describe('useCategoryPlayerQueue', () => {
  it('binds queue on mount with cursor 0 when no track playing', () => {
    const tracks = [T('a'), T('b'), T('c')];
    renderHook(() => useCategoryPlayerQueue('cat-1', 'style-1', tracks));
    expect(bindQueue).toHaveBeenCalledWith({
      source: { type: 'category', categoryId: 'cat-1', styleId: 'style-1' },
      tracks,
      cursor: 0,
      onCursorChange: expect.any(Function),
    });
  });

  it('rebinds when track list identity changes and preserves the playing track id', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    const next = [T('a'), T('b'), T('c'), T('d')];
    rerender({ tracks: next });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ tracks: next, cursor: 1 }),
    );
  });

  it('cursor = lastCursor - 1 when last track removed (advance(+1) → ended)', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 2;
    playback.track.current = T('c');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('a'), T('b')] });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 1 }),
    );
  });

  it('cursor = -1 when the FIRST (top) track is removed so advance(+1) lands on tracks[0]', () => {
    // Reproduction for the prod bug: track A plays at top of fresh-on list,
    // user assigns it to a playlist, optimistic shrink removes A from the
    // queue. Natural-end advance(+1) must play B (now at index 0), not C.
    // Old behaviour set cursor=0 (clamp), making advance(+1) skip to index 1
    // and play C. New behaviour sets cursor=-1, so advance(+1) → index 0 = B.
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 0;
    playback.track.current = T('a');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('b'), T('c')] });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: -1 }),
    );
  });

  it('cursor = lastCursor - 1 when a middle track is removed (advance(+1) → successor)', () => {
    // Track B at index 1 in [A, B, C, D]. User assigns B to playlist;
    // shrink → [A, C, D]. C is now at index 1, so cursor should be 0
    // (lastCursor 1 - 1) so advance(+1) lands on C.
    playback.queue.tracks = [T('a'), T('b'), T('c'), T('d')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useCategoryPlayerQueue('cat-1', 'style-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('a'), T('c'), T('d')] });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 0 }),
    );
  });

  it('calls clearQueue on unmount', () => {
    const { unmount } = renderHook(() =>
      useCategoryPlayerQueue('cat-1', 'style-1', [T('a')]),
    );
    unmount();
    expect(clearQueue).toHaveBeenCalledOnce();
  });
});

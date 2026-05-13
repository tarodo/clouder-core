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

  it('clamps cursor to len-1 when current track removed and list shorter', () => {
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

  it('calls clearQueue on unmount', () => {
    const { unmount } = renderHook(() =>
      useCategoryPlayerQueue('cat-1', 'style-1', [T('a')]),
    );
    unmount();
    expect(clearQueue).toHaveBeenCalledOnce();
  });
});

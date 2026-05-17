import { useEffect, useRef } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';

/**
 * Bind a category's track list to PlaybackProvider's singleton queue.
 *
 * On every tracks-identity change recompute the cursor: keep the currently
 * playing track id if it still exists in the new list, else clamp to the
 * tail. Unmount clears the queue (players own their routes).
 */
export function useCategoryPlayerQueue(
  categoryId: string,
  styleId: string,
  tracks: readonly PlaybackTrack[],
): void {
  const playback = usePlayback();
  const cursorRef = useRef(playback.queue.cursor);

  useEffect(() => {
    cursorRef.current = playback.queue.cursor;
  }, [playback.queue.cursor]);

  useEffect(() => {
    const currentId = playback.track.current?.id ?? null;
    let cursor = 0;
    if (currentId) {
      const idx = tracks.findIndex((t) => t.id === currentId);
      if (idx >= 0) {
        cursor = idx;
      } else {
        // Current track was shrunk out of the queue (e.g. assigned to a
        // playlist with fresh-on filter). Everything after the removed
        // track shifted down by 1, so the immediate successor now lives
        // at the OLD cursor index. Setting `cursor = cursorRef - 1` makes
        // the natural-end advance(+1) land on that successor instead of
        // skipping past it.
        cursor = Math.max(-1, cursorRef.current - 1);
      }
    }
    playback.controls.bindQueue({
      source: { type: 'category', categoryId, styleId },
      tracks,
      cursor,
      onCursorChange: (next) => {
        cursorRef.current = next;
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, categoryId, styleId]);

  useEffect(() => {
    return () => {
      playback.controls.clearQueue();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

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
      cursor = idx >= 0 ? idx : Math.min(cursorRef.current, Math.max(0, tracks.length - 1));
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

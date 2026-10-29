import type { PlaybackTrack } from '../../playback/lib/types';
import { useBoundQueue } from '../../playback/hooks/useBoundQueue';

/** Bind a category's track list to the player queue (see useBoundQueue). */
export function useCategoryPlayerQueue(
  categoryId: string,
  styleId: string,
  tracks: readonly PlaybackTrack[],
): void {
  useBoundQueue({ type: 'category', categoryId, styleId }, tracks);
}

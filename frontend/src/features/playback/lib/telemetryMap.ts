import { clampMs } from './seekHotkeys';
import type { PlaybackSource, QueueSource } from './types';

const SOURCE_BY_QUEUE: Record<QueueSource['type'], PlaybackSource> = {
  bucket: 'triage_player',
  category: 'category_player',
  playlist: 'playlist_player',
};

export function resolvePlaybackSource(
  explicit: PlaybackSource | undefined,
  queueSource: QueueSource | null,
): PlaybackSource {
  if (explicit) return explicit;
  return queueSource ? SOURCE_BY_QUEUE[queueSource.type] : 'triage_player';
}

export function seekEventProps(
  currentPositionMs: number,
  durationMs: number,
  targetMs: number,
): { from_position_ms: number; to_position_ms: number } {
  return {
    from_position_ms: currentPositionMs,
    to_position_ms: clampMs(targetMs, durationMs),
  };
}

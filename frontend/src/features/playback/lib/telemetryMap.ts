import { clampMs } from './seekHotkeys';
import type { PlaybackSource, QueueSource, QueueStatus } from './types';

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

const PLAYING: ReadonlySet<QueueStatus> = new Set(['playing', 'buffering']);
const STOPPED: ReadonlySet<QueueStatus> = new Set(['paused', 'error', 'disconnected']);

export type ListenEvent = 'playback_pause' | 'playback_resume' | 'playback_ended';

/**
 * The listen-time event a queue status change means, or null. Playing stops
 * (pause / error / lost device) = pause; starts again = resume; the queue runs
 * out = ended. A move through 'loading' to the next track emits nothing: its
 * playback_play already marks the boundary.
 */
export function statusTransitionEvent(prev: QueueStatus, next: QueueStatus): ListenEvent | null {
  if (prev === next) return null;
  if (next === 'ended') return PLAYING.has(prev) || STOPPED.has(prev) ? 'playback_ended' : null;
  if (PLAYING.has(prev) && STOPPED.has(next)) return 'playback_pause';
  if (STOPPED.has(prev) && PLAYING.has(next)) return 'playback_resume';
  return null;
}

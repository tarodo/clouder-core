import { describe, expect, it } from 'vitest';
import { resolvePlaybackSource, seekEventProps } from './telemetryMap';
import type { QueueSource } from './types';

describe('resolvePlaybackSource', () => {
  it('prefers the explicit source arg', () => {
    const q: QueueSource = { type: 'bucket', blockId: 'b', bucketId: 'k' };
    expect(resolvePlaybackSource('category_player', q)).toBe('category_player');
  });
  it('maps bucket→triage_player, category→category_player, playlist→playlist_player', () => {
    expect(resolvePlaybackSource(undefined, { type: 'bucket', blockId: 'b', bucketId: 'k' })).toBe(
      'triage_player',
    );
    expect(resolvePlaybackSource(undefined, { type: 'category', categoryId: 'c', styleId: 's' })).toBe(
      'category_player',
    );
    expect(resolvePlaybackSource(undefined, { type: 'playlist', playlistId: 'p' })).toBe(
      'playlist_player',
    );
  });
  it('falls back to triage_player when no queue source is bound', () => {
    expect(resolvePlaybackSource(undefined, null)).toBe('triage_player');
  });
});

describe('seekEventProps', () => {
  it('reads from_position from the current player position and clamps the target', () => {
    expect(seekEventProps(12_345, 200_000, 50_000)).toEqual({
      from_position_ms: 12_345,
      to_position_ms: 50_000,
    });
  });
  it('clamps to_position to [0, duration]', () => {
    expect(seekEventProps(0, 100_000, 999_999).to_position_ms).toBe(100_000);
    expect(seekEventProps(0, 100_000, -5).to_position_ms).toBe(0);
  });
});

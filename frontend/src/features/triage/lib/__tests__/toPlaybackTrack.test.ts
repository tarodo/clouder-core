import { describe, it, expect } from 'vitest';
import { toPlaybackTrack } from '../toPlaybackTrack';
import type { BucketTrack } from '../../hooks/useBucketTracks';

const base: BucketTrack = {
  track_id: 't1',
  title: 'Title',
  mix_name: null,
  isrc: null,
  bpm: 128,
  length_ms: 200_000,
  publish_date: null,
  spotify_release_date: null,
  spotify_id: 'sp1',
  release_type: null,
  artists: [{ id: 'a-1', name: 'A', role: 'artist' }, { id: 'a-2', name: 'B', role: 'artist' }],
  label_id: null,
  label_name: null,
  added_at: '2026-01-01T00:00:00Z',
};

describe('toPlaybackTrack', () => {
  it('maps BucketTrack fields to PlaybackTrack', () => {
    expect(toPlaybackTrack(base)).toEqual({
      id: 't1',
      title: 'Title',
      artists: 'A, B',
      cover_url: null,
      duration_ms: 200_000,
      spotify_id: 'sp1',
    });
  });

  it('passes a cover through when the row has one', () => {
    expect(toPlaybackTrack({ ...base, cover_url: 'data:image/svg+xml,x' }).cover_url).toBe('data:image/svg+xml,x');
  });

  it('defaults duration to 0 when length_ms is null', () => {
    expect(toPlaybackTrack({ ...base, length_ms: null }).duration_ms).toBe(0);
  });
});

describe('toPlaybackTrack AI flag', () => {
  it('carries ai_detected so the player can badge the track', () => {
    expect(toPlaybackTrack({ ...base, ai_detected: true }).ai_detected).toBe(true);
  });
});

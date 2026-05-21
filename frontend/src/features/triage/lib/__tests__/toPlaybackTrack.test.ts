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
  is_ai_suspected: false,
  artists: ['A', 'B'],
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

  it('defaults duration to 0 when length_ms is null', () => {
    expect(toPlaybackTrack({ ...base, length_ms: null }).duration_ms).toBe(0);
  });
});

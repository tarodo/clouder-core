import type { BucketTrack } from '../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../playback/lib/types';
import type { PlayerTrackInfo } from '../../playback/TrackPlayer';

export function toPlaybackTrack(t: BucketTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.map(a => a.name).join(', '),
    cover_url: t.cover_url ?? null,
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
    ai_verdict: t.ai_verdict,
  };
}

/** A bucket row as the player shows it. */
export function bucketTrackInfo(t: BucketTrack): PlayerTrackInfo {
  return {
    mixName: t.mix_name,
    artists: t.artists,
    label: t.label_name ? { id: t.label_id, name: t.label_name, ai: t.label_ai } : null,
    bpm: t.bpm,
    key: { camelot: t.key_camelot ?? null, name: t.key_name ?? null },
  };
}

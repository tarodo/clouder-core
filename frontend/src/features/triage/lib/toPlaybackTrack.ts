import type { BucketTrack } from '../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../playback/lib/types';

export function toPlaybackTrack(t: BucketTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.map(a => a.name).join(', '),
    cover_url: null,
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
  };
}

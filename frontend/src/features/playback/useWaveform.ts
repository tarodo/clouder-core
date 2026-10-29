import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { paths } from '../../api/schema';
import { decodeWaveform } from './lib/waveform';

type TrackWaveformResponse =
  paths['/tracks/{track_id}/waveform']['get']['responses'][200]['content']['application/json'];

// Module-level: a stable select runs once per fetch, not on every player tick.
const toLoudness = (d: TrackWaveformResponse) => (d.waveform ? decodeWaveform(d.waveform.data) : null);

/** The track's loudness curve; null when it has no waveform (not read yet, or another edit on Spotify). */
export function useWaveform(trackId: string | undefined) {
  return useQuery({
    queryKey: ['tracks', 'waveform', trackId],
    queryFn: () => api<TrackWaveformResponse>(`/tracks/${trackId}/waveform`),
    select: toLoudness,
    enabled: !!trackId,
    // A missing one appears after the analyzer's next pass (hours), a stored one never changes.
    staleTime: 30 * 60_000,
  });
}

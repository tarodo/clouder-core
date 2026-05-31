import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { MatchCandidatesResponse } from '../lib/playlistTypes';

export function matchCandidatesKey(playlistId: string, trackId: string) {
  return ['match-candidates', playlistId, trackId] as const;
}

export function useMatchCandidates(
  playlistId: string,
  trackId: string,
  enabled: boolean,
): UseQueryResult<MatchCandidatesResponse> {
  return useQuery({
    queryKey: matchCandidatesKey(playlistId, trackId),
    queryFn: () =>
      api<MatchCandidatesResponse>(
        `/playlists/${playlistId}/tracks/${trackId}/match-candidates?vendor=ytmusic`,
      ),
    enabled,
    staleTime: 0,
  });
}

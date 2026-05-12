import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylistTracks } from '../lib/playlistTypes';
import { playlistTracksKey } from '../lib/queryKeys';

export function usePlaylistTracks(
  id: string | undefined,
  limit = 200,
): UseQueryResult<PaginatedPlaylistTracks> {
  return useQuery({
    queryKey: playlistTracksKey(id ?? ''),
    queryFn: () =>
      api<PaginatedPlaylistTracks>(`/playlists/${id}/tracks?limit=${limit}&offset=0`),
    enabled: !!id,
  });
}

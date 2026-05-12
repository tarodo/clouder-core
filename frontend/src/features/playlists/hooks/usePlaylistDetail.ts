import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export function usePlaylistDetail(
  id: string | undefined,
): UseQueryResult<Playlist> {
  return useQuery({
    queryKey: playlistDetailKey(id ?? ''),
    queryFn: () => api<Playlist>(`/playlists/${id}`),
    enabled: !!id,
  });
}

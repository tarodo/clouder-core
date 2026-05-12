import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylists } from '../lib/playlistTypes';
import { playlistsKey } from '../lib/queryKeys';

export interface UsePlaylistsOpts {
  search?: string;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function usePlaylists(
  opts: UsePlaylistsOpts = {},
): UseQueryResult<PaginatedPlaylists> {
  const { search, limit = 20, offset = 0, enabled = true } = opts;
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  if (search && search.trim()) params.set('search', search.trim());
  return useQuery({
    queryKey: playlistsKey(search?.trim() || null),
    queryFn: () => api<PaginatedPlaylists>(`/playlists?${params.toString()}`),
    enabled,
  });
}

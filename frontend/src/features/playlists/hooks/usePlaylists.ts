import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylists, PlaylistStatus } from '../lib/playlistTypes';
import { playlistsKey } from '../lib/queryKeys';

export interface UsePlaylistsOpts {
  search?: string;
  status?: PlaylistStatus;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function usePlaylists(
  opts: UsePlaylistsOpts = {},
): UseQueryResult<PaginatedPlaylists> {
  const { search, status, limit = 20, offset = 0, enabled = true } = opts;
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  if (search && search.trim()) params.set('search', search.trim());
  if (status) params.set('status', status);
  return useQuery({
    queryKey: playlistsKey(`${status ?? 'all'}|${search?.trim() ?? ''}`),
    queryFn: () => api<PaginatedPlaylists>(`/playlists?${params.toString()}`),
    enabled,
  });
}

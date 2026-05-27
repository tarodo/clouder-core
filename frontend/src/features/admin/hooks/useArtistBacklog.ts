import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { BacklogResponse } from '../../../api/artists';

export type ArtistStatusFilter = 'all' | 'none' | 'completed' | 'outdated';

export interface UseArtistBacklogParams {
  style: string;
  status: ArtistStatusFilter;
}

export const artistBacklogKey = (p: UseArtistBacklogParams) =>
  ['admin', 'artistBacklog', p.style, p.status] as const;

export function useArtistBacklog(p: UseArtistBacklogParams) {
  return useInfiniteQuery<BacklogResponse, Error>({
    queryKey: artistBacklogKey(p),
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (p.style) qs.set('style', p.style);
      if (p.status !== 'all') qs.set('status', p.status);
      qs.set('limit', '100');
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<BacklogResponse>(`/admin/artists/backlog?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

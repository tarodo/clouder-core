import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ArtistsListResponse } from '../../../api/artists';

export type ArtistsListMy = 'all' | 'liked' | 'disliked' | 'unrated';

export interface UseArtistsListParams {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
  page: number;
  limit: number;
  my: ArtistsListMy;
}

export const artistsListKey = (params: UseArtistsListParams) =>
  [
    'library',
    'artists',
    params.styleId,
    params.q,
    params.sort,
    params.my,
    params.page,
    params.limit,
  ] as const;

export function useArtistsList(params: UseArtistsListParams) {
  return useQuery<ArtistsListResponse, Error>({
    queryKey: artistsListKey(params),
    queryFn: () => {
      const qs = new URLSearchParams();
      if (params.styleId) qs.set('style', params.styleId);
      if (params.q) qs.set('q', params.q);
      qs.set('sort', params.sort);
      if (params.my !== 'all') qs.set('my', params.my);
      qs.set('page', String(params.page));
      qs.set('limit', String(params.limit));
      return api<ArtistsListResponse>(`/artists?${qs.toString()}`);
    },
    placeholderData: (prev) => prev,
  });
}

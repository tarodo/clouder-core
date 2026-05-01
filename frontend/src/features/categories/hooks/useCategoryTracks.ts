import { useInfiniteQuery, type UseInfiniteQueryResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface TrackArtist {
  id: string;
  name: string;
}

export interface CategoryTrack {
  id: string;
  title: string;
  mix_name: string | null;
  artists: TrackArtist[];
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  isrc: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  added_at: string;
  source_triage_block_id: string | null;
}

export interface PaginatedTracks {
  items: CategoryTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export const categoryTracksKey = (id: string, search: string) =>
  ['categories', 'tracks', id, search] as const;

export function useCategoryTracks(
  categoryId: string,
  search: string,
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (search) params.set('search', search);
      return api<PaginatedTracks>(`/categories/${categoryId}/tracks?${params.toString()}`);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!categoryId,
  });
}

import {
  useInfiniteQuery,
  type UseInfiniteQueryResult,
  type InfiniteData,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface TrackArtist {
  id: string;
  name: string;
}

export interface TrackLabel {
  id: string;
  name: string;
}

export type CategoryTrackSort = 'title' | 'spotify_release_date' | 'added_at';
export type SortOrder = 'asc' | 'desc';

export interface CategoryTagRef {
  id: string;
  name: string;
  color: string | null;
}

export interface CategoryTrack {
  id: string;
  title: string;
  mix_name: string | null;
  artists: TrackArtist[];
  label: TrackLabel | null;
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  spotify_release_date: string | null;
  isrc: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  added_at: string;
  source_triage_block_id: string | null;
  tags: CategoryTagRef[];
}

export interface PaginatedTracks {
  items: CategoryTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export const categoryTracksKey = (
  id: string,
  search: string,
  sort: CategoryTrackSort,
  order: SortOrder,
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
) =>
  ['categories', 'tracks', id, search, sort, order,
   [...tagIds].sort().join(','), tagMatch] as const;

export function useCategoryTracks(
  categoryId: string,
  search: string,
  sort: CategoryTrackSort = 'added_at',
  order: SortOrder = 'desc',
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search, sort, order, tagIds, tagMatch),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
        sort,
        order,
      });
      if (search) params.set('search', search);
      if (tagIds.length > 0) {
        params.set('tags', [...tagIds].sort().join(','));
        if (tagMatch === 'any') params.set('match', 'any');
      }
      return api<PaginatedTracks>(
        `/categories/${categoryId}/tracks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!categoryId,
  });
}

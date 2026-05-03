import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface BucketTrack {
  track_id: string;
  title: string;
  mix_name: string | null;
  isrc: string | null;
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  spotify_release_date: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  artists: string[];
  added_at: string;
}

export interface PaginatedBucketTracks {
  items: BucketTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export const bucketTracksKey = (
  blockId: string,
  bucketId: string,
  search: string,
) => ['triage', 'bucketTracks', blockId, bucketId, search] as const;

export function useBucketTracks(
  blockId: string,
  bucketId: string,
  search: string,
): UseInfiniteQueryResult<InfiniteData<PaginatedBucketTracks>> {
  return useInfiniteQuery({
    queryKey: bucketTracksKey(blockId, bucketId, search),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (search) params.set('search', search);
      return api<PaginatedBucketTracks>(
        `/triage/blocks/${blockId}/buckets/${bucketId}/tracks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!blockId && !!bucketId,
    gcTime: 5 * 60_000,
  });
}

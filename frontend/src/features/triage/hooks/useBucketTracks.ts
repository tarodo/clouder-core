import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AiRep } from '../../library/components/AiRepBadge';

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
  ai_verdict?: 'high' | 'medium' | 'low' | null;
  /** The AI detector pair checked it / the audio profile read it (the player's meta line). */
  ai_checked?: boolean;
  profiled?: boolean;
  artists: { id: string; name: string; role: string; ai?: AiRep | null }[];
  label_id: string | null;
  label_name: string | null;
  /** The label's AI reputation; null/absent = no level. */
  label_ai?: AiRep | null;
  added_at: string;
  key_name?: string | null;
  key_camelot?: string | null;
  /** Release artwork when the API has it (the demo does; production rows carry none yet). */
  cover_url?: string | null;
  /** The recommender's call: keep (null = no keep head yet) and the user's category ids, best first. */
  prediction?: { keep: boolean | null; category_ids: string[]; unsure?: boolean } | null;
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

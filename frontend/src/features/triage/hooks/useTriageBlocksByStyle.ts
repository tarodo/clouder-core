import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export type TriageStatus = 'IN_PROGRESS' | 'FINALIZED';

export interface TriageBlockSummary {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  date_from: string;
  date_to: string;
  status: TriageStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  track_count: number;
}

export interface PaginatedTriageBlocks {
  items: TriageBlockSummary[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export function triageBlocksByStyleKey(
  styleId: string,
  status: TriageStatus | undefined,
) {
  return ['triage', 'byStyle', styleId, status ?? 'all'] as const;
}

export function useTriageBlocksByStyle(
  styleId: string,
  status: TriageStatus | undefined,
): UseInfiniteQueryResult<InfiniteData<PaginatedTriageBlocks>> {
  return useInfiniteQuery({
    queryKey: triageBlocksByStyleKey(styleId, status),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (status) params.set('status', status);
      return api<PaginatedTriageBlocks>(
        `/styles/${styleId}/triage/blocks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!styleId,
    staleTime: 30_000,
  });
}

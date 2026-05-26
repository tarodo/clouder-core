import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RunsListResponse } from '../../../api/labels';

export interface UseRunsParams {
  status: 'all' | 'queued' | 'running' | 'completed' | 'failed';
  source?: 'manual' | 'auto';
}

export function useEnrichmentRuns(p: UseRunsParams) {
  const anyInflight = (data: { pages: RunsListResponse[] } | undefined) =>
    data?.pages.some((page) =>
      page.items.some((r) => r.status === 'queued' || r.status === 'running'),
    ) ?? false;

  return useInfiniteQuery<RunsListResponse, Error>({
    queryKey: ['admin', 'enrichmentRuns', p.status, p.source ?? null] as const,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (p.status !== 'all') qs.set('status', p.status);
      if (p.source) qs.set('source', p.source);
      qs.set('limit', '50');
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<RunsListResponse>(`/admin/labels/enrich-runs?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: (qry) => (anyInflight(qry.state.data) ? 5_000 : false),
  });
}

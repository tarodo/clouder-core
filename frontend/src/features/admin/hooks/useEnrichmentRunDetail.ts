import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RunDetail } from '../../../api/labels';

export function useEnrichmentRunDetail(runId: string | null) {
  return useQuery<RunDetail, Error>({
    queryKey: ['admin', 'enrichmentRun', runId] as const,
    queryFn: () => api<RunDetail>(`/admin/labels/enrich-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (qry) => {
      const s = qry.state.data?.status;
      return s === 'queued' || s === 'running' ? 5_000 : false;
    },
  });
}

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { TriageBucket } from '../lib/bucketLabels';
import type { TriageStatus } from './useTriageBlocksByStyle';

export interface TriageBlock {
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
  buckets: TriageBucket[];
  /** The user's recommender for this style; first_hit is the share of first-button-right over first_n tracks. */
  model?: { trained_at: string; n_labels: number; first_hit: number | null; first_n: number } | null;
  correlation_id?: string;
}

export const triageBlockKey = (id: string) => ['triage', 'blockDetail', id] as const;

export function useTriageBlock(id: string): UseQueryResult<TriageBlock> {
  return useQuery({
    queryKey: triageBlockKey(id),
    queryFn: () => api<TriageBlock>(`/triage/blocks/${id}`),
    enabled: !!id,
    staleTime: 30_000,
  });
}

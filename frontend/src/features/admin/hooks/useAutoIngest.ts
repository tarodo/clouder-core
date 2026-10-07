import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoIngestState } from '../../../api/autoIngest';

export const AUTO_INGEST_KEY = ['admin', 'autoIngest'] as const;

export function useAutoIngest() {
  return useQuery<AutoIngestState, Error>({
    queryKey: AUTO_INGEST_KEY,
    queryFn: () => api<AutoIngestState>('/admin/auto-ingest'),
    staleTime: 60_000,
  });
}

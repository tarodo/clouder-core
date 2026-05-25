import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigResponse } from '../../../api/autoEnrich';

export function useAutoEnrichConfig() {
  return useQuery<AutoEnrichConfigResponse, Error>({
    queryKey: ['admin', 'autoEnrich', 'labels'],
    queryFn: () => api<AutoEnrichConfigResponse>('/admin/auto-enrich/labels'),
    staleTime: 5 * 60_000,
  });
}

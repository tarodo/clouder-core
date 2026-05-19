import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichmentOptions } from '../../../api/labels';

export function useEnrichmentOptions() {
  return useQuery<EnrichmentOptions, Error>({
    queryKey: ['admin', 'enrichment', 'options'],
    queryFn: () => api<EnrichmentOptions>('/admin/labels/enrich/options'),
    staleTime: 30 * 60_000,
  });
}

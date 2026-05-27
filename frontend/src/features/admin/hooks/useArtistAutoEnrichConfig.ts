import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigResponse } from '../../../api/artistAutoEnrich';

export function useArtistAutoEnrichConfig() {
  return useQuery<AutoEnrichConfigResponse, Error>({
    queryKey: ['admin', 'autoEnrich', 'artists'],
    queryFn: () => api<AutoEnrichConfigResponse>('/admin/auto-enrich/artists'),
    staleTime: 5 * 60_000,
  });
}

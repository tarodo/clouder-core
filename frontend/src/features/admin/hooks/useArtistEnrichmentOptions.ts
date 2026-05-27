import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichmentOptions } from '../../../api/artists';

export function useArtistEnrichmentOptions() {
  return useQuery<EnrichmentOptions, Error>({
    queryKey: ['admin', 'artistEnrichment', 'options'],
    queryFn: () => api<EnrichmentOptions>('/admin/artists/enrich/options'),
    staleTime: 30 * 60_000,
  });
}

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichBody } from '../../../api/artists';

interface EnqueueResponse { run_id: string; queued_artists: number; }

export function useEnqueueArtistEnrichment() {
  const qc = useQueryClient();
  return useMutation<EnqueueResponse, Error, EnrichBody>({
    mutationFn: (body) =>
      api<EnqueueResponse>('/admin/artists/enrich', {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'artistBacklog'] });
      qc.invalidateQueries({ queryKey: ['admin', 'artistEnrichmentRuns'] });
    },
  });
}

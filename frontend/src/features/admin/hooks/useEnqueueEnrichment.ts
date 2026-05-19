import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichBody } from '../../../api/labels';

interface EnqueueResponse { run_id: string; queued_labels: number; }

export function useEnqueueEnrichment() {
  const qc = useQueryClient();
  return useMutation<EnqueueResponse, Error, EnrichBody>({
    mutationFn: (body) =>
      api<EnqueueResponse>('/admin/labels/enrich', {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'labelBacklog'] });
      qc.invalidateQueries({ queryKey: ['admin', 'enrichmentRuns'] });
    },
  });
}

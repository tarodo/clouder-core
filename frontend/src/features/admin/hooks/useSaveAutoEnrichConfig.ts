import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigBody } from '../../../api/autoEnrich';

export function useSaveAutoEnrichConfig() {
  const qc = useQueryClient();
  return useMutation<void, Error, AutoEnrichConfigBody>({
    mutationFn: (body) =>
      api<void>('/admin/auto-enrich/labels', {
        method: 'PUT',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'autoEnrich', 'labels'] });
    },
  });
}

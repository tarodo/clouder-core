import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigBody } from '../../../api/artistAutoEnrich';

export function useSaveArtistAutoEnrichConfig() {
  const qc = useQueryClient();
  return useMutation<void, Error, AutoEnrichConfigBody>({
    mutationFn: (body) =>
      api<void>('/admin/auto-enrich/artists', {
        method: 'PUT',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'autoEnrich', 'artists'] });
    },
  });
}

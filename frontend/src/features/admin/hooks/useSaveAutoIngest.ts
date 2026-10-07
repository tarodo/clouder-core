import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoIngestSettingsBody, AutoIngestState } from '../../../api/autoIngest';
import { AUTO_INGEST_KEY } from './useAutoIngest';

export function useSaveAutoIngest() {
  const qc = useQueryClient();
  return useMutation<AutoIngestState, Error, AutoIngestSettingsBody>({
    mutationFn: (body) =>
      api<AutoIngestState>('/admin/auto-ingest', {
        method: 'PUT',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    // Replanning runs asynchronously; refetch shortly to pick up the new planned runs.
    onSuccess: (data) => {
      qc.setQueryData(AUTO_INGEST_KEY, data);
      setTimeout(() => qc.invalidateQueries({ queryKey: AUTO_INGEST_KEY }), 5_000);
    },
  });
}

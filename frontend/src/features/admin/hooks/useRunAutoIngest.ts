import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api/client';

export function useRunAutoIngest() {
  return useMutation<{ accepted: boolean }, Error, void>({
    mutationFn: () => api<{ accepted: boolean }>('/admin/auto-ingest/run', { method: 'POST' }),
  });
}

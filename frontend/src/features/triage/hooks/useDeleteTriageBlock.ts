import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { triageBlocksByStyleKey, type TriageStatus } from './useTriageBlocksByStyle';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useDeleteTriageBlock(
  styleId: string,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (blockId) =>
      api<void>(`/triage/blocks/${blockId}`, { method: 'DELETE' }),
    onSuccess: () => {
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}

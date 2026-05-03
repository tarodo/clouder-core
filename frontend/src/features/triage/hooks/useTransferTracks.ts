import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { triageBlockKey } from './useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export interface TransferInput {
  targetBlockId: string;
  targetBucketId: string;
  trackIds: string[];
  styleId: string;
}

export interface TransferResponse {
  transferred: number;
  correlation_id?: string;
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useTransferTracks(
  srcBlockId: string,
): UseMutationResult<TransferResponse, ApiError, TransferInput> {
  const qc = useQueryClient();
  return useMutation<TransferResponse, ApiError, TransferInput>({
    mutationKey: ['triage', 'transfer', srcBlockId],
    mutationFn: (input) =>
      api<TransferResponse>(`/triage/blocks/${srcBlockId}/transfer`, {
        method: 'POST',
        body: JSON.stringify({
          target_bucket_id: input.targetBucketId,
          track_ids: input.trackIds,
        }),
      }),
    onSuccess: (_data, input) => {
      qc.invalidateQueries({
        queryKey: ['triage', 'bucketTracks', input.targetBlockId, input.targetBucketId],
      });
      qc.invalidateQueries({ queryKey: triageBlockKey(input.targetBlockId) });
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(input.styleId, s) });
      }
    },
  });
}

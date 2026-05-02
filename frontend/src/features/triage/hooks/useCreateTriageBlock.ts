import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import {
  schedulePendingCreateRecovery,
  type PendingCreatePayload,
  type PendingPage,
} from '../lib/pendingCreateRecovery';
import {
  triageBlocksByStyleKey,
  type PaginatedTriageBlocks,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export class PendingCreateError extends Error {
  readonly kind = 'pending';
  constructor() {
    super('Triage block creation is taking longer than usual.');
    this.name = 'PendingCreateError';
  }
}

export interface CreateTriageBlockInput {
  style_id: string;
  name: string;
  date_from: string;
  date_to: string;
}

export interface TriageBlockDetail {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  date_from: string;
  date_to: string;
  status: TriageStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  buckets: unknown[];
}

const STATUSES: (TriageStatus | undefined)[] = [
  'IN_PROGRESS',
  'FINALIZED',
  undefined,
];

interface UseCreateOptions {
  onPendingSuccess?: () => void;
  onPendingFailure?: () => void;
}

export function useCreateTriageBlock(
  styleId: string,
  options: UseCreateOptions = {},
): UseMutationResult<TriageBlockDetail, Error, CreateTriageBlockInput> {
  const qc = useQueryClient();

  const refetchAllTabs = async (): Promise<PendingPage[]> => {
    const pages: PendingPage[] = [];
    for (const status of STATUSES) {
      const key = triageBlocksByStyleKey(styleId, status);
      await qc.invalidateQueries({ queryKey: key });
      const data = qc.getQueryData<{ pages: PaginatedTriageBlocks[] }>(key);
      if (data) {
        for (const page of data.pages) {
          pages.push({ items: page.items, total: page.total });
        }
      }
    }
    return pages;
  };

  return useMutation<TriageBlockDetail, Error, CreateTriageBlockInput>({
    mutationFn: async (input) => {
      try {
        return await api<TriageBlockDetail>('/triage/blocks', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      } catch (err) {
        if (
          err instanceof ApiError &&
          (err.status === 503 || err.code === 'cold_start')
        ) {
          const payload: PendingCreatePayload = {
            name: input.name,
            date_from: input.date_from,
            date_to: input.date_to,
          };
          schedulePendingCreateRecovery({
            payload,
            refetchAllTabs,
            onSuccess: () => options.onPendingSuccess?.(),
            onFailure: () => options.onPendingFailure?.(),
          });
          throw new PendingCreateError();
        }
        throw err;
      }
    },
    onSuccess: () => {
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { categoriesByStyleKey } from '../../categories/hooks/useCategoriesByStyle';
import { categoryDetailKey } from '../../categories/hooks/useCategoryDetail';
import { triageBlockKey, type TriageBlock } from './useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export interface FinalizeResponse {
  block: TriageBlock;
  /** Map of promoted category_id → tracks_added count. */
  promoted: Record<string, number>;
  correlation_id?: string;
}

export interface InactiveBucketRow {
  id: string;
  category_id: string;
  track_count: number;
}

export interface FinalizeErrorBody {
  error_code: string;
  message: string;
  inactive_buckets?: InactiveBucketRow[];
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useFinalizeTriageBlock(
  blockId: string,
  styleId: string,
): UseMutationResult<FinalizeResponse, ApiError, void> {
  const qc = useQueryClient();
  return useMutation<FinalizeResponse, ApiError, void>({
    mutationKey: ['triage', 'finalize', blockId],
    mutationFn: () =>
      api<FinalizeResponse>(`/triage/blocks/${blockId}/finalize`, {
        method: 'POST',
      }),
    onSuccess: (data) => {
      // Triage block detail (status flips to FINALIZED, finalized_at populated).
      qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });

      // All status filters of the byStyle list (IN_PROGRESS, FINALIZED, "all").
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }

      // Categories list (track_count bumped on every promoted category).
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });

      // Per promoted category: detail card and any open tracks list (regardless
      // of search query). categoryTracksKey is ['categories', 'tracks', id, search]
      // so we use a predicate to invalidate every search variant in cache.
      for (const categoryId of Object.keys(data.promoted ?? {})) {
        qc.invalidateQueries({ queryKey: categoryDetailKey(categoryId) });
        qc.invalidateQueries({
          predicate: (q) =>
            Array.isArray(q.queryKey) &&
            q.queryKey[0] === 'categories' &&
            q.queryKey[1] === 'tracks' &&
            q.queryKey[2] === categoryId,
        });
      }
    },
  });
}

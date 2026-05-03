import {
  useMutation,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { type PaginatedBucketTracks } from './useBucketTracks';
import { triageBlockKey, type TriageBlock } from './useTriageBlock';
import { triageBlocksByStyleKey, type TriageStatus } from './useTriageBlocksByStyle';

export interface MoveInput {
  fromBucketId: string;
  toBucketId: string;
  trackIds: string[];
}

export interface MoveResponse {
  moved: number;
  correlation_id?: string;
}

export interface MoveSnapshot {
  source: [readonly unknown[], unknown][];
  block: TriageBlock | undefined;
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function takeSnapshot(
  qc: QueryClient,
  blockId: string,
  fromBucketId: string,
): MoveSnapshot {
  const source = qc.getQueriesData({
    queryKey: ['triage', 'bucketTracks', blockId, fromBucketId],
  }) as [readonly unknown[], unknown][];
  const block = qc.getQueryData<TriageBlock>(triageBlockKey(blockId));
  return { source, block };
}

export function applyOptimisticMove(
  qc: QueryClient,
  blockId: string,
  input: MoveInput,
): void {
  qc.setQueriesData(
    { queryKey: ['triage', 'bucketTracks', blockId, input.fromBucketId] },
    (old: { pages: PaginatedBucketTracks[]; pageParams: unknown[] } | undefined) => {
      if (!old) return old;
      return {
        ...old,
        pages: old.pages.map((p) => ({
          ...p,
          items: p.items.filter((t) => !input.trackIds.includes(t.track_id)),
          total: Math.max(0, p.total - input.trackIds.length),
        })),
      };
    },
  );
  qc.setQueryData<TriageBlock | undefined>(triageBlockKey(blockId), (old) => {
    if (!old) return old;
    return {
      ...old,
      buckets: old.buckets.map((b) => {
        if (b.id === input.fromBucketId) {
          return { ...b, track_count: Math.max(0, b.track_count - input.trackIds.length) };
        }
        if (b.id === input.toBucketId) {
          return { ...b, track_count: b.track_count + input.trackIds.length };
        }
        return b;
      }),
    };
  });
}

export function restoreSnapshot(
  qc: QueryClient,
  blockId: string,
  snap: MoveSnapshot,
): void {
  for (const [key, val] of snap.source) {
    qc.setQueryData(key, val);
  }
  if (snap.block !== undefined) {
    qc.setQueryData(triageBlockKey(blockId), snap.block);
  }
}

/**
 * Direct apiClient call for the Undo button.
 *
 * Why bypass `useMoveTracks.mutate`? Going through the hook would trigger a
 * second `onMutate` cycle (cancel queries, snapshot, optimistic write) and on
 * `onSuccess` invalidate the now-source bucket — causing a refetch flicker
 * during the brief window where the cache still reflects the post-move state
 * before the network round-trips. Restoring the original snapshot synchronously
 * before firing the inverse HTTP call avoids the flicker entirely.
 */
export async function undoMoveDirect(
  qc: QueryClient,
  blockId: string,
  styleId: string,
  originalInput: MoveInput,
  snapshot: MoveSnapshot,
): Promise<void> {
  // 1. Restore caches to pre-move state synchronously.
  restoreSnapshot(qc, blockId, snapshot);

  // 2. Fire inverse HTTP call.
  try {
    await api<MoveResponse>(`/triage/blocks/${blockId}/move`, {
      method: 'POST',
      body: JSON.stringify({
        from_bucket_id: originalInput.toBucketId,
        to_bucket_id: originalInput.fromBucketId,
        track_ids: originalInput.trackIds,
      }),
    });
  } catch (err) {
    // Inverse failed — re-apply the optimistic write so the UI matches reality.
    applyOptimisticMove(qc, blockId, originalInput);
    throw err;
  }

  // 3. Invalidate caches affected by the inverse move.
  qc.invalidateQueries({ queryKey: ['triage', 'bucketTracks', blockId, originalInput.toBucketId] });
  qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
  for (const s of STATUSES) {
    qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
  }
}

export function useMoveTracks(
  blockId: string,
  styleId: string,
): UseMutationResult<MoveResponse, ApiError, MoveInput, MoveSnapshot> {
  const qc = useQueryClient();
  return useMutation<MoveResponse, ApiError, MoveInput, MoveSnapshot>({
    mutationKey: ['triage', 'move', blockId],
    mutationFn: (input) =>
      api<MoveResponse>(`/triage/blocks/${blockId}/move`, {
        method: 'POST',
        body: JSON.stringify({
          from_bucket_id: input.fromBucketId,
          to_bucket_id: input.toBucketId,
          track_ids: input.trackIds,
        }),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({
        queryKey: ['triage', 'bucketTracks', blockId, input.fromBucketId],
      });
      await qc.cancelQueries({ queryKey: triageBlockKey(blockId) });
      const snap = takeSnapshot(qc, blockId, input.fromBucketId);
      applyOptimisticMove(qc, blockId, input);
      return snap;
    },
    onError: (_err, _input, context) => {
      if (context) restoreSnapshot(qc, blockId, context);
    },
    onSuccess: (_data, input) => {
      qc.invalidateQueries({
        queryKey: ['triage', 'bucketTracks', blockId, input.toBucketId],
      });
      qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}

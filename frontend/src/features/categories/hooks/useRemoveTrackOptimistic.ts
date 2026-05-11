import { useMutation, useQueryClient, type UseMutationResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { PaginatedTracks } from './useCategoryTracks';

export interface RemoveTrackInput {
  categoryId: string;
  trackId: string;
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function shrink(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  let removed = 0;
  const pages = data.pages.map((p) => {
    const before = p.items.length;
    const items = p.items.filter((it) => it.id !== trackId);
    removed += before - items.length;
    return { ...p, items };
  });
  if (removed === 0) return data;
  return {
    ...data,
    pages: pages.map((p, idx) =>
      idx === 0 ? { ...p, total: Math.max(0, p.total - removed) } : p,
    ),
  };
}

export function useRemoveTrackOptimistic(): UseMutationResult<
  void,
  Error,
  RemoveTrackInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackInput, MutationContext>({
    mutationFn: async ({ categoryId, trackId }) => {
      try {
        await api(`/categories/${categoryId}/tracks/${trackId}`, { method: 'DELETE' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'track_not_in_category') {
          return; // idempotent: post-state already matches goal
        }
        throw err;
      }
    },
    onMutate: async ({ categoryId, trackId }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key }, (old) =>
        shrink(old, trackId),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) {
        qc.setQueryData(key, data);
      }
    },
    onSettled: (_d, _e, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
      qc.invalidateQueries({ queryKey: ['categories'] });
    },
  });
}

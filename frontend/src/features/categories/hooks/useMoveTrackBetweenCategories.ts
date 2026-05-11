import { useMutation, useQueryClient, type UseMutationResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from './useCategoryTracks';

export class MovePartialError extends Error {
  constructor(readonly cause: unknown) {
    super('Move partially completed: track was added to target but could not be removed from source');
    this.name = 'MovePartialError';
  }
}

export interface MoveTrackInput {
  trackId: string;
  fromCategoryId: string;
  toCategoryId: string;
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

export function useMoveTrackBetweenCategories(): UseMutationResult<
  void,
  Error,
  MoveTrackInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, MoveTrackInput, MutationContext>({
    mutationFn: async ({ trackId, fromCategoryId, toCategoryId }) => {
      await api(`/categories/${toCategoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_id: trackId }),
      });
      try {
        await api(`/categories/${fromCategoryId}/tracks/${trackId}`, { method: 'DELETE' });
      } catch (err) {
        throw new MovePartialError(err);
      }
    },
    onMutate: async ({ trackId, fromCategoryId }) => {
      const key = ['categories', 'tracks', fromCategoryId] as const;
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
    onSettled: (_d, _e, { fromCategoryId, toCategoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', fromCategoryId] });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', toCategoryId] });
      qc.invalidateQueries({ queryKey: ['categories'] });
    },
  });
}

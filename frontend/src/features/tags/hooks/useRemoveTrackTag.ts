import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface RemoveTrackTagInput {
  categoryId: string;
  trackId: string;
  tagId: string;
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function patch(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
  tagId: string,
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  let changed = 0;
  const pages = data.pages.map((p) => {
    let pageChanged = 0;
    const items = p.items.map((it) => {
      if (it.id !== trackId) return it;
      const filtered = it.tags.filter((t) => t.id !== tagId);
      if (filtered.length === it.tags.length) return it;
      pageChanged += 1;
      return { ...it, tags: filtered };
    });
    if (pageChanged === 0) return p;
    changed += pageChanged;
    return { ...p, items };
  });
  if (changed === 0) return data;
  return { ...data, pages };
}

export function useRemoveTrackTag(): UseMutationResult<
  void,
  Error,
  RemoveTrackTagInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackTagInput, MutationContext>({
    mutationFn: async ({ trackId, tagId }) => {
      await api(`/tracks/${trackId}/tags/${tagId}`, { method: 'DELETE' });
    },
    onMutate: async ({ categoryId, trackId, tagId }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>(
        { queryKey: key },
        (old) => patch(old, trackId, tagId),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) qc.setQueryData(key, data);
    },
    onSettled: (_d, _e, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}

import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface AddTrackTagInput {
  categoryId: string;
  trackId: string;
  tag: { id: string; name: string; color: string | null };
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function patch(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
  tag: AddTrackTagInput['tag'],
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  let changed = 0;
  const pages = data.pages.map((p) => {
    let pageChanged = 0;
    const items = p.items.map((it) => {
      if (it.id !== trackId) return it;
      if (it.tags.some((t) => t.id === tag.id)) return it;
      pageChanged += 1;
      return { ...it, tags: [...it.tags, tag] };
    });
    if (pageChanged === 0) return p;
    changed += pageChanged;
    return { ...p, items };
  });
  if (changed === 0) return data;
  return { ...data, pages };
}

export function useAddTrackTag(): UseMutationResult<
  void,
  Error,
  AddTrackTagInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, AddTrackTagInput, MutationContext>({
    mutationFn: async ({ trackId, tag }) => {
      await api(`/tracks/${trackId}/tags`, {
        method: 'POST',
        body: JSON.stringify({ tag_id: tag.id }),
      });
    },
    onMutate: async ({ categoryId, trackId, tag }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>(
        { queryKey: key },
        (old) => patch(old, trackId, tag),
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

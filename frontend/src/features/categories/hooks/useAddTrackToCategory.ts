import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface AddTrackToCategoryInput {
  categoryId: string;
  trackId: string;
  /** Undo of a removal: the removed row's values, so it returns to its old place. */
  restore?: { added_at: string; source_triage_block_id: string | null };
}

export function useAddTrackToCategory(): UseMutationResult<
  unknown,
  Error,
  AddTrackToCategoryInput
> {
  const qc = useQueryClient();
  return useMutation<unknown, Error, AddTrackToCategoryInput>({
    mutationFn: ({ categoryId, trackId, restore }) =>
      api(`/categories/${categoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({
          track_id: trackId,
          ...(restore && { added_at: restore.added_at }),
          ...(restore?.source_triage_block_id && {
            source_triage_block_id: restore.source_triage_block_id,
          }),
        }),
      }),
    onSuccess: (_data, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}

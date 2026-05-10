import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface RemoveTrackFromCategoryInput {
  categoryId: string;
  trackId: string;
}

export function useRemoveTrackFromCategory(): UseMutationResult<
  unknown,
  Error,
  RemoveTrackFromCategoryInput
> {
  const qc = useQueryClient();
  return useMutation<unknown, Error, RemoveTrackFromCategoryInput>({
    mutationFn: ({ categoryId, trackId }) =>
      api(`/categories/${categoryId}/tracks/${trackId}`, { method: 'DELETE' }),
    onSuccess: (_data, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}

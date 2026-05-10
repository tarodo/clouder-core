import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface AddTrackToCategoryInput {
  categoryId: string;
  trackId: string;
}

export function useAddTrackToCategory(): UseMutationResult<
  unknown,
  Error,
  AddTrackToCategoryInput
> {
  const qc = useQueryClient();
  return useMutation<unknown, Error, AddTrackToCategoryInput>({
    mutationFn: ({ categoryId, trackId }) =>
      api(`/categories/${categoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_id: trackId }),
      }),
    onSuccess: (_data, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}

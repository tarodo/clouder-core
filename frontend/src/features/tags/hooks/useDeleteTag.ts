import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { tagsKey } from './useTags';

export interface DeleteTagInput {
  tagId: string;
}

export function useDeleteTag(): UseMutationResult<void, Error, DeleteTagInput> {
  const qc = useQueryClient();
  return useMutation<void, Error, DeleteTagInput>({
    mutationFn: async ({ tagId }) => {
      try {
        await api(`/tags/${tagId}`, { method: 'DELETE' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'tag_not_found') {
          return;
        }
        throw err;
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
      // Server cascades the FK; drop pills from any cached track list.
      qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
  });
}

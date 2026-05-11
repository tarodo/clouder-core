import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RenameTagInput } from '../lib/tagSchemas';
import { tagsKey, type Tag } from './useTags';

export interface RenameTagArgs {
  tagId: string;
  patch: RenameTagInput;
}

export function useRenameTag(): UseMutationResult<Tag, Error, RenameTagArgs> {
  const qc = useQueryClient();
  return useMutation<Tag, Error, RenameTagArgs>({
    mutationFn: ({ tagId, patch }) =>
      api<Tag>(`/tags/${tagId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
    },
  });
}

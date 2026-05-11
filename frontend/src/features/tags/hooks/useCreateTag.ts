import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CreateTagInput } from '../lib/tagSchemas';
import { tagsKey, type Tag } from './useTags';

export function useCreateTag(): UseMutationResult<Tag, Error, CreateTagInput> {
  const qc = useQueryClient();
  return useMutation<Tag, Error, CreateTagInput>({
    mutationFn: (input) =>
      api<Tag>('/tags', { method: 'POST', body: JSON.stringify(input) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
    },
  });
}

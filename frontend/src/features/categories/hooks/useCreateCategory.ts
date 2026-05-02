import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CreateCategoryInput } from '../lib/categorySchemas';
import { categoriesByStyleKey, type Category } from './useCategoriesByStyle';

export function useCreateCategory(
  styleId: string,
): UseMutationResult<Category, Error, CreateCategoryInput> {
  const qc = useQueryClient();
  return useMutation<Category, Error, CreateCategoryInput>({
    mutationFn: (input) =>
      api<Category>(`/styles/${styleId}/categories`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
    },
  });
}

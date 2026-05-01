import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { categoriesByStyleKey } from './useCategoriesByStyle';

export function useDeleteCategory(
  styleId: string,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (categoryId: string) => {
      await api(`/categories/${categoryId}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
    },
  });
}

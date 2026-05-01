import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RenameCategoryInput } from '../lib/categorySchemas';
import {
  categoriesByStyleKey,
  type Category,
  type PaginatedCategories,
} from './useCategoriesByStyle';
import { categoryDetailKey } from './useCategoryDetail';

interface Snapshot {
  list: PaginatedCategories | undefined;
  detail: Category | undefined;
}

export function useRenameCategory(
  categoryId: string,
  styleId: string,
): UseMutationResult<Category, Error, RenameCategoryInput, Snapshot> {
  const qc = useQueryClient();
  return useMutation<Category, Error, RenameCategoryInput, Snapshot>({
    mutationFn: (input) =>
      api<Category>(`/categories/${categoryId}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: categoriesByStyleKey(styleId) });
      await qc.cancelQueries({ queryKey: categoryDetailKey(categoryId) });
      const list = qc.getQueryData<PaginatedCategories>(categoriesByStyleKey(styleId));
      const detail = qc.getQueryData<Category>(categoryDetailKey(categoryId));
      if (list) {
        qc.setQueryData<PaginatedCategories>(categoriesByStyleKey(styleId), {
          ...list,
          items: list.items.map((c) =>
            c.id === categoryId ? { ...c, name: input.name } : c,
          ),
        });
      }
      if (detail) {
        qc.setQueryData<Category>(categoryDetailKey(categoryId), { ...detail, name: input.name });
      }
      return { list, detail };
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.list) qc.setQueryData(categoriesByStyleKey(styleId), ctx.list);
      if (ctx?.detail) qc.setQueryData(categoryDetailKey(categoryId), ctx.detail);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
      qc.invalidateQueries({ queryKey: categoryDetailKey(categoryId) });
    },
  });
}

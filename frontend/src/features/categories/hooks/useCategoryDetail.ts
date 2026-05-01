import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Category } from './useCategoriesByStyle';

export const categoryDetailKey = (id: string) => ['categories', 'detail', id] as const;

export function useCategoryDetail(id: string): UseQueryResult<Category> {
  return useQuery({
    queryKey: categoryDetailKey(id),
    queryFn: () => api<Category>(`/categories/${id}`),
    enabled: !!id,
  });
}

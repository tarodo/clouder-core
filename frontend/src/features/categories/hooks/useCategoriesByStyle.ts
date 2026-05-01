import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Category {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  position: number;
  track_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaginatedCategories {
  items: Category[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export const categoriesByStyleKey = (styleId: string) => ['categories', 'byStyle', styleId] as const;

export function useCategoriesByStyle(styleId: string): UseQueryResult<PaginatedCategories> {
  return useQuery({
    queryKey: categoriesByStyleKey(styleId),
    queryFn: () => api<PaginatedCategories>(`/styles/${styleId}/categories?limit=200&offset=0`),
    enabled: !!styleId,
  });
}

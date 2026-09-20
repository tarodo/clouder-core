import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../api/client';

export interface CatalogStyle {
  id: string;
  name: string;
  selected: boolean;
  position: number | null;
}

export interface PaginatedCatalogStyles {
  items: CatalogStyle[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export const allStylesKey = ['styles', 'all'] as const;

/** Whole style catalog, annotated with the caller's selection. */
export function useAllStyles(): UseQueryResult<PaginatedCatalogStyles> {
  return useQuery({
    queryKey: allStylesKey,
    queryFn: () =>
      api<PaginatedCatalogStyles>('/styles?scope=all&limit=200&offset=0'),
    staleTime: 5 * 60 * 1000,
  });
}

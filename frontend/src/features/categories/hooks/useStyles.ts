import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Style {
  id: string;
  name: string;
}

export interface PaginatedStyles {
  items: Style[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export function useStyles(): UseQueryResult<PaginatedStyles> {
  return useQuery({
    queryKey: ['styles'],
    queryFn: () => api<PaginatedStyles>('/styles?limit=200&offset=0'),
    staleTime: 5 * 60 * 1000,
  });
}

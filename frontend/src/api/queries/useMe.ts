import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../client';
import type { Me } from '../../auth/AuthProvider';

export function useMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api<Me>('/me'),
  });
}

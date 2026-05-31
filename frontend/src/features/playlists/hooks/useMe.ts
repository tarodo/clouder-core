import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { MeResponse } from '../lib/playlistTypes';

export function useMe(): UseQueryResult<MeResponse, Error> {
  return useQuery<MeResponse, Error>({
    queryKey: ['me'],
    queryFn: () => api<MeResponse>('/me'),
    staleTime: 60_000,
  });
}

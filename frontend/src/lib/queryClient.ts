import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '../api/error';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, err) => {
          if (err instanceof ApiError && (err.code === 'forbidden' || err.code === 'not_found')) {
            return false;
          }
          return count < 2;
        },
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

export const queryClient = createQueryClient();

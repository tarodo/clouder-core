import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface RetryInput {
  publish_date_from: string;
  publish_date_to: string;
}

export interface RetryResponse {
  queued_count: number;
}

export function useRetrySpotifySearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RetryInput) =>
      api<RetryResponse>('/admin/spotify/retry-not-found', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'spotifyNotFound'] });
      queryClient.invalidateQueries({ queryKey: ['admin', 'coverage'] });
    },
  });
}
